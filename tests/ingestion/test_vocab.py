"""result_category bucketing — the single source both mlb_api.py (live) and
savant_loader.py (historical) import from, so a pitch can't land in different
buckets depending on which path ingested it.
"""

from __future__ import annotations

import pytest

from backend.ingestion.vocab import (
    CALL_CODE_TO_DESCRIPTION,
    ab_result_category,
    result_category,
)


@pytest.mark.parametrize("description,expected", [
    ("called_strike", "strike_foul"),
    ("swinging_strike", "strike_foul"),
    ("swinging_strike_blocked", "strike_foul"),
    ("foul", "strike_foul"),
    ("foul_tip", "strike_foul"),
    ("foul_bunt", "strike_foul"),
    ("bunt_foul_tip", "strike_foul"),
    ("ball", "ball"),
    ("blocked_ball", "ball"),
    ("automatic_ball", "ball"),
    ("intent_ball", "ball"),
    ("pitchout", "ball"),
    ("hit_by_pitch", "ball"),
    ("in_play", "in_play"),
    ("in_play_score", "in_play"),
    (None, None),
    # unmapped raw descriptions with no recognizable substring bucket to None
    ("missed_bunt", None),
    ("something_unmapped", None),
])
def test_result_category(description, expected):
    assert result_category(description) == expected


def test_call_code_to_description_covers_common_codes():
    assert CALL_CODE_TO_DESCRIPTION["B"] == "ball"
    assert CALL_CODE_TO_DESCRIPTION["X"] == "in_play"
    assert CALL_CODE_TO_DESCRIPTION["C"] == "called_strike"


def test_every_call_code_description_resolves_to_a_known_category():
    for code, description in CALL_CODE_TO_DESCRIPTION.items():
        assert result_category(description) in {"strike_foul", "ball", "in_play"}, (
            f"call code {code!r} -> {description!r} produced an unexpected category"
        )


@pytest.mark.parametrize("event_type,expected", [
    ("strikeout", "strikeout"),
    ("strikeout_double_play", "strikeout"),
    ("walk", "walk"),
    ("intent_walk", "walk"),
    ("hit_by_pitch", "walk"),
    ("single", "hit"),
    ("double", "hit"),
    ("triple", "hit"),
    ("home_run", "hit"),
    ("field_out", "out"),
    ("grounded_into_double_play", "out"),
    (None, None),
])
def test_ab_result_category(event_type, expected):
    assert ab_result_category(event_type) == expected
