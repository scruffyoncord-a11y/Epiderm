import asyncio
import json
import os
import queue
import threading
from typing import Optional
from pathlib import Path

from fastapi import FastAPI, File, Form, Header, HTTPException, Response, UploadFile
from pydantic import BaseModel, Field
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from . import documents, report, risk, sandbox
from .analyzers.document import MAX_BYTES, analyze_document
from .analyzers.headers import HeaderInfo
from .models import Analysis, DocumentReport, EmailResult, Category, Direction, Scenario, Signal
from .analyzers.text import MAX_CHARS
from .reasoning import analyze_with_reasoning, provider_config
from .placeholder import placeholder_analysis

ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


def load_env_file(path: Path = ENV_FILE) -> None:
    """Minimal .env reader: KEY=VALUE lines, existing environment variables win. Values are never logged."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip().strip('"').strip("'")
        if k and k not in os.environ:
            os.environ[k] = v


load_env_file()

SCENARIO_DIR = Path(__file__).resolve().parent.parent / "scenarios"

app = FastAPI(title="Epiderm API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def load_scenarios() -> dict[str, Scenario]:
    out: dict[str, Scenario] = {}
    for path in sorted(SCENARIO_DIR.glob("*.json")):
        sc = Scenario.model_validate_json(path.read_text(encoding="utf-8"))
        out[sc.id] = sc
    return out


@app.get("/health")
def health():
    return {"status": "ok", "scenarios": len(load_scenarios())}


@app.get("/scenarios")
def list_scenarios():
    return [
        {"id": s.id, "title": s.title, "description": s.description, "simulated": s.simulated}
        for s in load_scenarios().values()
    ]


@app.get("/scenarios/{scenario_id}")
def get_scenario(scenario_id: str):
    sc = load_scenarios().get(scenario_id)
    if sc is None:
        raise HTTPException(404, "unknown scenario")
    return sc


@app.get("/demo-signal")
def demo_signal() -> Signal:
    """Placeholder signal used to prove the backend-to-frontend contract works."""
    return Signal(
        id="demo.contract_check",
        category=Category.url,
        finding="Example finding: domain is one character away from the official domain",
        direction=Direction.suspicious,
        strength=0.8,
        confidence=0.9,
        evidence="acmecorp-pay.com vs acmecorp.com",
    )


@app.post("/analyze/{scenario_id}")
def analyze(scenario_id: str) -> Analysis:
    """Placeholder until the real engine exists: returns hand-written results, flagged is_placeholder."""
    sc = load_scenarios().get(scenario_id)
    if sc is None:
        raise HTTPException(404, "unknown scenario")
    return placeholder_analysis(sc)


class TextRequest(BaseModel):
    text: str = Field(default="", max_length=MAX_CHARS)
    headers: Optional[str] = Field(default=None, max_length=60_000, description="Pasted email headers or Gmail Show-original summary")
    sender_email: Optional[str] = Field(default=None, max_length=254, description="Address the message came from, if known")
    organisation: Optional[str] = Field(default=None, max_length=120, description="Company the sender claims to be from, if known")


def _validate_text_request(req: TextRequest) -> tuple[bool, bool]:
    """Returns (has_headers, in_container). Problems are ordinary HTTP errors, raised before any streaming starts."""
    has_headers = bool(req.headers and req.headers.strip())
    if not req.text.strip() and not has_headers:
        raise HTTPException(422, "give the message text, the email headers, or both")
    in_container = False
    if has_headers:
        try:
            in_container = sandbox.mode() == "container"
        except sandbox.SandboxUnavailable as exc:
            raise HTTPException(503, str(exc)) from None
    return has_headers, in_container


def _run_text_analysis(req: TextRequest, session_id: Optional[str], in_container: bool, progress=None) -> Analysis:
    header_info, isolation = None, "none"
    if req.headers and req.headers.strip() and in_container:
        isolation = "container"
        if progress:
            progress("container")
        try:
            header_info = sandbox.parse_headers(req.headers, sandbox.sessions.get(session_id))
        except sandbox.SandboxError:
            header_info = HeaderInfo()  # fail closed: never parse untrusted headers in this process
    analysis = analyze_with_reasoning(req.text, sender_email=req.sender_email, organisation=req.organisation,
                                      use_cache=True, headers=req.headers, header_info=header_info, progress=progress)
    analysis.isolation = isolation
    analysis.risk = risk.summarise(analysis.signals, analysis.band, "message")
    return analysis


@app.post("/analyze-text")
def analyze_free_text(req: TextRequest, x_session_id: Optional[str] = Header(default=None)) -> Analysis:
    """Free-text analysis: reasoning model first (when configured), then the rule-based check, then scoring.
    Text-only: no device, IP or link data."""
    _, in_container = _validate_text_request(req)
    return _run_text_analysis(req, x_session_id, in_container)


def _ndjson_stream(fn) -> StreamingResponse:
    """Runs fn(progress) in a thread and reports it as newline-delimited JSON events.

    Events: {"stage": "started" | "container" | "reading" | "verifying"} as each real stage begins, then
    {"stage": "done", "result": <result>} or {"stage": "error", "detail": "..."}. Stages that do not apply
    (no headers, no model) are simply never sent."""
    events: "queue.Queue[Optional[dict]]" = queue.Queue()

    def work() -> None:
        try:
            events.put({"stage": "started"})
            result = fn(lambda stage: events.put({"stage": stage}))
            events.put({"stage": "done", "result": result.model_dump(mode="json")})
        except Exception:  # nothing internal is echoed to the user
            events.put({"stage": "error", "detail": "The check failed."})
        finally:
            events.put(None)

    threading.Thread(target=work, daemon=True).start()

    def stream():
        while True:
            item = events.get()
            if item is None:
                return
            yield json.dumps(item) + "\n"

    return StreamingResponse(stream(), media_type="application/x-ndjson",
                             headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})


@app.post("/analyze-text/stream")
def analyze_free_text_stream(req: TextRequest, x_session_id: Optional[str] = Header(default=None)) -> StreamingResponse:
    """The same analysis as /analyze-text, reported as it happens."""
    _, in_container = _validate_text_request(req)
    return _ndjson_stream(lambda progress: _run_text_analysis(req, x_session_id, in_container, progress))


@app.get("/config")
def config():
    """Lets the UI tell the user honestly whether their text will be sent to a reasoning model."""
    return {**provider_config(), "sandbox": sandbox.status()}


async def _read_upload(file: UploadFile, vendor: Optional[str]) -> tuple[bytes, str, Optional[str]]:
    """Reads an upload into memory (never to disk) and applies the size limits. Problems are ordinary HTTP errors."""
    data = await file.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise HTTPException(413, f"File is larger than {MAX_BYTES // (1024 * 1024)} MB")
    if not data:
        raise HTTPException(422, "File is empty")
    try:
        sandbox.mode()  # raises when the sandbox is required but missing
    except sandbox.SandboxUnavailable as exc:
        raise HTTPException(503, str(exc)) from None
    return data, file.filename or "", (vendor or "").strip()[:120] or None


@app.post("/analyze-document")
async def analyze_document_upload(file: UploadFile = File(...), vendor: Optional[str] = Form(default=None),
                                  x_session_id: Optional[str] = Header(default=None)) -> DocumentReport:
    """Reads a file's metadata AND contents (in the sandbox), lets the reasoning model read the contents, verifies
    what it says, and returns one result. The file is processed in memory and never stored."""
    data, filename, vendor = await _read_upload(file, vendor)
    return await asyncio.to_thread(documents.run_document_analysis, data, filename, vendor, x_session_id)


@app.post("/analyze-document/stream")
async def analyze_document_stream(file: UploadFile = File(...), vendor: Optional[str] = Form(default=None),
                                  x_session_id: Optional[str] = Header(default=None)) -> StreamingResponse:
    """The same as /analyze-document, reported stage by stage (see _ndjson_stream)."""
    data, filename, vendor = await _read_upload(file, vendor)
    return _ndjson_stream(lambda progress: documents.run_document_analysis(data, filename, vendor, x_session_id, progress))


@app.post("/sessions")
def open_session():
    """Opens this person's private container. Called when they pick a category; takes a second or two."""
    try:
        in_container = sandbox.mode() == "container"
    except sandbox.SandboxUnavailable as exc:
        raise HTTPException(503, str(exc)) from None
    if not in_container:
        return {"session_id": None, "isolation": "none"}
    try:
        sid = sandbox.sessions.open()
    except sandbox.SandboxError:
        if sandbox.status()["setting"] == "docker":
            raise HTTPException(503, "The private container could not be opened.") from None
        return {"session_id": None, "isolation": "none"}
    return {"session_id": sid, "isolation": "container"}


@app.post("/sessions/{session_id}/close", status_code=204)
def close_session(session_id: str) -> Response:
    """Deletes the container. Also called by the browser as the tab closes, so it is a POST (works with sendBeacon)."""
    sandbox.sessions.close(session_id)
    return Response(status_code=204)


@app.post("/analyze-email/stream")
async def analyze_email_stream(
    text: str = Form(default="", max_length=MAX_CHARS),
    headers: Optional[str] = Form(default=None, max_length=60_000),
    sender_email: Optional[str] = Form(default=None, max_length=254),
    organisation: Optional[str] = Form(default=None, max_length=120),
    file: Optional[UploadFile] = File(default=None),
    x_session_id: Optional[str] = Header(default=None),
) -> StreamingResponse:
    """A message and its attachment checked together, each by its own pipeline, reported stage by stage.

    Message stages are as for /analyze-text/stream; the attachment's are the same names prefixed with
    "attachment_". The result is an EmailResult with one combined risk summary (the worst verdict wins)."""
    has_file = file is not None and bool(file.filename)
    req = TextRequest(text=text, headers=headers or None, sender_email=sender_email or None, organisation=organisation or None)
    has_message = bool(req.text.strip() or (req.headers and req.headers.strip()))
    if not has_message and not has_file:
        raise HTTPException(422, "give the message, the email headers, or an attachment")
    in_container = _validate_text_request(req)[1] if has_message else False
    upload = await _read_upload(file, organisation) if has_file else None

    def run(progress) -> EmailResult:
        message = _run_text_analysis(req, x_session_id, in_container, progress) if has_message else None
        attachment = None
        if upload is not None:
            data, filename, vendor = upload
            progress("attachment")
            attachment = documents.run_document_analysis(data, filename, vendor, x_session_id,
                                                         lambda stage: progress(f"attachment_{stage}"))
        parts = []
        if message is not None:
            parts.append(("Message", message.risk))
        if attachment is not None:
            parts.append((f"Attachment: {attachment.filename or 'file'}", attachment.risk))
        return EmailResult(message=message, attachment=attachment, risk=risk.combine(parts))

    return _ndjson_stream(run)


@app.post("/report")
def make_report(result: EmailResult) -> Response:
    """Turns a finished result (the JSON the screen already has) into a PDF. Generated in memory, never stored."""
    if result.message is None and result.attachment is None:
        raise HTTPException(422, "nothing to report")
    if result.risk is None:  # a single document result sent on its own
        parts = []
        if result.message is not None:
            parts.append(("Message", result.message.risk))
        if result.attachment is not None:
            parts.append((f"Attachment: {result.attachment.filename or 'file'}", result.attachment.risk))
        result = result.model_copy(update={"risk": risk.combine(parts)})
    try:
        pdf = report.build_pdf(result)
    except Exception:
        raise HTTPException(500, "The report could not be built.") from None
    return Response(pdf, media_type="application/pdf",
                    headers={"Content-Disposition": 'attachment; filename="epiderm-report.pdf"', "Cache-Control": "no-store"})
