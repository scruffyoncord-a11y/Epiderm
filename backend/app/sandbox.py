"""Host side of the sandbox: private throwaway containers for parsing untrusted input.

Untrusted bytes (uploaded files, pasted email headers) are parsed inside a container that has no
network, a read-only filesystem, no privileges and hard memory / process / time limits. What comes
back is a small JSON result. It crosses a trust boundary, so it is validated again here before
anything uses it.

Two ways to run it:
- a SESSION container, opened when a person picks a category and kept for that person's checks until
  they leave, go idle, or close the tab (each person gets their own);
- a ONE-SHOT container for a single check, used when there is no session or the session's container
  has died.

Fail closed: if the sandbox is available but a run fails (timeout, out-of-memory, bad output), the
file is refused. It is never quietly parsed in this privileged process instead.

TRUSTGUARD_SANDBOX = auto (default: use Docker when the image is ready) | docker (require it) | off
"""
from __future__ import annotations

import atexit
import base64
import ipaddress
import json
import os
import queue
import re
import secrets
import shutil
import struct
import subprocess
import threading
import time
import uuid
from typing import Optional

from .analyzers.headers import RESULT, HeaderInfo
from .models import Category, Direction, DocumentReport, Signal

IMAGE = os.getenv("TRUSTGUARD_SANDBOX_IMAGE", "trustguard-sandbox")
RUN_TIMEOUT = 30  # seconds for one check (or for a one-shot container including start-up)
OPEN_TIMEOUT = 25  # seconds for a session container to become ready
MAX_OUTPUT = 1_000_000  # bytes accepted back from a container
MAX_INPUT = 11 * 1024 * 1024
MAX_SESSIONS = int(os.getenv("TRUSTGUARD_MAX_SESSIONS", "6"))
IDLE_TIMEOUT = float(os.getenv("TRUSTGUARD_SESSION_IDLE_SECONDS", "600"))
_SLOTS = threading.BoundedSemaphore(int(os.getenv("TRUSTGUARD_SANDBOX_SLOTS", "4")))
_READY_TTL = 20.0
_ready: tuple[float, bool] = (0.0, False)
_RESULTS = set(RESULT.strip("()").split("|"))
_EMAIL = re.compile(r"[A-Za-z0-9._%+'-]{1,64}@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")
_DOMAIN = re.compile(r"[A-Za-z0-9.-]{1,253}")


class SandboxError(Exception):
    """A sandbox run failed. The message is generic on purpose: nothing from inside is echoed to users."""


class SandboxUnavailable(SandboxError):
    """The sandbox was required but Docker or the image is not available."""


def _setting() -> str:
    s = os.getenv("TRUSTGUARD_SANDBOX", "auto").lower()
    return s if s in ("auto", "docker", "off") else "auto"


def docker_ready(force: bool = False) -> bool:
    """Docker is installed, running, and the sandbox image exists. Cached briefly."""
    global _ready
    now = time.monotonic()
    if not force and now - _ready[0] < _READY_TTL:
        return _ready[1]
    ok = False
    exe = shutil.which("docker")
    if exe:
        try:
            ok = subprocess.run([exe, "image", "inspect", IMAGE], capture_output=True, timeout=8).returncode == 0
        except (subprocess.TimeoutExpired, OSError):
            ok = False
    _ready = (now, ok)
    return ok


def mode() -> str:
    """'container' or 'none'. Raises SandboxUnavailable when TRUSTGUARD_SANDBOX=docker cannot be honoured."""
    s = _setting()
    if s == "off":
        return "none"
    if docker_ready():
        return "container"
    if s == "docker":
        raise SandboxUnavailable("The sandbox is required but Docker or the sandbox image is not available.")
    return "none"


def status() -> dict:
    ready = docker_ready()
    s = _setting()
    return {"setting": s, "mode": "container" if ready and s != "off" else "none", "image_ready": ready,
            "open_sessions": sessions.count()}


def base_args(name: str) -> list[str]:
    """Everything that makes the container private. Kept in one place so tests can check the real flags."""
    return [
        "run", "--rm", "-i", "--name", name,
        "--network", "none",
        "--read-only", "--tmpfs", "/tmp:rw,noexec,nosuid,size=16m",
        "--memory", "256m", "--memory-swap", "256m", "--cpus", "1", "--pids-limit", "64",
        "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
        "--user", "65534:65534",
    ]


def _docker() -> str:
    exe = shutil.which("docker")
    if not exe:
        raise SandboxUnavailable("Docker is not available.")
    return exe


def _kill(name: str) -> None:
    exe = shutil.which("docker")
    if exe:
        try:
            subprocess.run([exe, "rm", "-f", name], capture_output=True, timeout=10)
        except (subprocess.TimeoutExpired, OSError):
            pass


# --------------------------------------------------------------------------- one-shot container

def _run(task: str, meta: dict, payload: bytes) -> object:
    exe = _docker()
    if len(payload) > MAX_INPUT:
        raise SandboxError("input too large")
    name = f"tg-{uuid.uuid4().hex[:12]}"
    stdin = json.dumps(meta).encode("utf-8") + b"\n" + payload
    if not _SLOTS.acquire(timeout=10):
        raise SandboxError("busy")
    try:
        proc = subprocess.run([exe, *base_args(name), IMAGE, task], input=stdin, capture_output=True, timeout=RUN_TIMEOUT)
    except subprocess.TimeoutExpired:
        _kill(name)
        raise SandboxError("timed out") from None
    except OSError:
        raise SandboxError("could not start") from None
    finally:
        _SLOTS.release()
    if proc.returncode != 0:
        raise SandboxError(f"exited with {proc.returncode}")
    if len(proc.stdout) > MAX_OUTPUT:
        raise SandboxError("output too large")
    try:
        return json.loads(proc.stdout)
    except ValueError:
        raise SandboxError("invalid output") from None


# --------------------------------------------------------------------------- session container

class SessionContainer:
    """One person's private container, kept open while they work. Calls are serialised."""

    def __init__(self) -> None:
        exe = _docker()
        self.name = f"tg-sess-{uuid.uuid4().hex[:12]}"
        self._lock = threading.Lock()
        self._replies: "queue.Queue[Optional[bytes]]" = queue.Queue()
        self.closed = False
        try:
            self.proc = subprocess.Popen([exe, *base_args(self.name), IMAGE, "serve"],
                                         stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        except OSError:
            raise SandboxError("could not start") from None
        threading.Thread(target=self._read_replies, daemon=True).start()
        try:
            hello = self._replies.get(timeout=OPEN_TIMEOUT)
            if hello is None or json.loads(hello).get("ready") is not True:
                raise SandboxError("did not become ready")
        except (queue.Empty, ValueError, SandboxError):
            self.close()
            raise SandboxError("did not become ready") from None

    def _read_replies(self) -> None:
        out = self.proc.stdout
        while True:
            head = self._read_exact(out, 4)
            if head is None:
                break
            (n,) = struct.unpack(">I", head)
            if n > MAX_OUTPUT:
                break
            body = self._read_exact(out, n)
            if body is None:
                break
            self._replies.put(body)
        self._replies.put(None)  # the container ended

    @staticmethod
    def _read_exact(stream, n: int) -> Optional[bytes]:
        buf = bytearray()
        while len(buf) < n:
            chunk = stream.read(n - len(buf))
            if not chunk:
                return None
            buf.extend(chunk)
        return bytes(buf)

    def alive(self) -> bool:
        return not self.closed and self.proc.poll() is None

    def call(self, task: str, meta: dict, payload: bytes) -> object:
        if len(payload) > MAX_INPUT:
            raise SandboxError("input too large")
        m = json.dumps({**meta, "task": task}).encode("utf-8")
        with self._lock:
            if not self.alive():
                raise SandboxError("session ended")
            while not self._replies.empty():  # discard anything stale from a previous timed-out call
                self._replies.get_nowait()
            try:
                self.proc.stdin.write(struct.pack(">I", len(m)) + m + struct.pack(">Q", len(payload)) + payload)
                self.proc.stdin.flush()
                body = self._replies.get(timeout=RUN_TIMEOUT)
            except (queue.Empty, OSError, ValueError):
                self.close()  # a hung or broken container is not reused
                raise SandboxError("timed out or broke") from None
        if body is None:
            self.close()
            raise SandboxError("container ended")
        try:
            reply = json.loads(body)
        except ValueError:
            self.close()
            raise SandboxError("invalid output") from None
        if not isinstance(reply, dict) or reply.get("ok") is not True:
            raise SandboxError("failed")  # this file failed; the session itself is still fine
        return reply.get("result")

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        try:
            self.proc.stdin.close()
        except (OSError, ValueError):
            pass
        _kill(self.name)
        try:
            self.proc.kill()
        except OSError:
            pass


class SessionManager:
    """Tracks open session containers: a cap, an idle timeout, and clean-up on exit."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._items: dict[str, tuple[SessionContainer, float]] = {}
        self._reaper: Optional[threading.Thread] = None
        atexit.register(self.close_all)

    def count(self) -> int:
        with self._lock:
            return len(self._items)

    def open(self) -> str:
        if mode() != "container":
            raise SandboxUnavailable("No sandbox container is available.")
        with self._lock:
            while len(self._items) >= MAX_SESSIONS:  # make room: close the least recently used
                oldest = min(self._items, key=lambda k: self._items[k][1])
                self._items.pop(oldest)[0].close()
        container = SessionContainer()  # may take a second or two
        sid = secrets.token_urlsafe(24)
        with self._lock:
            self._items[sid] = (container, time.monotonic())
        self._ensure_reaper()
        return sid

    def get(self, sid: Optional[str]) -> Optional[SessionContainer]:
        if not sid:
            return None
        with self._lock:
            item = self._items.get(sid)
            if item is None:
                return None
            container = item[0]
            if not container.alive():
                self._items.pop(sid, None)
                return None
            self._items[sid] = (container, time.monotonic())
            return container

    def close(self, sid: Optional[str]) -> bool:
        with self._lock:
            item = self._items.pop(sid, None) if sid else None
        if item:
            item[0].close()
        return item is not None

    def close_all(self) -> None:
        with self._lock:
            items, self._items = list(self._items.values()), {}
        for container, _ in items:
            container.close()

    def reap_idle(self, now: Optional[float] = None) -> int:
        now = time.monotonic() if now is None else now
        with self._lock:
            stale = [k for k, (c, seen) in self._items.items() if now - seen > IDLE_TIMEOUT or not c.alive()]
            victims = [self._items.pop(k)[0] for k in stale]
        for container in victims:
            container.close()
        return len(victims)

    def _ensure_reaper(self) -> None:
        if self._reaper and self._reaper.is_alive():
            return

        def loop() -> None:
            while True:
                time.sleep(30)
                self.reap_idle()

        self._reaper = threading.Thread(target=loop, daemon=True)
        self._reaper.start()


sessions = SessionManager()


def _call(task: str, meta: dict, payload: bytes, session: Optional[SessionContainer]) -> object:
    if session is not None and session.alive():
        return session.call(task, meta, payload)  # a failure here is a refusal, not a reason to retry elsewhere
    return _run(task, meta, payload)  # no session, or its container had already died: a fresh one-shot container


# --------------------------------------------------------------------------- documents

MAX_TEXT_BACK = 30_000  # characters of extracted text accepted from a container
MAX_IMAGE_B64 = 900_000


def analyze_document_full(data: bytes, filename: str, vendor: Optional[str],
                          session: Optional[SessionContainer] = None) -> tuple[DocumentReport, str, Optional[str]]:
    """Returns (report, extracted_text, clean_image_b64). Everything from the container is validated again here."""
    result = _call("document", {"filename": filename[:100], "vendor": vendor}, data, session)
    if not isinstance(result, dict):
        raise SandboxError("invalid output")
    try:
        report = DocumentReport.model_validate(result)  # keys the report does not know (the text, the image) are ignored
    except ValueError:
        raise SandboxError("invalid output") from None
    text = result.get("extracted_text")
    text = text[:MAX_TEXT_BACK] if isinstance(text, str) else ""
    image = result.get("image_b64")
    if not (isinstance(image, str) and len(image) <= MAX_IMAGE_B64 and re.fullmatch(r"[A-Za-z0-9+/=]+", image)):
        image = None
    if image:
        try:
            if base64.b64decode(image, validate=True)[:3] != b"\xff\xd8\xff":  # must be the JPEG we asked for
                image = None
        except ValueError:
            image = None
    report.isolation = "container"
    report.filename = re.sub(r"[\x00-\x1f\x7f/\\]", "", report.filename)[:100]
    if report.content is not None:  # clamp what the container may send back for display
        report.content.excerpt = report.content.excerpt[:600]
        report.content.links = [str(x)[:300] for x in report.content.links[:20]]
        report.content.identifiers = report.content.identifiers[:30]
        report.content.notes = [str(x)[:300] for x in report.content.notes[:10]]
    return report, text, image


def analyze_document(data: bytes, filename: str, vendor: Optional[str],
                     session: Optional[SessionContainer] = None) -> DocumentReport:
    return analyze_document_full(data, filename, vendor, session)[0]


def refused_report(filename: str, size: int) -> DocumentReport:
    """What the user sees when the sandbox could not safely handle a file. Never a fallback parse."""
    return DocumentReport(
        filename=re.sub(r"[\x00-\x1f\x7f/\\]", "", filename)[:100], format="unknown", size_bytes=size,
        signals=[Signal(id="document.sandbox_refused", category=Category.document,
                        finding="This file could not be opened safely in the sandbox, so it was not checked",
                        direction=Direction.unknown, strength=0.0, confidence=1.0)],
        could_not_check=["This file could not be opened safely in the sandbox (it may be damaged, oversized or malformed)"],
        summary="This file could not be opened safely in the sandbox, so nothing was checked. It was not opened outside the sandbox.",
        isolation="container")


# --------------------------------------------------------------------------- email headers

def _s(v, limit: int = 500) -> str:
    return v[:limit] if isinstance(v, str) else ""


def _public_ip(v) -> Optional[str]:
    try:
        addr = ipaddress.ip_address(v) if isinstance(v, str) else None
    except ValueError:
        return None
    return str(addr) if addr is not None and addr.is_global else None


def clean_header_info(d: object) -> HeaderInfo:
    """Re-validate the sandbox's answer field by field. Anything unexpected becomes 'not found'."""
    if not isinstance(d, dict):
        raise SandboxError("invalid output")

    def email(v):
        return v.lower() if isinstance(v, str) and len(v) <= 254 and _EMAIL.fullmatch(v) else None

    def result(v):
        return v if isinstance(v, str) and v in _RESULTS else None

    info = HeaderInfo(
        from_display=_s(d.get("from_display"), 120), from_email=email(d.get("from_email")),
        reply_to_email=email(d.get("reply_to_email")), return_path=email(d.get("return_path")),
        subject=_s(d.get("subject"), 200), spf=result(d.get("spf")), dkim=result(d.get("dkim")),
        dkim_domain=d["dkim_domain"] if isinstance(d.get("dkim_domain"), str) and _DOMAIN.fullmatch(d["dkim_domain"]) else None,
        dmarc=result(d.get("dmarc")), sending_ip=_public_ip(d.get("sending_ip")))
    info.found_anything = any([info.from_email, info.spf, info.dkim, info.dmarc, info.sending_ip, info.reply_to_email])
    return info


def parse_headers(text: str, session: Optional[SessionContainer] = None) -> HeaderInfo:
    return clean_header_info(_call("headers", {}, text.encode("utf-8", "replace"), session))
