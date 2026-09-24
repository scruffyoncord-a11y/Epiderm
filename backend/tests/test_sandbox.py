import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import app.main as main
import app.reasoning as r
from app import documents, sandbox
from app.models import Direction

client = TestClient(main.app)
BACKEND = Path(__file__).resolve().parent.parent

FORGED_PDF_META = {"/Producer": "Adobe Photoshop 25.0", "/Creator": "Adobe Photoshop", "/CreationDate": "D:20260923100000Z"}


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


HEADERS = "Authentication-Results: mx; spf=pass; dkim=pass; dmarc=pass\nFrom: bigbasket <alert@info.bigbasket.com>\n"
docker_needed = pytest.mark.skipif(not sandbox.docker_ready(force=True), reason="Docker or the trustguard-sandbox image is not available")


# ------------------------------------------------------------------ the worker protocol (runs locally, no container)

def run_worker(task: str, meta: dict, payload: bytes):
    return subprocess.run([sys.executable, "-m", "app.worker", task], input=json.dumps(meta).encode() + b"\n" + payload,
                          capture_output=True, cwd=BACKEND, timeout=60)


def test_worker_document_task_returns_a_validated_report():
    p = run_worker("document", {"filename": "inv.pdf", "vendor": None}, make_pdf(FORGED_PDF_META))
    assert p.returncode == 0
    report = sandbox.DocumentReport.model_validate_json(p.stdout)
    assert report.format == "pdf" and any(s.id == "document.editing_tool" for s in report.signals)


def test_worker_headers_task_returns_fields():
    p = run_worker("headers", {}, HEADERS.encode())
    d = json.loads(p.stdout)
    assert p.returncode == 0 and d["from_email"] == "alert@info.bigbasket.com" and d["dmarc"] == "pass"


def test_worker_rejects_bad_usage_and_oversized_input():
    assert subprocess.run([sys.executable, "-m", "app.worker", "rm -rf"], input=b"{}\n", capture_output=True, cwd=BACKEND).returncode == 2
    assert subprocess.run([sys.executable, "-m", "app.worker"], input=b"{}\n", capture_output=True, cwd=BACKEND).returncode == 2
    big = subprocess.run([sys.executable, "-m", "app.worker", "document"], input=b"{}\n" + b"x" * (12 * 1024 * 1024),
                         capture_output=True, cwd=BACKEND, timeout=60)
    assert big.returncode == 2


# ------------------------------------------------------------------ host logic (fake container runs)

def test_mode_selection(monkeypatch):
    monkeypatch.setattr(sandbox, "docker_ready", lambda force=False: True)
    monkeypatch.setenv("TRUSTGUARD_SANDBOX", "off")
    assert sandbox.mode() == "none"
    for setting in ("auto", "docker"):
        monkeypatch.setenv("TRUSTGUARD_SANDBOX", setting)
        assert sandbox.mode() == "container"
    monkeypatch.setattr(sandbox, "docker_ready", lambda force=False: False)
    monkeypatch.setenv("TRUSTGUARD_SANDBOX", "auto")
    assert sandbox.mode() == "none"  # allowed to run without, and the UI says so
    monkeypatch.setenv("TRUSTGUARD_SANDBOX", "docker")
    with pytest.raises(sandbox.SandboxUnavailable):
        sandbox.mode()


def test_container_flags_make_it_private():
    args = sandbox.base_args("tg-test")
    joined = " ".join(args)
    assert "--rm" in args  # deleted when it exits
    assert args[args.index("--network") + 1] == "none"
    assert "--read-only" in args and "noexec" in joined
    assert args[args.index("--cap-drop") + 1] == "ALL" and "no-new-privileges" in joined
    assert args[args.index("--user") + 1] == "65534:65534"  # not root
    assert args[args.index("--memory") + 1] == "256m" and "--pids-limit" in args and "--cpus" in args
    assert "-v" not in args and "--volume" not in args and "--mount" not in args  # nothing from the host is mounted
    assert "docker.sock" not in joined and "--privileged" not in args


def fake_run(monkeypatch, stdout=b"", returncode=0, raises=None):
    monkeypatch.setattr(sandbox.shutil, "which", lambda name: "docker")
    calls = []

    def run(cmd, input=None, capture_output=None, timeout=None):
        calls.append(cmd)
        if raises:
            raise raises
        return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=b"")

    monkeypatch.setattr(sandbox.subprocess, "run", run)
    return calls


def test_a_valid_document_report_is_accepted_and_marked(monkeypatch):
    report = sandbox.DocumentReport(filename="a/b\\c.pdf", format="pdf", size_bytes=10, signals=[])
    fake_run(monkeypatch, stdout=report.model_dump_json().encode())
    got = sandbox.analyze_document(b"%PDF-", "a.pdf", None)
    assert got.isolation == "container" and "/" not in got.filename and "\\" not in got.filename


def test_bad_output_nonzero_exit_timeout_and_oversize_are_errors(monkeypatch):
    fake_run(monkeypatch, stdout=b"not json")
    with pytest.raises(sandbox.SandboxError):
        sandbox.analyze_document(b"%PDF-", "a.pdf", None)
    fake_run(monkeypatch, stdout=b"{}", returncode=137)
    with pytest.raises(sandbox.SandboxError):
        sandbox.parse_headers("From: a@b.com")
    calls = fake_run(monkeypatch, raises=subprocess.TimeoutExpired("docker", 30))
    with pytest.raises(sandbox.SandboxError):
        sandbox.parse_headers("From: a@b.com")
    assert any("rm" in c and "-f" in c for c in calls), "a timed-out container must be force-removed"
    fake_run(monkeypatch, stdout=b"x" * (sandbox.MAX_OUTPUT + 1))
    with pytest.raises(sandbox.SandboxError):
        sandbox.parse_headers("From: a@b.com")


def test_header_answers_from_the_sandbox_are_revalidated():
    info = sandbox.clean_header_info({
        "from_display": "x" * 999, "from_email": "not an email", "reply_to_email": "ok@example.com", "spf": "evil<script>",
        "dkim": "pass", "dkim_domain": "bad domain!", "dmarc": "fail", "sending_ip": "10.0.0.5", "subject": "y" * 999})
    assert info.from_email is None and info.reply_to_email == "ok@example.com"
    assert info.spf is None and info.dkim == "pass" and info.dmarc == "fail"
    assert info.dkim_domain is None and info.sending_ip is None  # private IPs are never accepted
    assert len(info.from_display) <= 120 and len(info.subject) <= 200
    with pytest.raises(sandbox.SandboxError):
        sandbox.clean_header_info(["not", "a", "dict"])


# ------------------------------------------------------------------ the API uses the sandbox and fails closed

def test_uploaded_files_go_to_the_sandbox_and_never_to_the_in_process_parser(monkeypatch):
    monkeypatch.setattr(sandbox, "mode", lambda: "container")
    monkeypatch.setattr(documents, "analyze_full", lambda *a, **k: (_ for _ in ()).throw(AssertionError("parsed outside the sandbox")))
    monkeypatch.setattr(sandbox, "analyze_document_full", lambda data, name, vendor, session=None: (sandbox.DocumentReport(
        filename=name, format="pdf", size_bytes=len(data), signals=[], isolation="container"), "", None))
    body = client.post("/analyze-document", files={"file": ("x.pdf", make_pdf(), "application/pdf")}).json()
    assert body["isolation"] == "container"


def test_a_sandbox_failure_refuses_the_file_and_does_not_fall_back(monkeypatch):
    monkeypatch.setattr(sandbox, "mode", lambda: "container")
    monkeypatch.setattr(documents, "analyze_full", lambda *a, **k: (_ for _ in ()).throw(AssertionError("fell back to in-process parsing")))
    monkeypatch.setattr(sandbox, "analyze_document_full", lambda *a, **k: (_ for _ in ()).throw(sandbox.SandboxError("exited with 137")))
    res = client.post("/analyze-document", files={"file": ("x.pdf", make_pdf(), "application/pdf")})
    assert res.status_code == 200
    body = res.json()
    assert body["isolation"] == "container" and any(s["id"] == "document.sandbox_refused" for s in body["signals"])
    assert "not opened outside the sandbox" in body["summary"] and "137" not in res.text  # nothing internal is echoed


def test_required_sandbox_that_is_missing_is_a_503_not_a_silent_fallback(monkeypatch):
    monkeypatch.setenv("TRUSTGUARD_SANDBOX", "docker")
    monkeypatch.setattr(sandbox, "docker_ready", lambda force=False: False)
    assert client.post("/analyze-document", files={"file": ("x.pdf", make_pdf(), "application/pdf")}).status_code == 503
    assert client.post("/analyze-text", json={"headers": HEADERS}).status_code == 503
    assert client.post("/analyze-text", json={"text": "hello there"}).status_code == 200  # plain text needs no container


def test_headers_are_parsed_in_the_sandbox_and_failure_fails_closed(monkeypatch):
    monkeypatch.setattr(sandbox, "mode", lambda: "container")
    monkeypatch.setattr(r, "parse_headers", lambda *a, **k: (_ for _ in ()).throw(AssertionError("parsed outside the sandbox")))
    monkeypatch.setattr(sandbox, "parse_headers", lambda text, session=None: sandbox.clean_header_info(
        {"from_email": "alert@info.bigbasket.com", "spf": "pass", "dkim": "pass", "dmarc": "pass"}))
    ok = client.post("/analyze-text", json={"headers": HEADERS}).json()
    assert ok["isolation"] == "container" and ok["header_summary"]["from_email"] == "alert@info.bigbasket.com"

    monkeypatch.setattr(sandbox, "parse_headers", lambda text, session=None: (_ for _ in ()).throw(sandbox.SandboxError("timed out")))
    bad = client.post("/analyze-text", json={"headers": HEADERS}).json()
    assert bad["isolation"] == "container" and bad["header_summary"] is None
    assert any(s["id"] == "email.headers_unreadable" for s in bad["signals"])


def test_isolation_is_none_when_no_headers_were_given(monkeypatch):
    monkeypatch.setattr(sandbox, "mode", lambda: "container")
    assert client.post("/analyze-text", json={"text": "hello there"}).json()["isolation"] == "none"


# ------------------------------------------------------------------ real containers (skipped without Docker)

def container_probe(code: str) -> str:
    """Runs Python inside a container started with the production flags."""
    cmd = ["docker", *sandbox.base_args("tg-probe-" + code[:4].encode().hex()), "--entrypoint", "python", sandbox.IMAGE, "-c", code]
    return subprocess.run(cmd, capture_output=True, timeout=60).stdout.decode().strip()


@docker_needed
def test_real_container_checks_a_document_end_to_end():
    report = sandbox.analyze_document(make_pdf(FORGED_PDF_META), "forged.pdf", "Sunrise Traders")
    assert report.isolation == "container" and report.format == "pdf"
    assert any(s.id == "document.editing_tool" and s.direction == Direction.suspicious for s in report.signals)


@docker_needed
def test_real_container_parses_headers():
    info = sandbox.parse_headers(HEADERS)
    assert info.from_email == "alert@info.bigbasket.com" and (info.spf, info.dkim, info.dmarc) == ("pass", "pass", "pass")


@docker_needed
def test_real_container_is_actually_private():
    assert container_probe("import os; print(os.getuid())") == "65534"
    assert "blocked" in container_probe("import socket\ntry:\n  socket.create_connection(('8.8.8.8',53),3); print('REACHED')\nexcept OSError: print('blocked')")
    assert "blocked" in container_probe("import socket\ntry:\n  socket.gethostbyname('example.com'); print('RESOLVED')\nexcept OSError: print('blocked')")
    assert "blocked" in container_probe("try:\n  open('/sandbox/x','w'); print('WROTE')\nexcept OSError: print('blocked')")
    assert container_probe("print([l for l in open('/proc/self/status') if l.startswith('CapEff')][0].split()[1])") == "0000000000000000"
    assert "SECRET" not in container_probe("import os; print(os.environ)") and container_probe("import os; print(os.path.exists('/sandbox/.env'))") == "False"


@docker_needed
def test_real_container_survives_a_zip_bomb_and_garbage():
    import io
    import zipfile
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("word/document.xml", "<w:document/>")
        z.writestr("word/big.bin", b"\0" * (70 * 1024 * 1024))
    for blob in (buf.getvalue(), b"\x00" * 100, b"%PDF-1.4 nonsense"):
        report = sandbox.analyze_document(blob, "bad", None)
        assert any(s.id == "document.unreadable" for s in report.signals)


@docker_needed
def test_no_containers_are_left_behind():
    def names():
        out = subprocess.run(["docker", "ps", "-a", "--filter", "name=tg-", "--format", "{{.Names}}"], capture_output=True, timeout=30)
        return set(out.stdout.decode().split())

    before = names()  # a running app on this machine may have its own session container; only new ones count
    sandbox.parse_headers(HEADERS)
    assert names() - before == set()
