"""End-to-end offline test of the ingest -> predict -> grade chain.

Runs a realistic MLB Stats API playByPlay fixture through the ACTUAL
flatteners (no network), then the predictor, market-row builder, and the
settlement grader — proving the full data contract holds on realistic data.
Unlike the per-module unit tests elsewhere in tests/, this crosses
ingestion/models/jobs on purpose, so it lives on its own.
"""

from __future__ import annotations

import json
from pathlib import Path

from backend.ingestion.mlb_api import _flatten_at_bat_result, _flatten_pitch
from backend.jobs.settle_predictions import _grade_row
from backend.models.market_rows import build_markets
from backend.models.predictor import PitchPredictor

FIXTURE = Path(__file__).parent.parent / "fixtures" / "playbyplay_sample.json"
GAME_PK = 777001


def _ingest():
    data = json.loads(FIXTURE.read_text())
    pitches, at_bats = [], []
    for play in data["allPlays"]:
        for ev in play["playEvents"]:
            if ev.get("type") == "pitch":
                pitches.append(_flatten_pitch(GAME_PK, play, ev))
        ab = _flatten_at_bat_result(GAME_PK, play)
        if ab is not None:
            at_bats.append(ab)
    return pitches, at_bats


def test_flatten_pitches():
    pitches, _ = _ingest()
    assert len(pitches) == 6                      # 3 + 2 + 1 pitch events
    p0 = pitches[0]
    assert p0["game_pk"] == GAME_PK
    assert p0["at_bat_index"] == 0 and p0["pitch_number"] == 1
    assert p0["pitcher_id"] == 543037 and p0["batter_id"] == 646240
    assert p0["pitch_type"] == "FF" and p0["start_speed"] == 97.4
    assert p0["result_category"] == "strike_foul"   # called strike
    assert p0["inning"] == 1 and p0["top_inning"] is True
    # a thrown ball maps to the ball bucket
    assert pitches[1]["result_category"] == "ball"
    # a foul maps to strike_foul
    assert pitches[4]["result_category"] == "strike_foul"


def test_flatten_at_bats():
    _, at_bats = _ingest()
    # only the two completed at-bats (the in-progress 3rd play has no eventType)
    assert len(at_bats) == 2
    k, bb = at_bats[0], at_bats[1]
    assert k["at_bat_index"] == 0 and k["result"] == "strikeout" and k["pitch_count"] == 3
    assert bb["at_bat_index"] == 1 and bb["result"] == "walk" and bb["pitch_count"] == 2


def test_predict_from_ingested_state(stub_predictor_cache):
    pitches, _ = _ingest()
    # emulate the poller deriving state from the latest at-bat (the live PA)
    latest = max(p["at_bat_index"] for p in pitches)
    pa = sorted((p for p in pitches if p["at_bat_index"] == latest),
                key=lambda p: p["pitch_number"])
    last = pa[-1]
    ctx = {
        "game_pk": GAME_PK, "pitcher_id": last["pitcher_id"],
        "batter_id": last["batter_id"], "balls": last["balls"],
        "strikes": last["strikes"], "pitch_count_pa": len(pa), "inning": last["inning"],
    }
    predictor = PitchPredictor()
    preds = [
        predictor.predict_pitch_speed(ctx),
        predictor.predict_pitch_result(ctx),
        predictor.predict_at_bat_result(ctx),
        predictor.predict_at_bat_pitches(ctx),
    ]
    # all four markets return sane, complete shapes
    by = {p["market"]: p for p in preds}
    assert set(by) == {"pitch_speed_ou", "pitch_result", "ab_result", "ab_pitches_ou"}
    assert 60 < by["pitch_speed_ou"]["predicted_mph"] < 105
    for cat in ("pitch_result", "ab_result"):
        probs = by[cat]["probs"]
        assert abs(sum(probs.values()) - 1.0) < 1e-6

    # join to stub odds and confirm a persistable, pick-shaped row comes out
    from backend.ingestion.odds_provider import get_odds
    odds = {o["market"]: o for o in get_odds(GAME_PK)}
    rows = {r["market"]: r for r in build_markets(preds, odds)}
    assert rows["pitch_speed_ou"]["recommendation"] in ("over", "under")
    assert rows["pitch_speed_ou"]["edge"] is not None


def test_grade_ingested_at_bats():
    pitches, at_bats = _ingest()
    abs_by_idx = {a["at_bat_index"]: a for a in at_bats}
    # a strikeout pick on AB 0 should grade as a win against the real outcome
    row = {"market": "ab_result", "recommendation": "strikeout", "price": -120, "at_bat_index": 0}
    assert _grade_row(row, pitches, abs_by_idx, False) == ("win", 0.833)
    # a pitch-speed under on the first pitch resolves against pitch 2 (88.1)
    row = {"market": "pitch_speed_ou", "recommendation": "under", "line": 92.5,
           "price": -110, "at_bat_index": 0, "pitch_number": 1}
    assert _grade_row(row, pitches, abs_by_idx, False)[0] == "win"
