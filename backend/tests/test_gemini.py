import json
from types import SimpleNamespace

import pytest
import requests
from fastapi.testclient import TestClient

import app.reasoning as r
from app.main import app, load_env_file
from app.models import Band

KEY = "test-key-not-a-real-secret-123"
SCAM = ("Hi, this is Rahul from the CFO office. I'm in a meeting and can't take calls. "
        "Urgent: transfer Rs 2,40,000 today and don't tell anyone.")


def gemini_reply(assessment: dict, finish="STOP", block=None):
    body = {"candidates": [{"finishReason": finish,
                            "content": {"parts": [{"text": json.dumps(assessment)}]}}]}
    if block:
        body["promptFeedback"] = {"blockReason": block}
    return SimpleNamespace(status_code=200, json=lambda: body, raise_for_status=lambda: None)


def good(**over):
    base = {"claimed_identity": "Rahul, CFO", "request_type": "payment",
            "tactics": [{"kind": "secrecy", "quote": "don't tell anyone", "why": "asks for secrecy"}],
            "inconsistencies": ["An invented inconsistency"], "innocent_explanations": [], "unknowns": ["Whether Rahul sent it"],
            "concern": "high", "summary": "Looks like a payment pressure scam."}
    base.update(over)
    return base


@pytest.fixture
def with_key(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", KEY)
    monkeypatch.setenv("TRUSTGUARD_PROVIDER", "auto")


def test_gemini_is_chosen_when_a_key_is_set_and_reported_as_not_local(with_key):
    cfg = TestClient(app).get("/config").json()
    assert {k: cfg[k] for k in ("reasoning_enabled", "provider", "model", "local")} == {"reasoning_enabled": True, "provider": "gemini", "model": "gemini-2.5-flash", "local": False}
    assert KEY not in json.dumps(cfg)


def test_request_shape_key_only_in_header_text_delimited_and_untrusted(with_key, monkeypatch):
    seen = {}

    def fake_post(url, json=None, headers=None, timeout=None):
        seen.update(url=url, body=json, headers=headers)
        return gemini_reply(good())

    monkeypatch.setattr(r.requests, "post", fake_post)
    a = r.analyze_with_reasoning(SCAM)
    assert KEY not in seen["url"] and seen["headers"] == {"x-goog-api-key": KEY}
    assert "<user_scenario>" in seen["body"]["contents"][0]["parts"][0]["text"] and SCAM in seen["body"]["contents"][0]["parts"][0]["text"]
    assert "untrusted" in seen["body"]["systemInstruction"]["parts"][0]["text"].lower()
    cfg = seen["body"]["generationConfig"]
    assert cfg["responseMimeType"] == "application/json" and cfg["temperature"] == 0
    assert "$ref" not in json.dumps(cfg["responseJsonSchema"]) and "$defs" not in cfg["responseJsonSchema"]
    assert a.reasoning.status == "used" and a.reasoning.provider == "gemini" and a.reasoning.local is False
    assert KEY not in a.model_dump_json()


def test_gemini_inconsistencies_are_advisory_and_quotes_are_verified(with_key, monkeypatch):
    reply = good(tactics=[{"kind": "secrecy", "quote": "don't tell anyone", "why": "secrecy"},
                          {"kind": "isolation", "quote": "words that are not present", "why": "made up"}])
    monkeypatch.setattr(r.requests, "post", lambda *a, **k: gemini_reply(reply))
    a = r.analyze_with_reasoning(SCAM)
    assert not any(s.id.startswith("text.inconsistency") for s in a.signals)
    assert "text.isolation" not in {s.id for s in a.signals}
    assert a.reasoning.inconsistencies == ["An invented inconsistency"]
    assert a.band == Band.verify


def test_http_error_falls_back_without_leaking_the_key(with_key, monkeypatch):
    def boom(*a, **k):
        raise requests.HTTPError(f"403 Client Error for url with key {KEY}")

    monkeypatch.setattr(r.requests, "post", boom)
    a = r.analyze_with_reasoning(SCAM)
    assert a.reasoning.status == "failed" and a.band == Band.verify
    assert KEY not in a.model_dump_json()  # only the exception type name is reported


def test_blocked_unfinished_and_malformed_replies_fall_back(with_key, monkeypatch):
    for reply in (gemini_reply({}, block="SAFETY"), gemini_reply(good(), finish="MAX_TOKENS"),
                  SimpleNamespace(status_code=200, json=lambda: {"candidates": [{"content": {"parts": [{"text": "not json"}]}}]},
                                  raise_for_status=lambda: None)):
        monkeypatch.setattr(r.requests, "post", lambda *a, _r=reply, **k: _r)
        a = r.analyze_with_reasoning(SCAM)
        assert a.reasoning.status == "failed" and a.band == Band.verify


def test_env_file_is_loaded_without_overriding_and_never_logged(tmp_path, monkeypatch, capsys):
    f = tmp_path / ".env"
    f.write_text('# comment\nGEMINI_API_KEY="from-file"\nOTHER=1\nEXISTING=file\n', encoding="utf8")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("OTHER", raising=False)
    monkeypatch.setenv("EXISTING", "shell")
    load_env_file(f)
    import os
    assert os.environ["GEMINI_API_KEY"] == "from-file" and os.environ["OTHER"] == "1" and os.environ["EXISTING"] == "shell"
    assert "from-file" not in capsys.readouterr().out
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("OTHER", raising=False)
