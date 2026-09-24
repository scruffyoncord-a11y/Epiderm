"""Runs INSIDE the sandbox container.

Two modes:

  one-shot   `python -m app.worker document|headers`
             stdin: one JSON line (task metadata) then the untrusted payload; stdout: one JSON object.

  serve      `python -m app.worker serve`
             A private container that stays open for one user's session. It answers framed requests until
             its input closes. Frame formats (big-endian):
               request:  u32 len(meta_json) | meta_json | u64 len(payload) | payload
               response: u32 len(json) | json   ({"ok": true, "result": ...} or {"ok": false, "error": "failed"})
             meta_json is {"task": "document"|"headers", ...}. A {"ready": true} frame is sent first.

The container has no network and a read-only filesystem, and it is deleted when the session ends.
Only parsing lives here (files and email headers). Network lookups and the language model stay in the
main server, which treats this module's output as data and validates it again.
"""
from __future__ import annotations

import dataclasses
import json
import struct
import sys

MAX_INPUT = 11 * 1024 * 1024  # 10 MB file + a small envelope
MAX_META = 64 * 1024


def _fail(message: str) -> None:
    sys.stderr.write(message)
    raise SystemExit(2)


def handle(task: str, meta: dict, payload: bytes):
    """Runs one task and returns a JSON-serialisable result. Stateless: nothing is kept between calls."""
    if task == "document":
        from .analyzers.content import analyze_full

        report, text, image_b64 = analyze_full(payload, str(meta.get("filename", ""))[:100], (meta.get("vendor") or None))
        # extra keys travel beside the report: the text and a clean copy of an image, for the reading model
        return {**json.loads(report.model_dump_json()), "extracted_text": text, "image_b64": image_b64}
    if task == "headers":
        from .analyzers.headers import parse_headers

        return dataclasses.asdict(parse_headers(payload.decode("utf-8", "replace")))
    raise ValueError("unknown task")


# ------------------------------------------------------------------ one-shot mode

def one_shot(task: str) -> None:
    raw = sys.stdin.buffer.read(MAX_INPUT + 1)
    if len(raw) > MAX_INPUT:
        _fail("input too large")
    meta_line, _, payload = raw.partition(b"\n")
    try:
        meta = json.loads(meta_line or b"{}")
    except ValueError:
        _fail("bad metadata")
        return
    sys.stdout.write(json.dumps(handle(task, meta, payload)))


# ------------------------------------------------------------------ serve mode

def _read_exact(stream, n: int):
    buf = bytearray()
    while len(buf) < n:
        chunk = stream.read(n - len(buf))
        if not chunk:
            return None
        buf.extend(chunk)
    return bytes(buf)


def _write_frame(obj) -> None:
    data = json.dumps(obj).encode("utf-8")
    out = sys.stdout.buffer
    out.write(struct.pack(">I", len(data)) + data)
    out.flush()


def serve() -> None:
    # Import the parsers once so each request in the session is fast.
    from .analyzers import content, document, headers  # noqa: F401

    _write_frame({"ready": True})
    stdin = sys.stdin.buffer
    while True:
        head = _read_exact(stdin, 4)
        if head is None:
            return  # the host closed the session
        (mlen,) = struct.unpack(">I", head)
        if mlen > MAX_META:
            return  # cannot resynchronise safely: end the session
        meta_raw = _read_exact(stdin, mlen)
        plen_raw = _read_exact(stdin, 8)
        if meta_raw is None or plen_raw is None:
            return
        (plen,) = struct.unpack(">Q", plen_raw)
        if plen > MAX_INPUT:
            _write_frame({"ok": False, "error": "failed"})
            return
        payload = _read_exact(stdin, plen)
        if payload is None:
            return
        try:
            meta = json.loads(meta_raw)
            result = handle(str(meta.get("task", "")), meta, payload)
            _write_frame({"ok": True, "result": result})
        except Exception:  # never let one bad file end the session or leak details
            _write_frame({"ok": False, "error": "failed"})


def main(argv: list[str]) -> None:
    if len(argv) != 2 or argv[1] not in ("document", "headers", "serve"):
        _fail("usage: python -m app.worker document|headers|serve")
    if argv[1] == "serve":
        serve()
    else:
        one_shot(argv[1])


if __name__ == "__main__":
    main(sys.argv)
