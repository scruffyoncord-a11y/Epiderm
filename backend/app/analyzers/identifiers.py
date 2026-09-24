"""Identifiers found inside a document, validated with their own built-in check digits.

A fabricated invoice often carries a made-up GSTIN, PAN, IFSC or IBAN. Real ones have structure and check
digits, so a made-up one usually fails. What this can and cannot say:

- it CAN say an identifier is structurally impossible (bad checksum), which is a strong sign of fabrication;
- it CANNOT say a valid-looking identifier belongs to the named vendor: anyone can compute a valid check
  digit, and checking ownership needs an official registry lookup we do not do. So "valid" is neutral,
  never reassuring.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from ..models import Category, Direction, Signal

_B36 = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
GSTIN_RX = re.compile(r"\b(\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z])\b")
PAN_RX = re.compile(r"\b([A-Z]{5}\d{4}[A-Z])\b")
IFSC_RX = re.compile(r"\b([A-Z]{4}0[A-Z0-9]{6})\b")
IBAN_RX = re.compile(r"\b([A-Z]{2}\d{2}(?: ?[A-Z0-9]{4}){2,7}(?: ?[A-Z0-9]{1,3})?)\b")
UPI_RX = re.compile(r"\b([\w.\-]{2,}@(?:oksbi|okhdfcbank|okicici|okaxis|ybl|paytm|upi|apl|ibl|axl|sbi|hdfcbank|icici|axisbank))\b", re.I)
ACCOUNT_RX = re.compile(r"(?i)\b(?:a/c|acc(?:oun)?t)\s*(?:no\.?|number|#)?\s*[:\-]?\s*(\d{9,18})\b")
VALID_STATE_CODES = {f"{i:02d}" for i in range(1, 39)} | {"97", "99"}
PAN_HOLDER_TYPES = set("ABCFGHLJPT")  # 4th letter: association, company, HUF, firm, ... person, trust


@dataclass
class Found:
    kind: str  # GSTIN | PAN | IFSC | IBAN | UPI | ACCOUNT
    value: str
    valid: Optional[bool]  # None = format only, no check digit to test
    note: str = ""


def gstin_check_char(first14: str) -> str:
    total = 0
    for i, ch in enumerate(first14):
        v = _B36.index(ch) * (1 if i % 2 == 0 else 2)
        total += v // 36 + v % 36
    return _B36[(36 - total % 36) % 36]


def check_gstin(value: str) -> tuple[bool, str]:
    if value[:2] not in VALID_STATE_CODES:
        return False, "the state code is not a real one"
    if not (PAN_RX.fullmatch(value[2:12]) and value[5] in PAN_HOLDER_TYPES):
        return False, "the PAN inside it is malformed"
    if gstin_check_char(value[:14]) != value[14]:
        return False, "the check digit does not match, so this number cannot be genuine"
    return True, "structure and check digit are consistent (this does not show it belongs to this vendor)"


def check_iban(value: str) -> bool:
    v = value.replace(" ", "")
    if not 15 <= len(v) <= 34:
        return False
    rearranged = v[4:] + v[:4]
    digits = "".join(str(int(c, 36)) for c in rearranged)
    return int(digits) % 97 == 1


def mask(value: str) -> str:
    return "*" * max(0, len(value) - 4) + value[-4:]


def find_identifiers(text: str) -> list[Found]:
    out: list[Found] = []
    seen: set[tuple[str, str]] = set()

    def add(f: Found) -> None:
        key = (f.kind, f.value)
        if key not in seen and len(out) < 30:
            seen.add(key)
            out.append(f)

    gstins = []
    for m in GSTIN_RX.finditer(text):
        ok, why = check_gstin(m.group(1))
        gstins.append(m.group(1))
        add(Found("GSTIN", m.group(1), ok, why))
    embedded_pans = {g[2:12] for g in gstins}
    for m in PAN_RX.finditer(text):
        v = m.group(1)
        if v in embedded_pans:
            continue
        ok = v[3] in PAN_HOLDER_TYPES
        add(Found("PAN", v, ok, "format is valid" if ok else "the 4th letter is not a valid holder type"))
    for m in IFSC_RX.finditer(text):
        add(Found("IFSC", m.group(1), None, "format is valid (the branch itself is not checked)"))
    for m in IBAN_RX.finditer(text):
        ok = check_iban(m.group(1))
        if ok or re.search(r"(?i)iban", text[max(0, m.start() - 20):m.start()]):
            add(Found("IBAN", m.group(1), ok, "check digits pass" if ok else "the check digits fail, so this number cannot be genuine"))
    for m in UPI_RX.finditer(text):
        add(Found("UPI", m.group(1), None, "a payment address (whether it belongs to this vendor is not checked)"))
    for m in ACCOUNT_RX.finditer(text):
        add(Found("ACCOUNT", mask(m.group(1)), None, "shown masked; whether it belongs to this vendor is not checked"))
    return out


def identifier_signals(found: list[Found]) -> list[Signal]:
    S = Direction.suspicious
    out: list[Signal] = []
    for f in found:
        if f.valid is False:
            strength = {"GSTIN": 0.75, "IBAN": 0.75, "PAN": 0.5}.get(f.kind, 0.4)
            out.append(Signal(
                id=f"content.invalid_{f.kind.lower()}", category=Category.document,
                finding=f"A {f.kind} in the document is impossible: {f.note}", direction=S,
                strength=strength, confidence=0.85, evidence=f"{f.kind}: {f.value}"))
    return out
