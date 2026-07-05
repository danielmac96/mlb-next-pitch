"""Network smoke tests against the real MLB Stats API.

Excluded from the default `pytest` run (see pytest.ini: `addopts = -m "not
network"`) so CI and local unit-test runs never depend on statsapi.mlb.com
being reachable. Run explicitly with:

    pytest -m network tests/smoke

This supersedes scripts/verify_feeds.py as a CI-runnable check; that script
remains for ad-hoc manual debugging (prints full pitch payloads).
"""

from __future__ import annotations

import pytest

from backend.ingestion import mlb_api
from backend.ingestion.mlb_api import get_live_games, get_play_by_play

pytestmark = pytest.mark.network

# A completed historical game_pk, used when no game is currently live so this
# test is meaningful outside of live MLB game windows.
_FALLBACK_GAME_PK = 745431


@pytest.fixture(autouse=True)
def _fresh_httpx_client():
    """mlb_api caches a module-level httpx.AsyncClient bound to the event loop
    it was first created in. pytest-asyncio gives each test its own loop, so
    reusing that client across tests crashes on teardown (Windows
    ProactorEventLoop in particular). Reset it so each test gets a client
    created in, and torn down within, its own loop."""
    mlb_api._client = None
    yield
    mlb_api._client = None


@pytest.mark.asyncio
async def test_get_live_games_returns_a_list():
    games = await get_live_games()
    assert isinstance(games, list)
    for g in games:
        assert "game_pk" in g


@pytest.mark.asyncio
async def test_get_play_by_play_returns_well_shaped_pitches():
    games = await get_live_games()
    game_pk = games[0]["game_pk"] if games else _FALLBACK_GAME_PK
    pitches = await get_play_by_play(game_pk)
    assert isinstance(pitches, list)
    for p in pitches[:20]:
        assert p["game_pk"] == game_pk
        assert p["result_category"] in {"strike_foul", "ball", "in_play", "other"}
