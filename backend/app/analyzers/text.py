"""Text analyzer: looks for known social-engineering wording in a message.

This is a transparent rule set (regular expressions), not a model. Each hit
returns the exact phrase so the UI can highlight it. Wording alone is never
proof, so signals carry moderate confidence and the scorer needs several
distinct tactics before it recommends holding an action.
"""
import re
from dataclasses import dataclass

from ..models import Analysis, Band, Category, Direction, Signal

MAX_CHARS = 5000


@dataclass(frozen=True)
class Tactic:
    id: str
    finding: str
    strength: float
    pattern: re.Pattern


def _rx(p: str) -> re.Pattern:
    return re.compile(p, re.IGNORECASE)


TACTICS: list[Tactic] = [
    Tactic("text.urgency", "Creates urgency", 0.6, _rx(
        r"\burgent(ly)?\b|\bimmediately\b|\bright now\b|\basap\b|\bdue today\b|\btoday itself\b|"
        r"\bwithin \d+ (minutes?|hours?)\b|\bbefore (the )?end of (the )?day\b|\bhurry\b|\bno time\b")),
    Tactic("text.secrecy", "Asks the reader to keep it secret", 0.8, _rx(
        r"\b(don'?t|do not|never) (tell|discuss|share|mention|inform)\b[^.!?]{0,40}\b(anyone|anybody|team|family|others|colleagues?)\b|"
        r"\bkeep (this|it) (a )?(secret|confidential|between us|to yourself)\b|\bbetween us\b|\bstrictly confidential\b")),
    Tactic("text.verification_block", "Blocks normal ways of checking (no calls, can't talk)", 0.7, _rx(
        r"\b(can'?t|cannot|unable to) (take|answer|talk|speak|call|pick up)\b[^.!?]{0,20}\b(calls?|phone)?\b|"
        r"\b(don'?t|do not) call\b|\bno calls\b|\bin a meeting\b|\bonly (text|message|whatsapp) me\b")),
    Tactic("text.authority", "Claims authority to pressure the reader", 0.5, _rx(
        r"\bthis is [A-Z][a-z]+ (from|of|at)\b|\b(ceo|cfo|md|director|chairman|manager|boss)\b|"
        r"\b(police|cyber ?crime|customs|rbi|income tax|bank officer|court)\b")),
    Tactic("text.payment_pressure", "Pushes an unusual payment", 0.6, _rx(
        r"\b(transfer|wire|send)\b[^.!?]{0,30}\b(money|amount|rs\.?|inr|₹|\$|funds)|"
        r"\bgift ?cards?\b|\bcrypto(currency)?\b|\bbitcoin\b|\bupi (id|pin)\b|\bnew (bank )?account\b|"
        r"\b(rs\.?|inr|₹)\s?\d[\d,]*")),
    Tactic("text.credential_request", "Asks for a code or password", 0.9, _rx(
        r"\botp\b|\bone[- ]time (password|code)\b|\bverification code\b|\bpassword\b|\bcvv\b|\bpin\b|\bcard number\b")),
    Tactic("text.injection", "Tries to instruct the checking system", 0.9, _rx(
        r"ignore (all |any )?(previous|prior|above|earlier) (instructions?|rules?)|"
        r"mark (this|it) (as )?(safe|legit(imate)?|trusted)|disregard (the )?(rules?|instructions?)|"
        r"you are now\b|system prompt")),
]

PAYMENT_HINT = _rx(r"\b(transfer|payment|pay|wire|invoice|upi|bank|gift ?card|crypto)\b|₹|\brs\.?\s?\d")
URL_HINT = _rx(r"https?://\S+|\bwww\.\S+")
CONFIDENCE = 0.7
# A signal only counts as an independent tactic toward holding an action when we are reasonably
# sure of it. Weak, uncorroborated findings still add a little risk but cannot reach the bar alone.
DISTINCT_MIN_CONFIDENCE = 0.6
TEXT_ONLY_MAX_TRUST = 85

VERIFY_STEPS = [
    "Call the sender on a phone number you already have saved, not a number from this message.",
    "Do not click links in the message; open the organisation's official website yourself.",
    "Confirm any bank account or payee details through a previously known contact.",
    "Ask a question only the real person would know, or request a live video call.",
    "If anything still looks wrong, hold the action and report it (cybercrime helpline 1930, cybercrime.gov.in).",
]


def find_signals(text: str) -> list[Signal]:
    signals: list[Signal] = []
    for t in TACTICS:
        matches = list(t.pattern.finditer(text))
        matches = [m for m in matches if m.group(0).strip()]
        if not matches:
            continue
        signals.append(Signal(
            id=t.id,
            category=Category.text,
            finding=t.finding,
            direction=Direction.suspicious,
            strength=t.strength,
            confidence=CONFIDENCE,
            evidence=", ".join(f"\"{m.group(0).strip()}\"" for m in matches[:3]),
            spans=[(m.start(), m.end()) for m in matches[:5] if m.end() > m.start()],
        ))
    return signals


def analyze_text(text: str) -> Analysis:
    text = text[:MAX_CHARS]
    return score_signals(text, find_signals(text))


def score_signals(text: str, signals: list[Signal]) -> Analysis:
    """Turn text signals (from rules, the reasoning model, or both) into a scored Analysis."""
    signals = list(signals)

    # Injection attempts are a risk signal in themselves and never lower the score.
    tactics = [s for s in signals
               if s.direction == Direction.suspicious and s.id != "text.injection"
               and s.confidence >= DISTINCT_MIN_CONFIDENCE]
    distinct = len(tactics)
    injected = any(s.id == "text.injection" for s in signals)

    if not signals:
        signals.append(Signal(
            id="text.no_known_wording", category=Category.text,
            finding="No known scam wording found", direction=Direction.reassuring,
            strength=0.3, confidence=0.5,
            evidence="Absence of these phrases is weak evidence, not proof of a genuine message"))

    # noisy-OR over suspicious signals
    ok = 1.0
    for s in signals:
        if s.direction == Direction.suspicious:
            ok *= 1 - s.strength * s.confidence
    risk = 1 - ok
    # reassuring signals soften the result a little, but never when the text tried to instruct the checker
    if not injected:
        soft = 1.0
        for s in signals:
            if s.direction == Direction.reassuring:
                soft *= 1 - 0.3 * s.strength * s.confidence
        risk *= soft
    # corroboration: a single tactic is common in genuine messages
    if distinct < 2 and not injected:
        risk = min(risk, 0.3)
    # Most evidence types are unchecked in text-only mode, so never claim full trust.
    trust = min(round(100 * (1 - risk)), TEXT_ONLY_MAX_TRUST)

    impact = 0.7 if PAYMENT_HINT.search(text) else 0.3
    required = round(30 + 60 * impact)
    half_width = 20  # no device, IP, location or link data in text-only mode
    low, high = max(0, trust - half_width), min(100, trust + half_width)

    if trust >= required:
        band = Band.allow
    elif trust >= required - 25:
        band = Band.step_up
    else:
        band = Band.verify

    could_not_check = [
        "Device, IP address and location (not provided in text-only mode)",
        "Whether the sender is who they claim to be",
        "Voice, image or document evidence (none provided)",
    ]
    if URL_HINT.search(text):
        could_not_check.insert(0, "The link in the message (link analysis is not run on free text yet)")

    names = ", ".join(s.finding.lower() for s in tactics)
    if injected:
        summary = "The text tries to instruct the checking system, which is itself a warning sign. It was treated as data and ignored."
    elif distinct >= 3:
        summary = f"Several known pressure tactics appear together ({names}). That combination is common in scams, but wording alone is not proof."
    elif distinct >= 1:
        summary = f"Some pressure wording appears ({names}). That happens in genuine messages too, so treat it as a reason to check."
    else:
        summary = "No known scam wording found. That does not prove the message is genuine, and other evidence was not checked."

    return Analysis(
        scenario_id=None, band=band, trust_score=trust, trust_low=low, trust_high=high,
        required_trust=required, impact=impact, signals=signals, checks=[],
        could_not_check=could_not_check,
        verification_steps=VERIFY_STEPS if band != Band.allow else [],
        summary=summary, is_placeholder=False)
