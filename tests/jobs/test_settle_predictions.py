"""_grade_row — pure grading logic, no Supabase. settle_pending's DB plumbing
is exercised indirectly via the FakeSupabaseClient below."""

from __future__ import annotations

from backend.jobs.settle_predictions import _grade_row, _next_pitch, _win_profit, settle_pending
from tests.conftest import FakeSupabaseClient

PITCHES = [
    {"at_bat_index": 5, "pitch_number": 1, "start_speed": 95.1, "result_category": "ball"},
    {"at_bat_index": 5, "pitch_number": 2, "start_speed": 88.0, "result_category": "strike_foul"},
    {"at_bat_index": 6, "pitch_number": 1, "start_speed": 97.3, "result_category": "in_play"},
]
ABS_BY_IDX = {
    5: {"at_bat_index": 5, "result": "strikeout", "pitch_count": 2},
    6: {"at_bat_index": 6, "result": "hit", "pitch_count": 1},
}


def test_no_recommendation_is_always_voided():
    row = {"market": "ab_result", "recommendation": None}
    assert _grade_row(row, PITCHES, ABS_BY_IDX, True) == ("void", 0.0)


def test_next_pitch():
    assert _next_pitch(PITCHES, 5, 1)["pitch_number"] == 2
    assert _next_pitch(PITCHES, 5, 2)["at_bat_index"] == 6  # crosses AB boundary
    assert _next_pitch(PITCHES, 6, 1) is None                # nothing later


def test_win_profit():
    assert _win_profit(-110) == round(100 / 110, 3)
    assert _win_profit(150) == 1.5
    assert _win_profit(None) == 1.0


def test_pitch_speed_ou_win():
    row = {"market": "pitch_speed_ou", "recommendation": "over", "line": 90.5,
           "price": -110, "at_bat_index": 5, "pitch_number": 1}
    # next pitch after (5,1) is (5,2) at 88.0 mph -> under the 90.5 line, so
    # an "over" call loses
    assert _grade_row(row, PITCHES, ABS_BY_IDX, True) == ("loss", -1.0)


def test_ab_result_win_and_loss():
    row = {"market": "ab_result", "recommendation": "strikeout", "price": -120, "at_bat_index": 5}
    assert _grade_row(row, PITCHES, ABS_BY_IDX, True) == ("win", _win_profit(-120))
    row["recommendation"] = "walk"
    assert _grade_row(row, PITCHES, ABS_BY_IDX, True) == ("loss", -1.0)


def test_ab_pitches_ou_push_on_exact_line():
    row = {"market": "ab_pitches_ou", "recommendation": "over", "line": 2, "at_bat_index": 5}
    assert _grade_row(row, PITCHES, ABS_BY_IDX, True) == ("push", 0.0)


def test_unresolved_while_live_returns_none_but_voids_once_final():
    row = {"market": "pitch_result", "recommendation": "ball", "at_bat_index": 6, "pitch_number": 1}
    assert _grade_row(row, PITCHES, ABS_BY_IDX, True) is None
    assert _grade_row(row, PITCHES, ABS_BY_IDX, False) == ("void", 0.0)


def test_settle_pending_grades_and_writes_back():
    fake = FakeSupabaseClient({
        "predictions": [
            {"id": 1, "game_pk": 1, "at_bat_index": 0, "pitch_number": None,
             "market": "ab_result", "recommendation": "strikeout", "line": None,
             "price": None, "units": 1, "result": None},
        ],
        "at_bats": [{"game_pk": 1, "at_bat_index": 0, "result": "strikeout", "pitch_count": 3}],
        "pitches": [],
        "live_state": [{"game_pk": 1, "status": "final"}],
    })
    import backend.jobs.settle_predictions as mod
    orig = mod.get_client
    mod.get_client = lambda: fake
    try:
        graded = settle_pending()
    finally:
        mod.get_client = orig
    assert graded == 1
    row = fake.rows_for("predictions")[0]
    assert row["result"] == "win"
    assert row["profit_units"] == 1.0
    assert row["graded_at"] is not None
