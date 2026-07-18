"""Bundled live dashboard endpoints.

GET /live              — all active games with predictions + edge, sorted by top_edge desc
GET /live/{game_pk}    — single game (404 if no live_state row)
POST /admin/reload-stats — force a stats-cache reload (returns updated counts)
"""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from backend.api.live_store import get_store
from backend.db.client import get_client
from backend.ingestion.odds_stub import calculate_edge, get_odds
from backend.models._persist import current_pa_position, insert_predictions
from backend.models.predictor import PitchPredictor
from backend.models.stats_cache import get_cache

router = APIRouter(tags=["live"])

_predictor = PitchPredictor()

# game_pk -> (last_pitch_ts, payload). Lets /live skip predictor + DB work
# when nothing has changed since the last build.
_payload_cache: dict[int, tuple[str | None, dict]] = {}


def _player_name(player_id: int | None) -> str | None:
    if player_id is None:
        return None
    info = get_cache().get_player_info(player_id)
    return (info or {}).get("full_name") if info else None


def _context_from(ls: dict) -> dict:
    return {
        "game_pk":        ls.get("game_pk"),
        "pitcher_id":     ls.get("pitcher_id"),
        "batter_id":      ls.get("batter_id"),
        "balls":          ls.get("balls"),
        "strikes":        ls.get("strikes"),
        "pitch_count_pa": ls.get("pitch_count_pa"),
        "inning":         ls.get("inning"),
    }


def _situation(ls: dict) -> dict:
    balls = ls.get("balls") or 0
    strikes = ls.get("strikes") or 0
    return {
        "inning": ls.get("inning"),
        "half": "▲" if ls.get("top_inning") else "▼",
        "count": f"{balls}-{strikes}",
        "outs": ls.get("outs"),
        "pitcher_id": ls.get("pitcher_id"),
        "batter_id": ls.get("batter_id"),
        "pitch_count_pa": ls.get("pitch_count_pa"),
        "last_pitch_ts": ls.get("last_pitch_ts"),
    }


def _ou_market(
    pred: dict,
    predicted_value: float,
    line: float | None,
    over_price: int | None,
    under_price: int | None,
) -> dict:
    if line is None or predicted_value is None:
        return {
            "market": pred["market"],
            "predicted_value": predicted_value,
            "recommendation": None,
            "line": None,
            "price": None,
            "edge": None,
            "confidence": pred["confidence"],
            "probs": None,
            "sample_size": pred.get("sample_size", 0),
            "model_version": pred["model_version"],
            "features_used": pred.get("features_used", []),
        }
    if predicted_value > line:
        side, price = "over", over_price
    else:
        side, price = "under", under_price
    edge = calculate_edge(pred["confidence"], price) if price is not None else None
    return {
        "market": pred["market"],
        "predicted_value": predicted_value,
        "recommendation": side,
        "line": line,
        "price": price,
        "edge": edge,
        "confidence": pred["confidence"],
        "probs": None,
        "sample_size": pred.get("sample_size", 0),
        "model_version": pred["model_version"],
        "features_used": pred.get("features_used", []),
    }


def _argmax_market(pred: dict) -> dict:
    name, prob = max(pred["probs"].items(), key=lambda kv: kv[1])
    return {
        "market": pred["market"],
        "predicted_value": prob,
        "recommendation": name,
        "line": None,
        "price": None,
        "edge": None,
        "confidence": pred["confidence"],
        "probs": pred["probs"],
        "sample_size": pred.get("sample_size", 0),
        "model_version": pred["model_version"],
        "features_used": pred.get("features_used", []),
    }


def _market_sort_key(m: dict):
    edge = m.get("edge")
    return (edge is None, -(edge or 0.0))


def _pa_predictions(game_pk: int, ls: dict, markets: list[dict]) -> list[dict]:
    """Per-pitch prediction history for the current PA (pitch_result +
    pitch_speed_ou), matching the hosted api fn's contract: pitch_number is the
    pitches-thrown count when the row was scored, so it predicts pitch
    pitch_number + 1. Past positions come from the predictions audit table;
    the current position comes from the fresher in-request markets (the audit
    write is fire-and-forget and may not have landed yet)."""
    by_pos: dict[tuple[str, int], dict] = {}
    try:
        rows = (
            get_client().table("predictions")
            .select("at_bat_index,pitch_number,market,predicted_value,recommendation,line,confidence,probs,result")
            .eq("game_pk", game_pk)
            .in_("market", ["pitch_result", "pitch_speed_ou"])
            .order("id", desc=True)
            .limit(40)
            .execute().data
            or []
        )
    except Exception as exc:
        print(f"[live] pa_predictions failed game={game_pk}: {exc}")
        rows = []
    cur_abi = max((r["at_bat_index"] for r in rows if r.get("at_bat_index") is not None), default=None)
    for r in rows:
        if cur_abi is None or r.get("at_bat_index") != cur_abi:
            continue
        pos = r.get("pitch_number") or 0
        key = (r["market"], pos)
        if key in by_pos:  # rows are newest-first; keep the freshest per position
            continue
        by_pos[key] = {
            "market": r["market"],
            "pitch_number": pos,
            "predicted_value": r.get("predicted_value"),
            "recommendation": r.get("recommendation"),
            "line": r.get("line"),
            "confidence": r.get("confidence"),
            "probs": r.get("probs"),
            "result": r.get("result"),
        }
    pos_now = int(ls.get("pitch_count_pa") or 0)
    for m in markets:
        if m["market"] not in ("pitch_result", "pitch_speed_ou"):
            continue
        by_pos[(m["market"], pos_now)] = {
            "market": m["market"],
            "pitch_number": pos_now,
            "predicted_value": m.get("predicted_value"),
            "recommendation": m.get("recommendation"),
            "line": m.get("line"),
            "confidence": m.get("confidence"),
            "probs": m.get("probs"),
            "result": None,
        }
    return sorted(by_pos.values(), key=lambda r: r["pitch_number"])


def _build_game_payload(ls: dict) -> dict:
    # Import here to avoid a circular import between main.py and live.py.
    from backend.api.main import get_game_label

    game_pk = ls["game_pk"]
    last_ts = ls.get("last_pitch_ts")

    cached = _payload_cache.get(game_pk)
    if cached and cached[0] == last_ts:
        payload = dict(cached[1])
        payload["game_label"] = get_game_label(game_pk)
        # Names may have populated after first paint; refresh the cheap fields.
        payload["pitcher_name"] = _player_name(ls.get("pitcher_id"))
        payload["batter_name"] = _player_name(ls.get("batter_id"))
        return payload

    ctx = _context_from(ls)

    p_speed = _predictor.predict_pitch_speed(ctx)
    p_pres  = _predictor.predict_pitch_result(ctx)
    p_abr   = _predictor.predict_at_bat_result(ctx)
    p_abp   = _predictor.predict_at_bat_pitches(ctx)
    preds_all = [p_speed, p_pres, p_abr, p_abp]

    odds_by_market = {o["market"]: o for o in get_odds(game_pk)}
    o_speed = odds_by_market.get("pitch_speed_ou", {})
    o_abp   = odds_by_market.get("ab_pitches_ou", {})

    markets = [
        _ou_market(p_speed, p_speed["predicted_mph"],
                   o_speed.get("line"), o_speed.get("over_price"), o_speed.get("under_price")),
        _argmax_market(p_pres),
        _argmax_market(p_abr),
        _ou_market(p_abp, p_abp["predicted_count"],
                   o_abp.get("line"), o_abp.get("over_price"), o_abp.get("under_price")),
    ]
    markets.sort(key=_market_sort_key)

    edges = [m["edge"] for m in markets if m["edge"] is not None]
    top_edge = max(edges) if edges else 0.0
    has_edge = top_edge > 0.05

    # Background audit write (best-effort, non-blocking). Only on state change.
    asyncio.create_task(_persist_async(game_pk, preds_all))

    # Prefer the in-memory current-PA pitches the poller already derived; only
    # hit Supabase when the store has nothing for this game (graceful fallback).
    current_pa_pitches = get_store().get_pa_pitches(game_pk)
    if current_pa_pitches is None:
        try:
            current_pa_pitches = _load_current_pa_pitches(game_pk)
        except Exception as exc:
            print(f"[live] current_pa_pitches failed game={game_pk}: {exc}")
            current_pa_pitches = []

    payload = {
        "game_pk": game_pk,
        "game_label": get_game_label(game_pk),
        "pitcher_name": _player_name(ls.get("pitcher_id")),
        "batter_name": _player_name(ls.get("batter_id")),
        "situation": _situation(ls),
        "current_pa_pitches": current_pa_pitches,
        "pa_predictions": _pa_predictions(game_pk, ls, markets),
        "markets": markets,
        "has_edge": has_edge,
        "top_edge": top_edge,
        "model_version": _predictor.model_version,
    }
    _payload_cache[game_pk] = (last_ts, payload)
    return payload


async def _persist_async(game_pk: int, preds: list[dict]) -> None:
    try:
        at_bat_index, pitch_number = await asyncio.to_thread(current_pa_position, game_pk)
        await asyncio.to_thread(insert_predictions, game_pk, at_bat_index, pitch_number, preds)
    except Exception as exc:
        print(f"[live] persist failed game_pk={game_pk}: {exc}")


def _load_current_pa_pitches(game_pk: int) -> list[dict]:
    """Pitches in the current (latest) at-bat for this game, oldest first.

    Single Supabase round-trip: fetch the most-recent rows ordered by
    (at_bat_index desc, pitch_number desc), then keep only the top
    at_bat_index group and reverse to oldest-first. Limit 20 is well
    above any realistic single-PA pitch count.
    """
    rows = (
        get_client().table("pitches")
        .select("at_bat_index,pitch_number,pitch_type,start_speed,zone,description,result_category,balls,strikes")
        .eq("game_pk", game_pk)
        .order("at_bat_index", desc=True)
        .order("pitch_number", desc=True)
        .limit(20)
        .execute().data
        or []
    )
    if not rows:
        return []
    top_abi = rows[0].get("at_bat_index")
    current = [r for r in rows if r.get("at_bat_index") == top_abi]
    current.sort(key=lambda r: r.get("pitch_number") or 0)
    for r in current:
        r.pop("at_bat_index", None)
    return current


def _load_all_live() -> list[dict]:
    return (
        get_client().table("live_state")
        .select("*").execute().data
        or []
    )


def _load_one_live(game_pk: int) -> dict | None:
    rows = (
        get_client().table("live_state")
        .select("*").eq("game_pk", game_pk).limit(1).execute().data
    )
    return rows[0] if rows else None


async def _states_for_live() -> list[dict]:
    """In-memory states if the poller has populated the store; otherwise fall
    back to reading live_state from Supabase (e.g. right after a restart)."""
    states = get_store().all_states()
    if states:
        return states
    return await asyncio.to_thread(_load_all_live)


def _snapshot_payloads() -> list[dict]:
    states = get_store().all_states()
    payloads = [_build_game_payload(ls) for ls in states if ls.get("game_pk") is not None]
    payloads.sort(key=lambda p: -p["top_edge"])
    return payloads


def _sse(event: str, data) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


@router.get("/live")
async def get_live() -> list[dict]:
    states = await _states_for_live()
    payloads = [_build_game_payload(ls) for ls in states if ls.get("game_pk") is not None]
    payloads.sort(key=lambda p: -p["top_edge"])
    return payloads


@router.get("/live/stream")
async def live_stream(request: Request) -> StreamingResponse:
    """Server-Sent Events feed of live games.

    Emits one `snapshot` event on connect (full list, same shape as GET /live),
    then a `game` event per game the instant the poller derives a new pitch —
    eliminating the frontend's poll-interval delay. Every 15s with no activity
    it re-emits a `snapshot`, which doubles as a keepalive and as recovery for
    any client that missed a push. The frontend falls back to polling /live if
    the stream errors, so existing behavior is preserved when SSE is unavailable.
    """
    store = get_store()
    queue = store.subscribe()

    async def gen():
        try:
            yield _sse("snapshot", _snapshot_payloads())
            while True:
                if await request.is_disconnected():
                    break
                try:
                    game_pk = await asyncio.wait_for(queue.get(), timeout=15.0)
                except asyncio.TimeoutError:
                    yield _sse("snapshot", _snapshot_payloads())
                    continue
                ls = store.get_state(game_pk)
                if ls is None:
                    continue
                try:
                    payload = _build_game_payload(ls)
                except Exception as exc:
                    print(f"[live] stream payload failed game={game_pk}: {exc}")
                    continue
                yield _sse("game", payload)
        finally:
            store.unsubscribe(queue)

    headers = {
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",  # don't let nginx buffer the stream
    }
    return StreamingResponse(gen(), media_type="text/event-stream", headers=headers)


@router.get("/live/{game_pk}")
async def get_live_game(game_pk: int) -> dict:
    ls = get_store().get_state(game_pk)
    if ls is None:
        ls = await asyncio.to_thread(_load_one_live, game_pk)
    if not ls:
        raise HTTPException(404, detail=f"no live_state row for game_pk={game_pk}")
    return _build_game_payload(ls)


@router.post("/admin/reload-stats")
async def reload_stats() -> dict:
    counts = await asyncio.to_thread(get_cache().force_reload)
    return {"status": "reloaded", **counts}
