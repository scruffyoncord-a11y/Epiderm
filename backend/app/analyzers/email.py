"""Sender email check: compare who a message says it is from with the address it came from.

The rules that matter:
- an official-sounding message from a free address (Gmail, Yahoo, ...) is a warning sign;
- an address on a domain we have on record for the company is reassuring, but the address shown
  can be forged, so it never proves anything;
- a domain that only resembles the company's (acmecorp-pay.com) is a strong warning sign;
- Indian government bodies write from gov.in / nic.in, so a "police" or "tax" message from
  anywhere else is a warning sign;
- if the company is not in our directory we say we cannot verify it. Nothing here comes from a
  language model: the directory is curated by people, and a model never supplies official addresses.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from ..models import Category, Direction, OfficialContact, Signal

DIRECTORY_FILE = Path(__file__).resolve().parent.parent / "official_contacts.json"

FREE_PROVIDERS = {
    "gmail.com", "googlemail.com", "yahoo.com", "yahoo.in", "yahoo.co.in", "ymail.com", "outlook.com", "hotmail.com",
    "live.com", "msn.com", "aol.com", "proton.me", "protonmail.com", "icloud.com", "me.com", "rediffmail.com",
    "mail.com", "gmx.com", "yandex.com", "zohomail.in",
}
OFFICIALISH = re.compile(
    r"\b(office|department|dept|bank|support|customer care|helpdesk|officer|police|court|customs|payroll|hr team|"
    r"accounts team|finance team|compliance|kyc|verification team|official)\b", re.I)
IDENTITY_CLAIM = re.compile(
    r"\b(this is|i am|i'm|my name is)\b[^.!?]{0,40}\b(from|at|of|with)\b|\bon behalf of\b|\b(calling|writing|messaging) from\b", re.I)
GOV_CLAIM = re.compile(r"\b(police|cyber ?crime|court|income tax|customs|cbi|enforcement directorate|rbi|reserve bank|"
                       r"government|ministry|tax department)\b", re.I)
EMAIL_RX = re.compile(r"[A-Za-z0-9._%+'-]{1,64}@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")
GOV_SUFFIXES = (".gov.in", ".nic.in", ".gov")
GOV_EXACT = {"rbi.org.in"}


@dataclass
class Org:
    name: str
    aliases: list[str]
    domains: list[str]
    site: str
    kind: str = "company"


@dataclass
class SenderResult:
    signals: list[Signal] = field(default_factory=list)
    org: Optional[Org] = None
    domain: Optional[str] = None


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", " ", s.lower()).strip()


def load_directory(path: Path = DIRECTORY_FILE) -> list[Org]:
    raw = json.loads(path.read_text(encoding="utf8"))
    return [Org(o["name"], [_norm(a) for a in o["aliases"]] + [_norm(o["name"])], [d.lower() for d in o["domains"]],
                o["site"], o.get("kind", "company")) for o in raw["organisations"]]


def find_org(name: Optional[str], directory: list[Org]) -> Optional[Org]:
    """Exact match on a normalised name or alias. No fuzzy guessing: a wrong match would give false comfort."""
    if not name:
        return None
    n = _norm(name)
    n_clean = re.sub(r"\b(pvt|ltd|limited|private|inc|the|bank of)\b", " ", n)
    n_clean = re.sub(r"\s+", " ", n_clean).strip()
    for org in directory:
        if n in org.aliases or n_clean in org.aliases:
            return org
    return None


def find_org_mention(text: str, directory: list[Org]) -> Optional[Org]:
    """A company from our own directory named in the text (whole words). Independent of any language model."""
    hay = f" {_norm(text)} "
    best: tuple[int, Org] | None = None
    for org in directory:
        for alias in org.aliases:
            if len(alias) >= 3 and f" {alias} " in hay and (best is None or len(alias) > best[0]):
                best = (len(alias), org)
    return best[1] if best else None


def parse_email(s: Optional[str]) -> Optional[tuple[str, str]]:
    s = (s or "").strip().strip("<>").strip()
    if not s or len(s) > 254:
        return None
    m = EMAIL_RX.fullmatch(s)
    if not m:
        return None
    local, domain = s.rsplit("@", 1)
    return local, domain.lower().rstrip(".")


def find_addresses(text: str) -> list[str]:
    return list(dict.fromkeys(m.group(0) for m in EMAIL_RX.finditer(text)))[:3]


def _lev(a: str, b: str) -> int:
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


_HOMOGLYPH = str.maketrans({"0": "o", "1": "l", "3": "e", "5": "s", "$": "s"})


def _on_domain(domain: str, official: str) -> bool:
    return domain == official or domain.endswith("." + official)


def _is_lookalike(domain: str, official_domains: list[str]) -> bool:
    label = domain.split(".")[0].translate(_HOMOGLYPH)
    for off in official_domains:
        off_label = off.split(".")[0]
        if label == off_label and domain != off:
            return True  # same name on a different domain / with digits swapped for letters
        if len(off_label) >= 4 and (off_label in label or _lev(label, off_label) <= 2):
            return True
    return False


def _sig(id_, finding, direction, strength, confidence, evidence=""):
    return Signal(id=f"email.{id_}", category=Category.email, finding=finding, direction=direction,
                  strength=strength, confidence=confidence, evidence=evidence)


def is_gov_domain(domain: str) -> bool:
    return domain in GOV_EXACT or domain.endswith(GOV_SUFFIXES)


def official_contact(org: Optional[Org]) -> Optional[OfficialContact]:
    if org is None:
        return None
    return OfficialContact(organisation=org.name, domains=org.domains, site=org.site, kind=org.kind)


def analyze_sender(email: Optional[str], org_name: Optional[str], text: str = "",
                   directory: Optional[list[Org]] = None) -> SenderResult:
    directory = load_directory() if directory is None else directory
    S, R, U = Direction.suspicious, Direction.reassuring, Direction.unknown
    org = find_org(org_name, directory)
    result = SenderResult(org=org)
    if not email or not email.strip():
        return result

    parsed = parse_email(email)
    if parsed is None:
        result.signals.append(_sig("invalid", "That does not look like a valid email address", U, 0.0, 1.0, email.strip()[:80]))
        return result
    _, domain = parsed
    result.domain = domain
    claims_official = bool(org_name) or bool(OFFICIALISH.search(text))
    free = domain in FREE_PROVIDERS

    if free and claims_official:
        who = org.name if org else (org_name or "an organisation")
        result.signals.append(_sig(
            "free_provider", f"The message claims to be from {who}, but was sent from a free email service ({domain})",
            S, 0.6, 0.7, f"Sender: {email.strip()}"))
    elif free:
        result.signals.append(_sig("free_provider_neutral", f"Sent from a free email service ({domain}), which is normal for individuals",
                                   Direction.neutral, 0.0, 0.5, f"Sender: {email.strip()}"))

    if GOV_CLAIM.search(f"{text} {org_name or ''}") and not is_gov_domain(domain) and not (org and org.kind == "government" and any(_on_domain(domain, d) for d in org.domains)):
        result.signals.append(_sig(
            "gov_claim_non_gov", "The message speaks for a government body, but the address is not a government domain (gov.in, nic.in)",
            S, 0.7, 0.7, f"Sender domain: {domain}"))

    if org and not free:
        if any(_on_domain(domain, d) for d in org.domains):
            result.signals.append(_sig(
                "domain_matches_official", f"The address is on a domain we have on record for {org.name} (the shown address can still be forged)",
                R, 0.5, 0.6, f"{domain} is on record for {org.name}"))
        elif _is_lookalike(domain, org.domains):
            result.signals.append(_sig(
                "lookalike_domain", f"The address is on a domain that imitates {org.name}'s", S, 0.8, 0.8,
                f"{domain} vs official {', '.join(org.domains)}"))
        else:
            result.signals.append(_sig(
                "domain_not_official", f"The address is not on any domain we have on record for {org.name}", S, 0.5, 0.6,
                f"{domain} vs official {', '.join(org.domains)}"))
    elif org_name and not org and not free:
        result.signals.append(_sig(
            "org_unknown", f"We have no verified record for \"{org_name[:60]}\", so we cannot compare the address. "
            "Find the company's own website yourself; do not use contact details from the message.",
            U, 0.0, 1.0, f"Sender domain: {domain}"))
    elif org_name and not org and free:
        result.signals.append(_sig(
            "org_unknown", f"We have no verified record for \"{org_name[:60]}\", so we cannot check whether it uses this address.",
            U, 0.0, 1.0, f"Sender domain: {domain}"))
    return result
