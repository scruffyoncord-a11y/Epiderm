from fastapi.testclient import TestClient

import app.analyzers.ip as ipmod
from app.analyzers.ip import analyze_ip, classify
from app.main import app
from app.models import Band, Direction

client = TestClient(app)


class FakeResolver:
    def __init__(self, ptr=None, forward=None):
        self.ptr, self.fwd, self.reverse_calls = ptr, forward or [], []

    def reverse(self, ip):
        self.reverse_calls.append(ip)
        return self.ptr

    def forward(self, name):
        return self.fwd


def ids(res, direction=None):
    return {s.id for s in res.signals if direction is None or s.direction == direction}


def test_classification_of_common_names():
    assert classify("tor-exit-14.example.org") == "anonymiser"
    assert classify("ec2-3-4-5-6.compute-1.amazonaws.com") == "hosting"
    assert classify("static.vps.hetzner.de") == "hosting"
    assert classify("abts-kl-dynamic-12.34.56.78.airtel.in") == "residential"
    assert classify("mail.example.com") == "unknown"


def test_hosting_ptr_is_a_moderate_suspicious_signal_when_forward_confirmed():
    r = analyze_ip("8.8.4.4", FakeResolver("ec2-8-8-4-4.compute-1.amazonaws.com", ["8.8.4.4"]))
    assert r.kind == "hosting" and r.forward_confirmed is True
    assert ids(r, Direction.suspicious) == {"ip.rdns_hosting"}


def test_unconfirmed_forward_lookup_adds_a_weak_signal():
    r = analyze_ip("8.8.4.4", FakeResolver("host.example.net", ["1.2.3.4"]))
    assert r.forward_confirmed is False
    assert "ip.rdns_unconfirmed" in ids(r, Direction.suspicious)


def test_missing_ptr_is_unknown_never_suspicious():
    r = analyze_ip("8.8.4.4", FakeResolver(None))
    assert ids(r, Direction.suspicious) == set()
    assert ids(r) == {"ip.rdns_missing"}


def test_residential_ptr_is_reassuring():
    r = analyze_ip("8.8.4.4", FakeResolver("dynamic-8-8-4-4.broadband.example.in", ["8.8.4.4"]))
    assert ids(r, Direction.reassuring) == {"ip.rdns_residential"}


def test_private_loopback_and_invalid_addresses_are_never_looked_up():
    fake = FakeResolver("internal.corp", ["10.0.0.1"])
    for addr in ("10.0.0.1", "192.168.1.5", "127.0.0.1", "169.254.1.1", "::1"):
        r = analyze_ip(addr, fake)
        assert r.kind == "private"
    assert fake.reverse_calls == []
    assert analyze_ip("not-an-ip", fake).kind == "invalid"


def test_lookup_timeout_returns_unknown(monkeypatch):
    class Slow(ipmod.SocketResolver):
        def reverse(self, ip):
            return None  # what the timeout path yields

    assert ids(analyze_ip("8.8.4.4", Slow())) == {"ip.rdns_missing"}


def test_ip_signals_join_the_text_score_and_ip_is_no_longer_unchecked(monkeypatch):
    import app.reasoning as r
    text = "Urgent: transfer Rs 50,000 today and keep this between us."
    without = r.analyze_with_reasoning(text)
    with_ip = r.analyze_with_reasoning(text, ip="185.220.101.14",
                                       resolver=FakeResolver("tor-exit-14.example.org", ["185.220.101.14"]))
    assert with_ip.trust_score <= without.trust_score
    assert any(s.id == "ip.rdns_anonymiser" for s in with_ip.signals)
    assert not any(c.startswith("Device, IP address") for c in with_ip.could_not_check)
    assert any(c.startswith("Device and location") for c in with_ip.could_not_check)
    assert any(c.startswith("Device, IP address") for c in without.could_not_check)


def test_a_hosting_ip_alone_cannot_hold_a_genuine_message():
    import app.reasoning as r
    a = r.analyze_with_reasoning("Lunch on Friday at 1pm?", ip="8.8.4.4",
                                 resolver=FakeResolver("ec2-8-8-4-4.compute-1.amazonaws.com", ["8.8.4.4"]))
    assert a.band == Band.allow


def test_endpoint_accepts_optional_ip(monkeypatch):
    import app.reasoning as r
    monkeypatch.setattr(r, "analyze_ip", lambda ip, resolver=None: analyze_ip(ip, FakeResolver("tor-exit-1.example.org", [ip])))
    body = client.post("/analyze-text", json={"text": "hello there", "ip": "185.220.101.14"}).json()
    assert any(s["id"] == "ip.rdns_anonymiser" for s in body["signals"])
    assert client.post("/analyze-text", json={"text": "hello", "ip": "x" * 100}).status_code == 422
    assert client.post("/analyze-text", json={"text": "hello", "ip": "not-an-ip"}).status_code == 200
