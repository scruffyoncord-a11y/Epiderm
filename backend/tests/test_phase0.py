from fastapi.testclient import TestClient

from app.main import app, load_scenarios
from app.models import Band, Signal

client = TestClient(app)


def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_signal_contract_round_trip():
    body = client.get("/demo-signal").json()
    sig = Signal.model_validate(body)
    assert sig.direction.value == "suspicious"
    assert 0 <= sig.strength <= 1 and 0 <= sig.confidence <= 1


def test_all_scenarios_load_and_have_expectations():
    scenarios = load_scenarios()
    assert set(scenarios) == {"scam_bundle", "legit_traveller", "clean_request", "legit_urgent"}
    expected = {s.id: s.expected.band for s in scenarios.values()}
    assert expected == {
        "scam_bundle": Band.verify,
        "legit_traveller": Band.step_up,
        "clean_request": Band.allow,
        "legit_urgent": Band.step_up,
    }


def test_scenario_endpoints():
    assert len(client.get("/scenarios").json()) == 4
    assert client.get("/scenarios/scam_bundle").status_code == 200
    assert client.get("/scenarios/nope").status_code == 404


def test_placeholder_matches_expected_band_and_is_flagged():
    for sid, sc in load_scenarios().items():
        body = client.post(f"/analyze/{sid}").json()
        assert body["is_placeholder"] is True
        assert body["band"] == sc.expected.band.value
        assert 0 <= body["trust_low"] <= body["trust_score"] <= body["trust_high"] <= 100
