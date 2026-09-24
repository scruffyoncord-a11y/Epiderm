import json
import os
from typing import Optional
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field
from fastapi.middleware.cors import CORSMiddleware

from .analyzers.document import MAX_BYTES, analyze_document
from .models import Analysis, DocumentReport, Category, Direction, Scenario, Signal
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

app = FastAPI(title="TrustGuard API", version="0.1.0")
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


@app.post("/analyze-text")
def analyze_free_text(req: TextRequest) -> Analysis:
    """Free-text analysis: reasoning model first (when configured), then the rule-based check, then scoring.
    Text-only: no device, IP or link data."""
    if not req.text.strip() and not (req.headers and req.headers.strip()):
        raise HTTPException(422, "give the message text, the email headers, or both")
    return analyze_with_reasoning(req.text, sender_email=req.sender_email,
                                 organisation=req.organisation, use_cache=True, headers=req.headers)


@app.get("/config")
def config():
    """Lets the UI tell the user honestly whether their text will be sent to a reasoning model."""
    return provider_config()


@app.post("/analyze-document")
async def analyze_document_upload(file: UploadFile = File(...), vendor: Optional[str] = Form(default=None)) -> DocumentReport:
    """Read a file's metadata and flag what looks unusual. The file is processed in memory and never stored."""
    data = await file.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise HTTPException(413, f"File is larger than {MAX_BYTES // (1024 * 1024)} MB")
    if not data:
        raise HTTPException(422, "File is empty")
    vendor = (vendor or "").strip()[:120] or None
    return analyze_document(data, file.filename or "", vendor)
