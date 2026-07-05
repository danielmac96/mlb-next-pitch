"""_flatten_pitch is the pure transform from a raw MLB Stats API playByPlay
event to our pitches-table shape. Tested directly against a recorded-shape
fixture dict so this never needs a live network call.
"""

from __future__ import annotations

from backend.ingestion.mlb_api import _flatten_pitch

_PLAY = {
    "about": {"atBatIndex": 5, "inning": 3, "isTopInning": True},
    "matchup": {"pitcher": {"id": 111}, "batter": {"id": 222}},
}

_PITCH_EVENT = {
    "type": "pitch",
    "pitchNumber": 2,
    "startTime": "2026-06-22T20:00:00.000Z",
    "details": {
        "call": {"code": "C"},
        "description": "Called Strike",
        "type": {"code": "FF"},
    },
    "pitchData": {"startSpeed": 95.4, "zone": 5},
    "count": {"balls": 1, "strikes": 1, "outs": 0},
}


def test_flatten_pitch_maps_call_code_to_description_and_category():
    row = _flatten_pitch(game_pk=12345, play=_PLAY, event=_PITCH_EVENT)
    assert row["game_pk"] == 12345
    assert row["at_bat_index"] == 5
    assert row["pitch_number"] == 2
    assert row["pitcher_id"] == 111
    assert row["batter_id"] == 222
    assert row["description"] == "called_strike"
    assert row["result_category"] == "strike_foul"
    assert row["start_speed"] == 95.4
    assert row["balls"] == 1
    assert row["strikes"] == 1
    assert row["inning"] == 3
    assert row["top_inning"] is True


def test_flatten_pitch_falls_back_to_raw_description_for_unknown_call_code():
    event = dict(_PITCH_EVENT, details={
        "call": {"code": "ZZ_UNKNOWN"},
        "description": "Some New Call Type",
        "type": {"code": "FF"},
    })
    row = _flatten_pitch(game_pk=1, play=_PLAY, event=event)
    assert row["description"] == "some_new_call_type"
    # no recognizable substring in the unmapped raw description -> uncategorized
    assert row["result_category"] is None


def test_flatten_pitch_handles_missing_call_code_and_description():
    event = dict(_PITCH_EVENT, details={"call": {}, "description": "", "type": {}})
    row = _flatten_pitch(game_pk=1, play=_PLAY, event=event)
    assert row["description"] is None
    assert row["result_category"] is None
