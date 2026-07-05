"""build_markets — odds-join shared by /live and /predictions (extracted so
both serve and persist the same recommendation/line/price/probs shape)."""

from __future__ import annotations

from backend.models.market_rows import build_markets


def _preds():
    return [
        {"market": "pitch_speed_ou", "predicted_mph": 94.0, "confidence": 0.6,
         "model_version": "freq_v2", "sample_size": 50},
        {"market": "pitch_result", "probs": {"strike_foul": 0.5, "ball": 0.3, "in_play": 0.2},
         "confidence": 0.5, "model_version": "freq_v2", "sample_size": 50},
        {"market": "ab_result", "probs": {"strikeout": 0.3, "walk": 0.1, "hit": 0.2, "out": 0.4},
         "confidence": 0.4, "model_version": "freq_v2", "sample_size": 30},
        {"market": "ab_pitches_ou", "predicted_count": 4.2, "confidence": 0.55,
         "model_version": "freq_v2", "sample_size": 30},
    ]


def test_ou_market_recommends_over_when_predicted_above_line():
    odds = {"pitch_speed_ou": {"line": 92.5, "over_price": -115, "under_price": -105}}
    markets = build_markets(_preds()[:1], odds)
    m = markets[0]
    assert m["recommendation"] == "over"
    assert m["price"] == -115
    assert m["edge"] is not None


def test_ou_market_no_line_means_no_recommendation():
    markets = build_markets(_preds()[:1], {})
    m = markets[0]
    assert m["recommendation"] is None
    assert m["edge"] is None


def test_argmax_market_recommends_highest_prob_outcome():
    markets = build_markets([_preds()[2]], {})
    m = markets[0]
    assert m["recommendation"] == "out"
    assert m["predicted_value"] == 0.4
    assert m["probs"] == {"strikeout": 0.3, "walk": 0.1, "hit": 0.2, "out": 0.4}


def test_build_markets_sorts_by_edge_descending():
    odds = {
        "pitch_speed_ou": {"line": 92.5, "over_price": 150, "under_price": -200},
        "ab_pitches_ou": {"line": 4.5, "over_price": -110, "under_price": -110},
    }
    markets = build_markets(_preds(), odds)
    edges = [m["edge"] for m in markets if m["edge"] is not None]
    assert edges == sorted(edges, reverse=True)
