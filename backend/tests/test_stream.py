import json
from types import SimpleNamespace

from fastapi.testclient import TestClient

import app.main as main
import app.reasoning as r
from app import sandbox
from app.reasoning import Assessment, Concern, RequestType

client = TestClient(main.app)
SCAM = "Urgent: transfer Rs 50,000 today and keep this between us."
HEADERS = "Authentication-Results: mx; spf=pass; dkim=pass; dmarc=pass\nFrom: bigbasket <alert@info.bigbasket.com>\nTo: recipient@example.com\n"


def events(res):
    return [json.loads(line) for line in res.text.splitlines() if line.strip()]


def stages(res):
    return [e["stage"] for e in events(res)]


def with_fake_model(monkeypatch):
    monkeypatch.setenv("TRUSTGUARD_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    monkeypatch.setattr(r, "get_client", lambda: SimpleNamespace())
    fake = Assessment(claimed_identity=None, request_type=RequestType.payment, tactics=[], inconsistencies=[],
                      innocent_explanations=[], unknowns=[], concern=Concern.high, summary="Scam-like.")
    monkeypatch.setattr(r, "_ask_model", lambda client, text: (fake, ""))


def test_stages_arrive_in_the_real_order_when_a_model_reads_the_text(monkeypatch):
    with_fake_model(monkeypatch)
    res = client.post("/analyze-text/stream", json={"text": SCAM})
    assert res.headers["content-type"].startswith("application/x-ndjson") and res.headers["cache-control"] == "no-store"
    assert stages(res) == ["started", "reading", "verifying", "done"]
    assert events(res)[-1]["result"]["reasoning"]["status"] == "used"


def test_stages_that_do_not_apply_are_never_sent(monkeypatch):
    res = client.post("/analyze-text/stream", json={"text": SCAM})  # no model available in the test environment
    assert stages(res) == ["started", "verifying", "done"]  # no "reading", no "container"


def test_headers_read_in_a_container_add_that_stage_and_no_model_means_no_reading(monkeypatch):
    monkeypatch.setattr(sandbox, "mode", lambda: "container")
    monkeypatch.setattr(sandbox, "parse_headers", lambda text, session=None: sandbox.clean_header_info(
        {"from_email": "alert@info.bigbasket.com", "spf": "pass", "dkim": "pass", "dmarc": "pass"}))
    res = client.post("/analyze-text/stream", json={"headers": HEADERS})
    assert stages(res) == ["started", "container", "verifying", "done"]
    done = events(res)[-1]["result"]
    assert done["isolation"] == "container" and done["header_summary"]["from_email"] == "alert@info.bigbasket.com"
    assert "recipient@example.com" not in res.text  # the recipient's address never leaves the server


def test_all_four_stages_when_there_are_headers_and_a_model(monkeypatch):
    with_fake_model(monkeypatch)
    monkeypatch.setattr(sandbox, "mode", lambda: "container")
    monkeypatch.setattr(sandbox, "parse_headers", lambda text, session=None: sandbox.clean_header_info({"from_email": "a@b.com"}))
    assert stages(client.post("/analyze-text/stream", json={"text": SCAM, "headers": HEADERS})) == [
        "started", "container", "reading", "verifying", "done"]


def test_the_streamed_result_matches_the_normal_endpoint():
    body = {"text": SCAM}
    streamed = events(client.post("/analyze-text/stream", json=body))[-1]["result"]
    normal = client.post("/analyze-text", json=body).json()
    assert streamed == normal


def test_bad_requests_are_ordinary_http_errors_not_streams(monkeypatch):
    assert client.post("/analyze-text/stream", json={"text": "  "}).status_code == 422
    monkeypatch.setenv("TRUSTGUARD_SANDBOX", "docker")
    monkeypatch.setattr(sandbox, "docker_ready", lambda force=False: False)
    assert client.post("/analyze-text/stream", json={"headers": HEADERS}).status_code == 503


def test_a_failure_mid_stream_is_reported_generically_and_leaks_nothing(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("secret internal path C:/Users/someone/private.txt")

    monkeypatch.setattr(main, "analyze_with_reasoning", boom)
    res = client.post("/analyze-text/stream", json={"text": SCAM})
    assert stages(res) == ["started", "error"]
    assert events(res)[-1]["detail"] == "The check failed." and "secret" not in res.text and "private.txt" not in res.text
