import pytest


@pytest.fixture(autouse=True)
def no_real_model_by_default(monkeypatch):
    """Tests never call a real model: default to no provider unless a test sets one."""
    monkeypatch.setenv("TRUSTGUARD_PROVIDER", "none")
    monkeypatch.setenv("TRUSTGUARD_SANDBOX", "off")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
