"""build_at_bats groups pitches into plate appearances — pure pandas logic,
tested against a constructed DataFrame so it never needs pybaseball/network.
"""

from __future__ import annotations

import pandas as pd

from backend.ingestion.savant_loader import build_at_bats


def _pitch(game_pk, ab_idx, pitch_number, pitcher_id, batter_id, events=None, ts="2026-06-01T18:00:00Z"):
    return {
        "game_pk": game_pk,
        "at_bat_index": ab_idx,
        "pitch_number": pitch_number,
        "pitcher_id": pitcher_id,
        "batter_id": batter_id,
        "pitch_ts": pd.Timestamp(ts),
        "events": events,
    }


def test_build_at_bats_groups_by_game_and_at_bat_index():
    df = pd.DataFrame([
        _pitch(1, 1, 1, 100, 200),
        _pitch(1, 1, 2, 100, 200),
        _pitch(1, 1, 3, 100, 200, events="strikeout"),
        _pitch(1, 2, 1, 100, 201, events="walk"),
    ])
    out = build_at_bats(df)
    assert len(out) == 2
    ab1 = out[out["at_bat_index"] == 1].iloc[0]
    assert ab1["pitch_count"] == 3
    assert ab1["result"] == "strikeout"
    ab2 = out[out["at_bat_index"] == 2].iloc[0]
    assert ab2["pitch_count"] == 1
    assert ab2["result"] == "walk"


def test_build_at_bats_defaults_to_out_when_no_terminal_event():
    df = pd.DataFrame([_pitch(1, 1, 1, 100, 200, events=None)])
    out = build_at_bats(df)
    assert out.iloc[0]["result"] == "out"
    assert out.iloc[0]["result_detail"] is None


def test_build_at_bats_empty_input_returns_empty_dataframe():
    assert build_at_bats(pd.DataFrame()).empty
    assert build_at_bats(None).empty
