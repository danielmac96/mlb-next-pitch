"""Unit tests for the prediction/settlement pipeline logic."""

from __future__ import annotations

import pytest

from backend.ingestion.odds_provider import (
    StubOddsProvider, calculate_edge, implied_probability,
)
from backend.ingestion.vocab import ab_result_category, result_category
from backend.jobs.settle_predictions import _grade_row, _next_pitch, _win_profit
from backend.models.market_rows import build_markets


# ── vocab ──────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("desc,cat", [
    ("called_strike", "strike_foul"), ("swinging_strike", "strike_foul"),
    ("foul", "strike_foul"), ("ball", "ball"), ("hit_by_pitch", "ball"),
    ("in_play", "in_play"), (None, None), ("blooper", None),
])
def test_result_category(desc, cat):
    assert result_category(desc) == cat


@pytest.mark.parametrize("event,cat", [
    ("strikeout", "strikeout"), ("strikeout_double_play", "strikeout"),
    ("walk", "walk"), ("hit_by_pitch", "walk"), ("intent_walk", "walk"),
    ("single", "hit"), ("home_run", "hit"),
    ("field_out", "out"), ("grounded_into_double_play", "out"),
    ("fielders_choice", "out"), (None, None),
])
def test_ab_result_category(event, cat):
    assert ab_result_category(event) == cat


# ── odds math ──────────────────────────────────────────────────────────────
def test_implied_probability():
    assert implied_probability(-110) == pytest.approx(0.5238, abs=1e-3)
    assert implied_probability(+150) == pytest.approx(0.40, abs=1e-3)
    assert implied_probability(None) is None


def test_calculate_edge():
    # model 60% vs -110 (52.4% implied) -> ~+7.6% edge
    assert calculate_edge(0.60, -110) == pytest.approx(0.0762, abs=1e-3)
    assert calculate_edge(None, -110) is None
    assert calculate_edge(0.6, None) is None


def test_stub_provider_shape():
    rows = StubOddsProvider().get_odds(12345)
    markets = {r["market"] for r in rows}
    assert markets == {"pitch_speed_ou", "ab_pitches_ou"}
    for r in rows:
        assert r["source"] == "stub"
        assert r["over_price"] is not None and r["under_price"] is not None


# ── market rows ────────────────────────────────────────────────────────────
def test_build_markets_ou_and_categorical():
    preds = [
        {"market": "pitch_speed_ou", "predicted_mph": 94.0, "confidence": 0.58, "model_version": "v1"},
        {"market": "pitch_result", "probs": {"strike_foul": 0.5, "ball": 0.3, "in_play": 0.2}, "confidence": 0.5, "model_version": "v1"},
        {"market": "ab_result", "probs": {"strikeout": 0.3, "walk": 0.1, "hit": 0.25, "out": 0.35}, "confidence": 0.35, "model_version": "v1"},
        {"market": "ab_pitches_ou", "predicted_count": 3.2, "confidence": 0.55, "model_version": "v1"},
    ]
    odds = {
        "pitch_speed_ou": {"line": 92.5, "over_price": -110, "under_price": -110},
        "ab_pitches_ou": {"line": 3.5, "over_price": -115, "under_price": -105},
    }
    rows = {r["market"]: r for r in build_markets(preds, odds)}
    assert rows["pitch_speed_ou"]["recommendation"] == "over"   # 94.0 > 92.5
    assert rows["pitch_speed_ou"]["edge"] is not None
    assert rows["ab_pitches_ou"]["recommendation"] == "under"   # 3.2 < 3.5
    assert rows["pitch_result"]["recommendation"] == "strike_foul"
    assert rows["ab_result"]["recommendation"] == "out"
    assert rows["ab_result"]["probs"] is not None


def test_build_markets_no_line_leaves_null():
    preds = [{"market": "pitch_speed_ou", "predicted_mph": 94.0, "confidence": 0.6, "model_version": "v1"}]
    rows = build_markets(preds, {})
    assert rows[0]["recommendation"] is None and rows[0]["edge"] is None


# ── settlement grading ─────────────────────────────────────────────────────
PITCHES = [
    {"at_bat_index": 5, "pitch_number": 1, "start_speed": 95.1, "result_category": "ball"},
    {"at_bat_index": 5, "pitch_number": 2, "start_speed": 88.0, "result_category": "strike_foul"},
    {"at_bat_index": 6, "pitch_number": 1, "start_speed": 97.3, "result_category": "in_play"},
]
ABS = {5: {"at_bat_index": 5, "result": "strikeout", "pitch_count": 2},
       6: {"at_bat_index": 6, "result": "hit", "pitch_count": 1}}


def test_next_pitch():
    assert _next_pitch(PITCHES, 5, 1)["pitch_number"] == 2
    assert _next_pitch(PITCHES, 5, 2)["at_bat_index"] == 6      # crosses AB boundary
    assert _next_pitch(PITCHES, 6, 1) is None                   # nothing later


def test_win_profit():
    assert _win_profit(-110) == pytest.approx(0.909, abs=1e-3)
    assert _win_profit(+150) == pytest.approx(1.5, abs=1e-3)
    assert _win_profit(None) == 1.0


def test_grade_pitch_speed_win():
    row = {"market": "pitch_speed_ou", "recommendation": "over", "line": 90.5, "price": -110, "at_bat_index": 5, "pitch_number": 2}
    assert _grade_row(row, PITCHES, ABS, True) == ("win", _win_profit(-110))


def test_grade_ab_result():
    row = {"market": "ab_result", "recommendation": "strikeout", "price": -120, "at_bat_index": 5}
    assert _grade_row(row, PITCHES, ABS, True) == ("win", _win_profit(-120))
    row["recommendation"] = "walk"
    assert _grade_row(row, PITCHES, ABS, True) == ("loss", -1.0)


def test_grade_ab_pitches_push():
    row = {"market": "ab_pitches_ou", "recommendation": "over", "line": 2, "at_bat_index": 5}
    assert _grade_row(row, PITCHES, ABS, True) == ("push", 0.0)


def test_grade_unresolved_while_live_returns_none():
    row = {"market": "pitch_result", "recommendation": "ball", "at_bat_index": 6, "pitch_number": 1}
    assert _grade_row(row, PITCHES, ABS, True) is None
    # ...but voids once the game is final
    assert _grade_row(row, PITCHES, ABS, False) == ("void", 0.0)


def test_grade_no_recommendation_voids():
    row = {"market": "ab_result", "recommendation": None, "at_bat_index": 5}
    assert _grade_row(row, PITCHES, ABS, True) == ("void", 0.0)
