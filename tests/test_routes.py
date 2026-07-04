"""Tests for the picks/record aggregation + settle against a fake Supabase."""

from __future__ import annotations

import asyncio
from datetime import date

from backend.jobs.settle_predictions import settle_pending


def test_record_empty_is_honest(fake_client):
    from backend.api.routes.picks import record
    out = asyncio.run(record())
    assert out["overall"] == {"wins": 0, "losses": 0, "pushes": 0, "units": 0.0,
                              "roi": 0.0, "picks": 0}
    assert out["recent"] == []
    assert out["byMarket"] == []


def test_record_aggregates_graded_picks(fake_client):
    fake_client.seed("picks", [
        {"pick_date": "2026-07-01", "market": "ab_result", "recommendation": "strikeout",
         "label": "X — Strikeout", "price": -120, "units": 1, "status": "win",
         "profit_units": 0.833, "graded_at": "2026-07-01T20:00:00Z", "payload": {"game": {"matchup": "NYY @ BOS"}}},
        {"pick_date": "2026-07-01", "market": "ab_result", "recommendation": "hit",
         "label": "Y — Hit", "price": 140, "units": 1, "status": "loss",
         "profit_units": -1.0, "graded_at": "2026-07-01T20:05:00Z", "payload": {"game": {"matchup": "LAD @ SF"}}},
        {"pick_date": "2026-07-01", "market": "pitch_speed_ou", "recommendation": "over",
         "label": "Over 95.5", "price": -110, "units": 1, "status": "win",
         "profit_units": 0.909, "graded_at": "2026-07-01T20:10:00Z", "payload": {}},
        # a pending pick must be excluded from the record
        {"pick_date": "2026-07-02", "market": "ab_result", "recommendation": "walk",
         "status": "pending", "units": 1, "payload": {}},
    ])
    from backend.api.routes.picks import record
    out = asyncio.run(record())
    assert out["overall"]["picks"] == 3
    assert out["overall"]["wins"] == 2 and out["overall"]["losses"] == 1
    assert out["overall"]["units"] == round(0.833 - 1.0 + 0.909, 2)
    markets = {m["market"]: m for m in out["byMarket"]}
    assert markets["ab_result"]["picks"] == 2
    assert markets["pitch_speed_ou"]["wins"] == 1
    assert len(out["recent"]) == 3


def test_picks_today_filters_by_date(fake_client):
    today = date.today().isoformat()
    fake_client.seed("picks", [
        {"pick_date": today, "market": "ab_result", "recommendation": "strikeout",
         "label": "Today Pick", "edge": 0.08, "units": 1, "status": "pending",
         "payload": {"game": {"away": "NYY", "home": "BOS"}, "bullets": ["x"]}},
        {"pick_date": "2020-01-01", "market": "ab_result", "recommendation": "hit",
         "label": "Old Pick", "edge": 0.05, "units": 1, "status": "pending", "payload": {}},
    ])
    from backend.api.routes.picks import picks_today
    out = asyncio.run(picks_today())
    assert len(out) == 1 and out[0]["pick"] == "Today Pick"
    assert out[0]["game"] == {"away": "NYY", "home": "BOS"}


def test_settle_grades_pending_predictions(fake_client):
    fake_client.seed("pitches", [
        {"game_pk": 1, "at_bat_index": 0, "pitch_number": 1, "start_speed": 96.0, "result_category": "ball"},
        {"game_pk": 1, "at_bat_index": 0, "pitch_number": 2, "start_speed": 88.5, "result_category": "strike_foul"},
    ])
    fake_client.seed("at_bats", [
        {"game_pk": 1, "at_bat_index": 0, "result": "strikeout", "pitch_count": 2},
    ])
    fake_client.seed("games", [])  # no game row -> treated as not live -> resolvable
    fake_client.seed("live_state", [{"game_pk": 1, "status": "final"}])
    fake_client.seed("predictions", [
        {"game_pk": 1, "at_bat_index": 0, "pitch_number": 1, "market": "pitch_speed_ou",
         "recommendation": "under", "line": 92.0, "price": -110, "result": None},
        {"game_pk": 1, "at_bat_index": 0, "pitch_number": None, "market": "ab_result",
         "recommendation": "strikeout", "price": -120, "result": None},
    ])
    n = settle_pending()
    assert n == 2
    graded = {r["market"]: r for r in fake_client._store["predictions"]}
    # next pitch after (0,1) is (0,2) at 88.5 < 92.0 -> under wins
    assert graded["pitch_speed_ou"]["result"] == "win"
    assert graded["ab_result"]["result"] == "win"
    assert all(r["graded_at"] is not None for r in fake_client._store["predictions"])
