"""One structured call to whichever reasoning model is configured, optionally with an image.

Used for reading documents. (Message reading has its own path in reasoning.py.) The caller passes a
pydantic model; the answer is validated against it, and anything that does not validate is treated as
"the model could not be used". The model's output is data: callers verify it before relying on it.
"""
from __future__ import annotations

import json
from typing import Optional, Type, TypeVar

import requests
from pydantic import BaseModel

from . import reasoning as rz

T = TypeVar("T", bound=BaseModel)
OLLAMA_TIMEOUT = 300
DOC_CONTEXT = 8192  # tokens: room for ~20k characters of document text plus the answer


def _inline_schema(model: Type[BaseModel]) -> dict:
    """The JSON schema with $refs inlined and cosmetic keys removed (what Gemini's structured output accepts)."""
    schema = model.model_json_schema()
    defs = schema.pop("$defs", {})

    def walk(node):
        if isinstance(node, dict):
            if "$ref" in node:
                return walk(defs[node["$ref"].split("/")[-1]])
            return {k: walk(v) for k, v in node.items() if k not in ("title", "default")}
        if isinstance(node, list):
            return [walk(x) for x in node]
        return node

    return walk(schema)


def _ollama(model_cls: Type[T], system: str, user: str, image_b64: Optional[str]) -> tuple[Optional[T], str]:
    message: dict = {"role": "user", "content": user}
    if image_b64:
        message["images"] = [image_b64]
    body = {
        "model": rz.local_model_name(), "stream": False, "keep_alive": "30m",
        "messages": [{"role": "system", "content": system}, message],
        "format": model_cls.model_json_schema(),
        "options": {"temperature": 0, "num_ctx": DOC_CONTEXT},
    }
    r = requests.post(f"{rz.OLLAMA_URL}/api/chat", json=body, timeout=OLLAMA_TIMEOUT)
    r.raise_for_status()
    raw = r.json().get("message", {}).get("content", "")
    try:
        return model_cls.model_validate_json(raw), ""
    except Exception:
        return None, "The local model's answer did not match the expected format."


def _gemini(model_cls: Type[T], system: str, user: str, image_b64: Optional[str]) -> tuple[Optional[T], str]:
    parts: list[dict] = [{"text": user}]
    if image_b64:
        parts.append({"inline_data": {"mime_type": "image/jpeg", "data": image_b64}})
    body = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": {"temperature": 0, "responseMimeType": "application/json", "responseJsonSchema": _inline_schema(model_cls)},
    }
    r = requests.post(f"{rz.GEMINI_URL}/v1beta/models/{rz.gemini_model_name()}:generateContent", json=body,
                      headers={"x-goog-api-key": rz._gemini_key()}, timeout=120)
    r.raise_for_status()
    data = r.json()
    if data.get("promptFeedback", {}).get("blockReason"):
        return None, "Gemini declined to read this document."
    cand = (data.get("candidates") or [{}])[0]
    if cand.get("finishReason") not in (None, "STOP"):
        return None, "Gemini did not finish its answer."
    raw = "".join(p.get("text", "") for p in cand.get("content", {}).get("parts", []))
    try:
        return model_cls.model_validate_json(raw), ""
    except Exception:
        return None, "Gemini's answer did not match the expected format."


def _anthropic(model_cls: Type[T], system: str, user: str, image_b64: Optional[str]) -> tuple[Optional[T], str]:
    client = rz.get_client()
    content: list[dict] = []
    if image_b64:
        content.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": image_b64}})
    content.append({"type": "text", "text": user})
    response = client.messages.parse(model=rz.model_name(), max_tokens=4000, system=system,
                                     messages=[{"role": "user", "content": content}], output_format=model_cls)
    if getattr(response, "stop_reason", None) == "refusal":
        return None, "The reasoning model declined to read this document."
    parsed = getattr(response, "parsed_output", None)
    return (parsed, "") if parsed is not None else (None, "The reasoning model returned no usable result.")


def ask_structured(model_cls: Type[T], system: str, user: str, provider: Optional[str],
                   image_b64: Optional[str] = None) -> tuple[Optional[T], str]:
    """Returns (answer, note). answer is None when the model could not be used; the caller falls back to rules only."""
    if provider == "ollama":
        return _ollama(model_cls, system, user, image_b64)
    if provider == "gemini":
        return _gemini(model_cls, system, user, image_b64)
    if provider == "anthropic":
        return _anthropic(model_cls, system, user, image_b64)
    return None, "No reasoning model is available."
