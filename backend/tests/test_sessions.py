import json
import struct
import subprocess
import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.main as main
from app import sandbox

client = TestClient(main.app)
BACKEND = Path(__file__).resolve().parent.parent
docker_needed = pytest.mark.skipif(not sandbox.docker_ready(force=True), reason="Docker or the trustguard-sandbox image is not available")


@pytest.fixture
def real_sandbox(monkeypatch):
    """The suite defaults the sandbox to off; tests that use real containers switch it on."""
    monkeypatch.setenv("TRUSTGUARD_SANDBOX", "auto")
    sandbox.docker_ready(force=True)


def docker_test(fn):
    return pytest.mark.usefixtures("real_sandbox")(docker_needed(fn))

HEADERS = "Authentication-Results: mx; spf=pass; dkim=pass; dmarc=pass\nFrom: bigbasket <alert@info.bigbasket.com>\n"


def make_pdf(meta=None) -> bytes:
    import io
    from pypdf import PdfWriter
    w = PdfWriter()
    w.add_blank_page(width=200, height=200)
    if meta:
        w.add_metadata(meta)
    buf = io.BytesIO()
    w.write(buf)
    return buf.getvalue()


_BASELINE: set[str] = set()


def _all_containers(prefix: str = "tg-sess-") -> list[str]:
    out = subprocess.run(["docker", "ps", "-a", "--filter", f"name={prefix}", "--format", "{{.Names}}"], capture_output=True, timeout=30)
    return out.stdout.decode().split()


def containers(prefix: str = "tg-sess-") -> list[str]:
    """Containers created by THIS test. A running app on the same machine may have its own; those are not ours to count."""
    return [n for n in _all_containers(prefix) if n not in _BASELINE]


@pytest.fixture(autouse=True)
def tidy():
    global _BASELINE
    try:
        _BASELINE = set(_all_containers("tg-"))
    except (OSError, subprocess.SubprocessError):
        _BASELINE = set()
    yield
    sandbox.sessions.close_all()


@pytest.fixture
def container_mode(monkeypatch):
    monkeypatch.setenv("TRUSTGUARD_SANDBOX", "auto")
    monkeypatch.setattr(sandbox, "docker_ready", lambda force=False: True)


# ------------------------------------------------------------------ the serve-mode protocol (a local process, no Docker)

class LocalServe:
    def __init__(self):
        self.p = subprocess.Popen([sys.executable, "-m", "app.worker", "serve"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  stderr=subprocess.DEVNULL, cwd=BACKEND)
        self.hello = self.read()

    def read(self):
        (n,) = struct.unpack(">I", self.p.stdout.read(4))
        return json.loads(self.p.stdout.read(n))

    def ask(self, task, payload=b"", **meta):
        m = json.dumps({"task": task, **meta}).encode()
        self.p.stdin.write(struct.pack(">I", len(m)) + m + struct.pack(">Q", len(payload)) + payload)
        self.p.stdin.flush()
        return self.read()

    def stop(self):
        self.p.stdin.close()
        return self.p.wait(timeout=10)


def test_serve_handshake_then_many_requests_in_one_process():
    s = LocalServe()
    try:
        assert s.hello == {"ready": True}
        a = s.ask("headers", HEADERS.encode())
        assert a["ok"] and a["result"]["from_email"] == "alert@info.bigbasket.com"
        b = s.ask("document", make_pdf({"/Producer": "Adobe Photoshop 25.0"}), filename="x.pdf", vendor=None)
        assert b["ok"] and b["result"]["format"] == "pdf"
        c = s.ask("headers", b"From: other@example.org\n")
        assert c["result"]["from_email"] == "other@example.org" and "bigbasket" not in json.dumps(c)  # nothing carried over
    finally:
        assert s.stop() == 0  # closing the input ends the session cleanly


def test_a_bad_request_does_not_end_the_session():
    s = LocalServe()
    try:
        assert s.ask("nonsense")["ok"] is False
        assert s.ask("document", b"\x00garbage", filename="x")["ok"] is True  # unreadable is a normal result
        assert s.ask("headers", HEADERS.encode())["ok"] is True
        assert s.p.poll() is None
    finally:
        s.stop()


def test_an_oversized_frame_ends_the_session_instead_of_being_read():
    s = LocalServe()
    s.p.stdin.write(struct.pack(">I", 10_000_000))  # claims a huge metadata block
    s.p.stdin.flush()
    assert s.p.wait(timeout=10) == 0


# ------------------------------------------------------------------ the manager (fake containers: cap, idle, clean-up)

class FakeContainer:
    made: list = []

    def __init__(self):
        self.closed = False
        FakeContainer.made.append(self)

    def alive(self):
        return not self.closed

    def close(self):
        self.closed = True


def test_manager_cap_idle_close_and_unique_unguessable_ids(monkeypatch, container_mode):
    FakeContainer.made = []
    monkeypatch.setattr(sandbox, "SessionContainer", FakeContainer)
    monkeypatch.setattr(sandbox, "MAX_SESSIONS", 2)
    mgr = sandbox.SessionManager()
    monkeypatch.setattr(mgr, "_ensure_reaper", lambda: None)
    a, b = mgr.open(), mgr.open()
    assert a != b and len(a) >= 32 and len(b) >= 32
    assert mgr.get(a) is FakeContainer.made[0]
    c = mgr.open()  # over the cap: the least recently used (b) is closed to make room
    assert mgr.count() == 2 and FakeContainer.made[1].closed and mgr.get(b) is None
    assert mgr.get("not-a-session") is None and mgr.get(None) is None
    assert mgr.reap_idle(now=time.monotonic() + sandbox.IDLE_TIMEOUT + 5) == 2 and mgr.count() == 0
    assert all(x.closed for x in FakeContainer.made)
    d = mgr.open()
    assert mgr.close(d) is True and mgr.close(d) is False and mgr.close(None) is False
    mgr.open()
    mgr.close_all()
    assert mgr.count() == 0 and all(x.closed for x in FakeContainer.made)
    _ = c


def test_a_dead_session_is_dropped_not_reused(monkeypatch, container_mode):
    FakeContainer.made = []
    monkeypatch.setattr(sandbox, "SessionContainer", FakeContainer)
    mgr = sandbox.SessionManager()
    monkeypatch.setattr(mgr, "_ensure_reaper", lambda: None)
    sid = mgr.open()
    FakeContainer.made[0].closed = True
    assert mgr.get(sid) is None and mgr.count() == 0


def test_no_session_when_the_sandbox_is_off_or_missing(monkeypatch):
    monkeypatch.setenv("TRUSTGUARD_SANDBOX", "off")
    assert client.post("/sessions").json() == {"session_id": None, "isolation": "none"}
    monkeypatch.setenv("TRUSTGUARD_SANDBOX", "docker")
    monkeypatch.setattr(sandbox, "docker_ready", lambda force=False: False)
    assert client.post("/sessions").status_code == 503
    assert client.post("/sessions/whatever/close").status_code == 204  # closing is always safe and reveals nothing


def test_a_failed_open_falls_back_quietly_unless_docker_is_required(monkeypatch, container_mode):
    monkeypatch.setattr(sandbox, "SessionContainer", lambda: (_ for _ in ()).throw(sandbox.SandboxError("did not become ready")))
    assert client.post("/sessions").json() == {"session_id": None, "isolation": "none"}
    monkeypatch.setenv("TRUSTGUARD_SANDBOX", "docker")
    assert client.post("/sessions").status_code == 503


# ------------------------------------------------------------------ real session containers (skipped without Docker)

@docker_test
def test_a_session_container_opens_stays_private_and_is_deleted_on_close():
    sid = client.post("/sessions").json()["session_id"]
    assert sid and len(sid) >= 32
    names = containers()
    assert len(names) == 1
    info = json.loads(subprocess.run(["docker", "inspect", names[0]], capture_output=True, timeout=30).stdout)[0]
    host = info["HostConfig"]
    assert host["NetworkMode"] == "none" and host["ReadonlyRootfs"] is True and host["Privileged"] is False
    assert host["CapDrop"] == ["ALL"] and host["Memory"] == 256 * 1024 * 1024 and host["PidsLimit"] == 64
    assert info["Config"]["User"] == "65534:65534" and info["Mounts"] == []  # nothing from this machine is mounted in
    assert client.post(f"/sessions/{sid}/close").status_code == 204
    time.sleep(1)
    assert containers() == []


@docker_test
def test_checks_in_a_session_reuse_the_same_container_and_are_fast():
    sid = client.post("/sessions").json()["session_id"]
    first = containers()
    sandbox_calls = []
    original = sandbox._run
    sandbox._run = lambda *a, **k: sandbox_calls.append(a) or original(*a, **k)  # would be called only for one-shot containers
    try:
        times = []
        for _ in range(3):
            t = time.time()
            res = client.post("/analyze-document", files={"file": ("x.pdf", make_pdf({"/Producer": "Adobe Photoshop 25.0"}), "application/pdf")},
                              headers={"X-Session-Id": sid}).json()
            times.append(time.time() - t)
            assert res["isolation"] == "container" and any(s["id"] == "document.editing_tool" for s in res["signals"])
        hdr = client.post("/analyze-text", json={"headers": HEADERS}, headers={"X-Session-Id": sid}).json()
        assert hdr["header_summary"]["from_email"] == "alert@info.bigbasket.com"
    finally:
        sandbox._run = original
    assert sandbox_calls == [], "a session's checks must not start extra one-shot containers"
    assert containers() == first and max(times) < 3
    client.post(f"/sessions/{sid}/close")


@docker_test
def test_two_people_get_two_separate_containers_and_closing_one_leaves_the_other():
    a = client.post("/sessions").json()["session_id"]
    b = client.post("/sessions").json()["session_id"]
    assert a != b and len(containers()) == 2
    client.post(f"/sessions/{a}/close")
    time.sleep(1)
    assert len(containers()) == 1
    res = client.post("/analyze-text", json={"headers": HEADERS}, headers={"X-Session-Id": b}).json()
    assert res["isolation"] == "container"
    client.post(f"/sessions/{b}/close")


@docker_test
def test_a_bad_file_does_not_kill_the_session_and_a_hung_one_does():
    sid = client.post("/sessions").json()["session_id"]
    box = sandbox.sessions.get(sid)
    assert box.alive()
    with pytest.raises(sandbox.SandboxError):
        box.call("nonsense", {}, b"")  # rejected, but the session carries on
    assert box.alive()
    report = sandbox.analyze_document(b"\x00garbage", "bad", None, box)
    assert any(s.id == "document.unreadable" for s in report.signals) and box.alive()
    old = sandbox.RUN_TIMEOUT
    sandbox.RUN_TIMEOUT = 0  # no time to answer: the container is treated as hung and removed
    try:
        with pytest.raises(sandbox.SandboxError):
            box.call("headers", {}, HEADERS.encode())
    finally:
        sandbox.RUN_TIMEOUT = old
    assert not box.alive()
    time.sleep(1)
    assert containers() == []


@docker_test
def test_if_a_session_container_dies_the_next_check_uses_a_fresh_one_off_container():
    sid = client.post("/sessions").json()["session_id"]
    name = containers()[0]
    subprocess.run(["docker", "rm", "-f", name], capture_output=True, timeout=30)
    time.sleep(1)
    res = client.post("/analyze-document", files={"file": ("x.pdf", make_pdf({"/Producer": "Adobe Photoshop 25.0"}), "application/pdf")},
                      headers={"X-Session-Id": sid}).json()
    assert res["isolation"] == "container" and any(s["id"] == "document.editing_tool" for s in res["signals"])
    assert sandbox.sessions.get(sid) is None  # the dead session was forgotten


@docker_test
def test_an_unknown_session_id_is_ignored_and_the_check_still_runs_in_a_container():
    res = client.post("/analyze-text", json={"headers": HEADERS}, headers={"X-Session-Id": "forged-id"}).json()
    assert res["isolation"] == "container" and res["header_summary"]["from_email"] == "alert@info.bigbasket.com"


@docker_test
def test_close_all_removes_every_session_container_and_status_counts_them():
    client.post("/sessions")
    client.post("/sessions")
    assert client.get("/config").json()["sandbox"]["open_sessions"] == 2
    sandbox.sessions.close_all()
    time.sleep(1)
    assert containers() == [] and client.get("/config").json()["sandbox"]["open_sessions"] == 0
