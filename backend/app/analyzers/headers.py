"""Email header analyzer: reads what pasted headers say about where a message really came from.

Accepts either Gmail's "Show original" summary block (SPF / DKIM / DMARC lines with the sending IP)
or the full raw headers (Authentication-Results, Received-SPF, Received chain).

What matters, and its limits:
- SPF, DKIM and DMARC are the receiving mail service's own verdict on whether the sender was allowed to
  send for that domain. A failure is a strong sign of a forged sender. A pass is only mildly reassuring:
  a scammer's own lookalike domain passes for itself.
- Reply-To pointing somewhere other than the From address is a classic impersonation tell.
- The sending IP is a mail server, not a person. Its reverse DNS is judged by mail rules (see ip.py).
- Only the fields we need are returned. The recipient's own address and the full header text are never
  echoed or stored.
"""
from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass
from typing import Optional

from ..models import Category, Direction, Signal
from .email import EMAIL_RX

MAX_HEADER_CHARS = 60_000
RESULT = r"(pass|fail|softfail|neutral|none|temperror|permerror|bestguesspass|policy)"
_TWO_LEVEL = {"co", "com", "org", "net", "gov", "ac", "nic", "edu", "ltd"}


@dataclass
class HeaderInfo:
    from_display: str = ""
    from_email: Optional[str] = None
    reply_to_email: Optional[str] = None
    return_path: Optional[str] = None
    subject: str = ""
    spf: Optional[str] = None
    dkim: Optional[str] = None
    dkim_domain: Optional[str] = None
    dmarc: Optional[str] = None
    sending_ip: Optional[str] = None
    found_anything: bool = False


def _decode_words(value: str) -> str:
    """Decode RFC 2047 encoded words such as =?utf-8?q?Hello_World?= into readable text."""
    from email.header import decode_header, make_header
    try:
        return str(make_header(decode_header(value)))
    except Exception:
        return value


def _line(text: str, name: str) -> Optional[str]:
    m = re.search(rf"(?im)^{name}:[ \t]*(.+)$", text)
    return m.group(1).strip()[:500] if m else None


def parse_address(value: Optional[str]) -> tuple[str, Optional[str]]:
    """'Display Name <a@b.com> Using Foo' -> ('Display Name', 'a@b.com')."""
    if not value:
        return "", None
    m = re.search(r"<([^<>\s]+@[^<>\s]+)>", value)
    if m:
        return value[:m.start()].strip().strip('"').strip()[:120], m.group(1).lower()
    m = EMAIL_RX.search(value)
    return "", (m.group(0).lower() if m else None)


def _public_ip(candidate: Optional[str]) -> Optional[str]:
    if not candidate:
        return None
    try:
        addr = ipaddress.ip_address(candidate.strip("[]"))
    except ValueError:
        return None
    return str(addr) if addr.is_global else None


def _first(text: str, pattern: str, group: int = 1) -> Optional[str]:
    m = re.search(pattern, text, re.I)
    return m.group(group) if m else None


def parse_headers(raw: str) -> HeaderInfo:
    text = (raw or "")[:MAX_HEADER_CHARS]
    text = re.sub(r"\r\n?", "\n", text)
    text = re.sub(r"\n[ \t]+", " ", text)  # unfold wrapped header lines
    info = HeaderInfo()

    info.from_display, info.from_email = parse_address(_line(text, "from"))
    info.reply_to_email = parse_address(_line(text, "reply-to"))[1]
    rp = _line(text, "return-path")
    info.return_path = parse_address(rp)[1] if rp else None
    info.subject = _decode_words(_line(text, "subject") or "")[:200]

    # Gmail "Show original" summary lines first, then the raw Authentication-Results header.
    info.spf = (_first(text, rf"(?im)^spf:[ \t]*'?{RESULT}'?") or _first(text, rf"\bspf={RESULT}") or "").lower() or None
    info.dkim = (_first(text, rf"(?im)^dkim:[ \t]*'?{RESULT}'?") or _first(text, rf"\bdkim={RESULT}") or "").lower() or None
    info.dmarc = (_first(text, rf"(?im)^dmarc:[ \t]*'?{RESULT}'?") or _first(text, rf"\bdmarc={RESULT}") or "").lower() or None
    info.dkim_domain = _first(text, r"(?im)^dkim:[^\n]*?with domain[ \t]+([A-Za-z0-9.-]+)") or _first(text, r"\bheader\.[di]=@?([A-Za-z0-9.-]+)")

    ip = (_public_ip(_first(text, r"(?im)^spf:[^\n]*?with IP[ \t]+([0-9a-f:.]+)"))
          or _public_ip(_first(text, r"designates[ \t]+([0-9a-f:.]+)[ \t]+as permitted sender"))
          or _public_ip(_first(text, r"client-ip=([0-9a-f:.]+)"))
          or _public_ip(_first(text, r"(?im)^x-originating-ip:[ \t]*\[?([0-9a-f:.]+)\]?")))
    if not ip:
        received = re.findall(r"(?im)^received:[ \t]*(.+)$", text)
        for line in reversed(received):  # the earliest hop is the last Received header
            for cand in re.findall(r"\[(?:IPv6:)?([0-9a-fA-F:.]+)\]", line):
                ip = _public_ip(cand)
                if ip:
                    break
            if ip:
                break
    info.sending_ip = ip
    info.found_anything = any([info.from_email, info.spf, info.dkim, info.dmarc, info.sending_ip, info.reply_to_email])
    return info


def _sig(id_, finding, direction, strength, confidence, evidence=""):
    return Signal(id=f"email.{id_}", category=Category.email, finding=finding, direction=direction,
                  strength=strength, confidence=confidence, evidence=evidence)


def _org_domain(domain: str) -> str:
    parts = domain.lower().split(".")
    if len(parts) >= 3 and len(parts[-1]) == 2 and parts[-2] in _TWO_LEVEL:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def same_organisation(a: str, b: str) -> bool:
    return _org_domain(a) == _org_domain(b)


def header_signals(info: HeaderInfo) -> list[Signal]:
    S, R, U = Direction.suspicious, Direction.reassuring, Direction.unknown
    out: list[Signal] = []
    if not info.found_anything:
        return [_sig("headers_unreadable", "No email header fields could be read from what was pasted", U, 0.0, 1.0)]

    results = {"SPF": info.spf, "DKIM": info.dkim, "DMARC": info.dmarc}
    if not any(results.values()):
        out.append(_sig("auth_missing", "No SPF, DKIM or DMARC results were found, so the sender could not be authenticated from this text",
                        U, 0.0, 1.0))
    else:
        weights = {"DMARC": (0.8, 0.8), "SPF": (0.6, 0.7), "DKIM": (0.6, 0.7)}
        for name, res in results.items():
            if res in ("fail", "permerror"):
                s, c = weights[name]
                out.append(_sig(f"{name.lower()}_fail", f"{name} failed: the sender was not authorised to send for that domain",
                                S, s, c, f"{name}: {res}"))
            elif res == "softfail":
                out.append(_sig(f"{name.lower()}_softfail", f"{name} soft-failed: the domain says this sender is probably not authorised",
                                S, 0.4, 0.6, f"{name}: softfail"))
            elif res in ("none", "neutral"):
                out.append(_sig(f"{name.lower()}_none", f"{name} gave no verdict for this message", S, 0.2, 0.5, f"{name}: {res}"))
        if all(results[k] in ("pass", "bestguesspass") for k in results):
            out.append(_sig("auth_pass", "SPF, DKIM and DMARC all passed: the message really came from a server allowed to send for its domain. "
                            "This does not show the content is honest, since a scammer's own domain also passes.",
                            R, 0.4, 0.6, f"Sending domain: {info.dkim_domain or (info.from_email or '').split('@')[-1]}"))

    if info.from_email and info.reply_to_email:
        f_dom, r_dom = info.from_email.split("@")[-1], info.reply_to_email.split("@")[-1]
        if not same_organisation(f_dom, r_dom):
            from .email import FREE_PROVIDERS
            free_reply = r_dom in FREE_PROVIDERS and f_dom not in FREE_PROVIDERS
            out.append(_sig(
                "reply_to_mismatch",
                "Replies would go to a different address than the one it was sent from" + (", and that address is a free email account" if free_reply else ""),
                S, 0.7 if free_reply else 0.5, 0.7 if free_reply else 0.6,
                f"From {f_dom}; replies go to {info.reply_to_email}"))
    return out
