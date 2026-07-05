"""GET /picks/today and GET /record — both read the curated `picks` table
(populated by the prediction pipeline elsewhere), not live state computed
on the fly. Mirrors the shapes frontend/picks-data.js documents as the
eventual real-data contract."""

from __future__ import annotations

from datetime import date

from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.conftest import FakeSupabaseClient


def _client_for(router) -> TestClient:
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_picks_today_empty_when_none_published(monkeypatch):
    from backend.api.routes import picks as mod

    monkeypatch.setattr(mod, "get_client", lambda: FakeSupabaseClient({"picks": []}))
    resp = _client_for(mod.router).get("/picks/today")
    assert resp.status_code == 200
    assert resp.json() == []


def test_picks_today_filters_by_date(monkeypatch):
    from backend.api.routes import picks as mod

    today = date.today().isoformat()
    fake = FakeSupabaseClient({"picks": [
        {"pick_date": today, "market": "ab_result", "recommendation": "strikeout",
         "label": "Today Pick", "edge": 0.08, "units": 1, "status": "pending",
         "payload": {"game": {"away": "NYY", "home": "BOS"}, "bullets": ["x"]}},
        {"pick_date": "2020-01-01", "market": "ab_result", "recommendation": "hit",
         "label": "Old Pick", "edge": 0.05, "units": 1, "status": "pending", "payload": {}},
    ]})
    monkeypatch.setattr(mod, "get_client", lambda: fake)

    resp = _client_for(mod.router).get("/picks/today")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["pick"] == "Today Pick"
    assert body[0]["game"] == {"away": "NYY", "home": "BOS"}


def test_record_is_honestly_empty_with_no_graded_picks(monkeypatch):
    from backend.api.routes import picks as mod

    monkeypatch.setattr(mod, "get_client", lambda: FakeSupabaseClient({"picks": []}))
    resp = _client_for(mod.router).get("/record")
    assert resp.status_code == 200
    body = resp.json()
    assert body["overall"] == {"wins": 0, "losses": 0, "pushes": 0, "units": 0.0,
                                "roi": 0.0, "picks": 0}
    assert body["byMarket"] == []
    assert body["recent"] == []


def test_record_aggregates_graded_picks_and_skips_pending(monkeypatch):
    from backend.api.routes import picks as mod

    fake = FakeSupabaseClient({"picks": [
        {"pick_date": "2026-07-01", "market": "ab_result", "recommendation": "strikeout",
         "label": "X — Strikeout", "price": -120, "units": 1, "status": "win",
         "profit_units": 0.833, "graded_at": "2026-07-01T20:00:00Z",
         "payload": {"game": {"matchup": "NYY @ BOS"}}},
        {"pick_date": "2026-07-01", "market": "ab_result", "recommendation": "hit",
         "label": "Y — Hit", "price": 140, "units": 1, "status": "loss",
         "profit_units": -1.0, "graded_at": "2026-07-01T20:05:00Z",
         "payload": {"game": {"matchup": "LAD @ SF"}}},
        {"pick_date": "2026-07-01", "market": "pitch_speed_ou", "recommendation": "over",
         "label": "Over 95.5", "price": -110, "units": 1, "status": "win",
         "profit_units": 0.909, "graded_at": "2026-07-01T20:10:00Z", "payload": {}},
        # a pending pick must be excluded from the record
        {"pick_date": "2026-07-02", "market": "ab_result", "recommendation": "walk",
         "status": "pending", "units": 1, "payload": {}},
    ]})
    monkeypatch.setattr(mod, "get_client", lambda: fake)

    resp = _client_for(mod.router).get("/record")
    assert resp.status_code == 200
    body = resp.json()
    assert body["overall"]["picks"] == 3
    assert body["overall"]["wins"] == 2 and body["overall"]["losses"] == 1
    assert body["overall"]["units"] == round(0.833 - 1.0 + 0.909, 2)
    markets = {m["market"]: m for m in body["byMarket"]}
    assert markets["ab_result"]["picks"] == 2
    assert markets["pitch_speed_ou"]["wins"] == 1
    assert len(body["recent"]) == 3
