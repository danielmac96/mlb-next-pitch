"""/live and /live/{game_pk} — mounted standalone (not the real app, so the
lifespan poller never starts) with the in-memory store seeded directly and
Supabase/predictor-cache dependencies monkeypatched out.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.live_store import LiveStore
from tests.conftest import FakeSupabaseClient


class _StubStatsCache:
    def get_player_info(self, _player_id):
        return None


def _setup(monkeypatch, stub_predictor_cache, states):
    from backend.api.routes import live as mod

    mod._payload_cache.clear()  # avoid cross-test bleed via the module-level cache

    store = LiveStore()
    for s in states:
        store.update(s["game_pk"], s, [])
    monkeypatch.setattr(mod, "get_store", lambda: store)
    monkeypatch.setattr(mod, "get_client", lambda: FakeSupabaseClient())
    monkeypatch.setattr(mod, "get_cache", lambda: _StubStatsCache())
    monkeypatch.setattr(mod, "current_pa_position", lambda game_pk: (None, None))
    monkeypatch.setattr(mod, "insert_predictions", lambda *a, **k: None)

    app = FastAPI()
    app.include_router(mod.router)
    return TestClient(app), mod


def _state(game_pk, last_pitch_ts="t1"):
    return {
        "game_pk": game_pk, "pitcher_id": 1, "batter_id": 2,
        "balls": 1, "strikes": 1, "outs": 0, "inning": 3, "top_inning": True,
        "pitch_count_pa": 2, "last_pitch_ts": last_pitch_ts,
    }


def test_live_list_sorted_by_top_edge_desc(monkeypatch, stub_predictor_cache):
    client, _ = _setup(monkeypatch, stub_predictor_cache, [_state(1), _state(2)])
    resp = client.get("/live")
    assert resp.status_code == 200
    payloads = resp.json()
    assert len(payloads) == 2
    edges = [p["top_edge"] for p in payloads]
    assert edges == sorted(edges, reverse=True)


def test_live_single_game_404_when_missing(monkeypatch, stub_predictor_cache):
    client, _ = _setup(monkeypatch, stub_predictor_cache, [])
    resp = client.get("/live/999")
    assert resp.status_code == 404


def test_live_single_game_200_with_markets(monkeypatch, stub_predictor_cache):
    client, _ = _setup(monkeypatch, stub_predictor_cache, [_state(1)])
    resp = client.get("/live/1")
    assert resp.status_code == 200
    body = resp.json()
    assert body["game_pk"] == 1
    assert len(body["markets"]) == 4


def test_live_payload_cache_skips_rebuild_when_last_pitch_ts_unchanged(monkeypatch, stub_predictor_cache):
    client, mod = _setup(monkeypatch, stub_predictor_cache, [_state(1, last_pitch_ts="t1")])
    first = client.get("/live/1").json()
    assert 1 in mod._payload_cache
    second = client.get("/live/1").json()
    assert first["markets"] == second["markets"]


def test_live_returns_404_for_a_game_pk_with_no_live_state(monkeypatch, stub_predictor_cache):
    # unlike /predictions/{game_pk}, /live/{game_pk} has no gt=0 path
    # constraint — game_pk=0 just isn't in the store, so it 404s like any
    # other unknown game_pk.
    client, _ = _setup(monkeypatch, stub_predictor_cache, [])
    resp = client.get("/live/0")
    assert resp.status_code == 404
