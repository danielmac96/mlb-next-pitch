"""OddsProvider abstraction — defaults to the stub, swappable via config."""

from __future__ import annotations

from backend.ingestion import odds_provider as mod


def teardown_function(_fn):
    mod._provider = None


def test_get_provider_defaults_to_stub():
    mod._provider = None
    provider = mod.get_provider()
    assert isinstance(provider, mod.StubOddsProvider)


def test_get_odds_delegates_to_provider():
    mod._provider = None
    rows = mod.get_odds(123)
    # the stub only prices the two O/U micro-markets (no free public source
    # for the categorical markets) — see StubOddsProvider's docstring.
    assert {r["market"] for r in rows} == {"pitch_speed_ou", "ab_pitches_ou"}
    assert all(r["source"] == "stub" for r in rows)


def test_unknown_provider_name_falls_back_to_stub(monkeypatch):
    monkeypatch.setenv("ODDS_PROVIDER", "draftkings_live")
    mod._provider = None
    provider = mod.get_provider()
    assert isinstance(provider, mod.StubOddsProvider)


def test_provider_instance_is_cached():
    mod._provider = None
    first = mod.get_provider()
    second = mod.get_provider()
    assert first is second


def test_implied_probability():
    assert round(mod.implied_probability(-110), 4) == 0.5238
    assert round(mod.implied_probability(150), 4) == 0.40
    assert mod.implied_probability(None) is None


def test_calculate_edge_positive_value_bet():
    assert mod.calculate_edge(0.6, -115) > 0


def test_calculate_edge_handles_missing_inputs():
    assert mod.calculate_edge(None, -110) is None
    assert mod.calculate_edge(0.6, None) is None


def test_odds_stub_module_is_a_backward_compatible_alias():
    from backend.ingestion import odds_stub

    rows = odds_stub.get_odds(1)
    assert rows == mod.StubOddsProvider().get_odds(1)
    assert odds_stub.calculate_edge(0.6, -115) == mod.calculate_edge(0.6, -115)
