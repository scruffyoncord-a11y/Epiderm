"""Reads the CONTENTS of a document: text from PDFs and Office files, a sanitised copy of an image, and
content-level checks that need no AI (identifier check digits, hidden text, pressure wording).

Runs inside the sandbox container together with the metadata reader, because it parses untrusted files.
Everything it returns is plain data (strings, lists, numbers) that the main server validates again.
"""
from __future__ import annotations

import base64
import datetime as dt
import io
import re
import warnings
import zipfile
from dataclasses import dataclass, field
from typing import Optional

import defusedxml.ElementTree as ET

from ..models import Category, ContentReport, Direction, Identifier, Signal
from .document import MAX_PART, MAX_UNCOMPRESSED, _read_part
from .identifiers import find_identifiers, identifier_signals
from .text import find_signals

MAX_TEXT = 20_000  # characters kept for reading
MAX_PDF_PAGES = 25
MAX_SHEET_CELLS = 3_000
MAX_LINKS = 20
IMAGE_MAX_SIDE = 1024
IMAGE_MAX_BYTES = 600_000
MAX_PIXELS = 50_000_000

_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


@dataclass
class Extracted:
    text: str = ""
    pages: Optional[int] = None
    truncated: bool = False
    links: list[str] = field(default_factory=list)
    image_b64: Optional[str] = None  # a clean, re-encoded copy for a vision model
    hidden_text: int = 0  # runs of text the document hides from view
    hidden_sheets: int = 0
    notes: list[str] = field(default_factory=list)


def sanitise(text: str) -> str:
    t = _CTRL.sub(" ", text)
    t = re.sub(r"[ \t ]+", " ", t)
    t = re.sub(r" ?\n ?", "\n", t)
    return re.sub(r"\n{3,}", "\n\n", t).strip()


def _cap(parts: list[str], ex: Extracted) -> str:
    joined = sanitise("\n".join(parts))
    if len(joined) > MAX_TEXT:
        ex.truncated = True
        return joined[:MAX_TEXT]
    return joined


# ---------------------------------------------------------------------------------------- PDF

def _pdf(data: bytes, ex: Extracted) -> None:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data), strict=False)
    if reader.is_encrypted:
        try:
            if not reader.decrypt(""):
                ex.notes.append("The PDF is password-protected, so its contents could not be read.")
                return
        except Exception:
            ex.notes.append("The PDF is password-protected, so its contents could not be read.")
            return
    ex.pages = len(reader.pages)
    parts: list[str] = []
    size = 0
    for i, page in enumerate(reader.pages):
        if i >= MAX_PDF_PAGES or size > MAX_TEXT:
            ex.truncated = True
            break
        try:
            chunk = page.extract_text() or ""
        except Exception:
            chunk = ""
        parts.append(chunk)
        size += len(chunk)
        try:
            for annot in page.get("/Annots") or []:
                obj = annot.get_object()
                uri = (obj.get("/A") or {}).get("/URI") if hasattr(obj, "get") else None
                if uri and len(ex.links) < MAX_LINKS:
                    ex.links.append(str(uri)[:300])
        except Exception:
            pass
    ex.text = _cap(parts, ex)
    if not ex.text:
        ex.notes.append("The PDF has no selectable text (it may be a scan or a picture), so its contents could not be read.")


# ---------------------------------------------------------------------------------------- Office

def _walk_text(root, para_tag: str, text_tag: str, ex: Extracted, hidden_tag: Optional[str] = None) -> list[str]:
    """Paragraph texts from an OOXML part. Text a document hides from view is kept and counted."""
    paras: list[str] = []
    for p in root.iter():
        if not p.tag.endswith("}" + para_tag):
            continue
        pieces: list[str] = []
        for r in p.iter():
            if r.tag.endswith("}" + text_tag) and r.text:
                pieces.append(r.text)
            elif r.tag.endswith("}tab"):
                pieces.append("\t")
            elif r.tag.endswith("}br"):
                pieces.append("\n")
            elif hidden_tag and r.tag.endswith("}" + hidden_tag):
                ex.hidden_text += 1
        if pieces:
            paras.append("".join(pieces))
    return paras


def _docx(z: zipfile.ZipFile, ex: Extracted) -> None:
    parts: list[str] = []
    for name in ["word/document.xml"] + sorted(n for n in z.namelist() if re.fullmatch(r"word/(header|footer)\d*\.xml", n)):
        raw = _read_part(z, name)
        if raw:
            parts += _walk_text(ET.fromstring(raw), "p", "t", ex, hidden_tag="vanish")
    comments = _read_part(z, "word/comments.xml")
    if comments:
        parts += ["[comment] " + c for c in _walk_text(ET.fromstring(comments), "p", "t", ex)]
    ex.text = _cap(parts, ex)


def _pptx(z: zipfile.ZipFile, ex: Extracted) -> None:
    parts: list[str] = []
    slides = sorted((n for n in z.namelist() if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)), key=lambda n: int(re.findall(r"\d+", n)[0]))
    ex.pages = len(slides)
    for name in slides[:40]:
        raw = _read_part(z, name)
        if raw:
            parts += _walk_text(ET.fromstring(raw), "p", "t", ex)
    ex.text = _cap(parts, ex)


def _xlsx(z: zipfile.ZipFile, ex: Extracted) -> None:
    shared: list[str] = []
    raw = _read_part(z, "xl/sharedStrings.xml")
    if raw:
        for si in ET.fromstring(raw):
            shared.append("".join(t.text or "" for t in si.iter() if t.tag.endswith("}t")))
    wb = _read_part(z, "xl/workbook.xml")
    if wb:
        ex.hidden_sheets = sum(1 for el in ET.fromstring(wb).iter() if el.tag.endswith("}sheet") and el.get("state") in ("hidden", "veryHidden"))
    rows: list[str] = []
    cells = 0
    for name in sorted(n for n in z.namelist() if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", n))[:3]:
        raw = _read_part(z, name)
        if not raw:
            continue
        for row in ET.fromstring(raw).iter():
            if not row.tag.endswith("}row"):
                continue
            values = []
            for c in row:
                v = next((x for x in c if x.tag.endswith("}v")), None)
                is_ = next((x for x in c if x.tag.endswith("}is")), None)
                if c.get("t") == "s" and v is not None and (v.text or "").isdigit() and int(v.text) < len(shared):
                    values.append(shared[int(v.text)])
                elif is_ is not None:
                    values.append("".join(t.text or "" for t in is_.iter() if t.tag.endswith("}t")))
                elif v is not None and v.text:
                    values.append(v.text)
                cells += 1
                if cells > MAX_SHEET_CELLS:
                    ex.truncated = True
                    break
            if values:
                rows.append(" | ".join(values))
            if cells > MAX_SHEET_CELLS:
                break
    ex.text = _cap(rows, ex)


def _ooxml(data: bytes, fmt: str, ex: Extracted) -> None:
    z = zipfile.ZipFile(io.BytesIO(data))
    if sum(i.file_size for i in z.infolist()) > MAX_UNCOMPRESSED:
        raise ValueError("container expands to an unsafe size")
    {"docx": _docx, "pptx": _pptx, "xlsx": _xlsx}[fmt](z, ex)


# ---------------------------------------------------------------------------------------- images

def _image(data: bytes, ex: Extracted) -> None:
    """A clean, bounded, metadata-free copy. The vision model only ever sees this, never the original file."""
    from PIL import Image

    Image.MAX_IMAGE_PIXELS = MAX_PIXELS
    warnings.simplefilter("error", Image.DecompressionBombWarning)
    img = Image.open(io.BytesIO(data))
    img.load()
    img = img.convert("RGB")
    img.thumbnail((IMAGE_MAX_SIDE, IMAGE_MAX_SIDE))
    for quality in (85, 70, 55, 40):
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=quality)
        if buf.tell() <= IMAGE_MAX_BYTES:
            ex.image_b64 = base64.b64encode(buf.getvalue()).decode("ascii")
            return
    ex.notes.append("The image was too large to read safely.")


def extract(data: bytes, fmt: str) -> Extracted:
    ex = Extracted()
    try:
        if fmt == "pdf":
            _pdf(data, ex)
        elif fmt in ("docx", "xlsx", "pptx"):
            _ooxml(data, fmt, ex)
        elif fmt == "image":
            _image(data, ex)
    except Exception:
        ex.text = ex.text or ""
        ex.notes.append("The contents could not be read (the file may be damaged or malformed).")
    return ex


# ---------------------------------------------------------------------------------------- content-level signals

def _sig(id_: str, finding: str, direction: Direction, strength: float, confidence: float, evidence: str = "") -> Signal:
    return Signal(id=f"content.{id_}", category=Category.document, finding=finding, direction=direction,
                  strength=strength, confidence=confidence, evidence=evidence)


# ---------------------------------------------------------------------------------------- everyday-fraud checks (no AI)

PAID_RX = re.compile(r"\b(amount paid|paid on|payment (received|successful|confirmation)|paid in full|receipt|thank you for your payment)\b", re.I)
BARE_AMOUNT = re.compile(r"^(rs\.?|inr|₹)\s?\d[\d,.]*$", re.I)
ADVANCE_RX = re.compile(
    r"\b(pay|deposit|transfer)\b[^.!?\n]{0,30}\b(first|in advance|upfront|before (you )?(start|join|joining|receiv\w*|we (release|send|process)))\b|"
    r"\b(advance|registration|processing|security|clearance|release|refundable)\s+(fee|deposit|charges?)\b|"
    r"\bfee\b[^.!?\n]{0,30}\bto (release|receive|unlock|claim|confirm)\b", re.I)
EMAIL_RX = re.compile(r"\b[\w.+-]+@([A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+)\b")
COMMON_MAIL = ("gmail.com", "yahoo.com", "outlook.com", "hotmail.com", "icloud.com", "rediffmail.com", "yahoo.co.in", "live.com")
COMMON_TLDS = {"com", "in", "org", "net", "co", "edu", "gov"}
MONTHS = {m: i + 1 for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}
_M = r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*"
DATE_RX = re.compile(
    rf"(?P<num>\b\d{{1,2}}[-/.]\d{{1,2}}[-/.]\d{{2,4}}\b)|(?P<iso>\b\d{{4}}-\d{{2}}-\d{{2}}\b)|"
    rf"(?P<dmy>\b\d{{1,2}}(?:st|nd|rd|th)?\s+{_M},?\s+\d{{4}}\b)|(?P<mdy>\b{_M}\s+\d{{1,2}},?\s+\d{{4}}\b)", re.I)


def is_paid_receipt(text: str) -> bool:
    return bool(PAID_RX.search(text))


def _distance(a: str, b: str) -> int:
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def _parse_date(m: re.Match) -> Optional[tuple[dt.date, bool]]:
    """Returns (date, plausible). A date that is impossible in both day-first and month-first order is not plausible."""
    g = m.lastgroup
    t = m.group(0)
    try:
        if g == "iso":
            return dt.date.fromisoformat(t), True
        if g == "num":
            a, b, y = (int(x) for x in re.split(r"[-/.]", t))
            y += 2000 if y < 100 else 0
            for day, mon in ((a, b), (b, a)):  # day-first is the norm here
                try:
                    return dt.date(y, mon, day), True
                except ValueError:
                    continue
            return None
        nums = re.findall(r"\d+", t)
        mon = MONTHS[re.search(_M, t, re.I).group(1).lower()]
        day, year = (int(nums[0]), int(nums[1])) if g == "dmy" else (int(nums[0]), int(nums[1]))
        return dt.date(year, mon, day), True
    except (ValueError, KeyError, AttributeError):
        return None


def _label_before(text: str, pos: int) -> str:
    return text[max(0, pos - 45):pos].lower()


def wording_checks(text: str, today: Optional[dt.date] = None) -> list[Signal]:
    """Simple everyday-fraud tells: asking to pay first, look-alike email domains, dates that contradict each other."""
    today = today or dt.date.today()
    out: list[Signal] = []
    paid = is_paid_receipt(text)

    # 1. Asking for money up front. Not applied to a receipt, where a "registration fee" has already been paid.
    if not paid:
        hits = [m.group(0).strip() for m in ADVANCE_RX.finditer(text)]
        if hits:
            out.append(_sig("advance_payment", "Asks you to pay first (an advance, deposit or fee) before anything is delivered",
                            Direction.suspicious, 0.7, 0.7, ", ".join(f"\"{h}\"" for h in hits[:3])))

    # 2. Email addresses that look like a well-known provider with a typo (gmial.com, gmail.con)
    for m in EMAIL_RX.finditer(text):
        dom = m.group(1).lower()
        tld = dom.rsplit(".", 1)[-1]
        typo = next((c for c in COMMON_MAIL if dom != c and _distance(dom, c) <= 2 and abs(len(dom) - len(c)) <= 2), None)
        if typo or (tld not in COMMON_TLDS and len(tld) <= 3 and _distance(tld, "com") == 1):
            out.append(_sig("email_lookalike", "An email address looks like a real provider with a spelling change",
                            Direction.suspicious, 0.6, 0.7, f"{m.group(0)} (did you mean {typo or 'the .com version'}?)"))
            break

    # 3. Dates that contradict each other or cannot be real
    dated: dict[str, list[dt.date]] = {"paid": [], "due": [], "issue": []}
    impossible = []
    for m in DATE_RX.finditer(text):
        parsed = _parse_date(m)
        if parsed is None:
            impossible.append(m.group(0))
            continue
        label = _label_before(text, m.start())
        if re.search(r"paid|payment date|received", label):
            dated["paid"].append(parsed[0])
        elif re.search(r"due|pay by|payable by|valid (until|till)|expires?", label):
            dated["due"].append(parsed[0])
        elif re.search(r"invoice date|date of issue|issued|dated|date:|bill date|order date", label):
            dated["issue"].append(parsed[0])
    if impossible:
        out.append(_sig("impossible_date", "A date in the document cannot exist", Direction.suspicious, 0.6, 0.8, ", ".join(impossible[:3])))
    if any(d > today + dt.timedelta(days=1) for d in dated["paid"]):
        out.append(_sig("future_paid_date", "It says it was paid on a date that has not happened yet", Direction.suspicious, 0.7, 0.8,
                        ", ".join(d.isoformat() for d in dated["paid"] if d > today)))
    if any(d > today + dt.timedelta(days=1) for d in dated["issue"]):
        out.append(_sig("future_issue_date", "The document is dated in the future", Direction.suspicious, 0.5, 0.7,
                        ", ".join(d.isoformat() for d in dated["issue"] if d > today)))
    if dated["issue"] and dated["due"] and min(dated["due"]) < min(dated["issue"]):
        out.append(_sig("dates_out_of_order", "The due date is before the date the document was issued", Direction.suspicious, 0.6, 0.8,
                        f"issued {min(dated['issue']).isoformat()}, due {min(dated['due']).isoformat()}"))
    if dated["issue"] and dated["paid"] and min(dated["paid"]) < min(dated["issue"]):
        out.append(_sig("dates_out_of_order", "It says it was paid before the date it was issued", Direction.suspicious, 0.5, 0.8,
                        f"issued {min(dated['issue']).isoformat()}, paid {min(dated['paid']).isoformat()}"))
    return out


def content_signals(ex: Extracted) -> tuple[list[Signal], list[Identifier]]:
    """Checks that need no AI: identifier check digits, hidden content, and pressure wording in the document text."""
    signals: list[Signal] = []
    found = find_identifiers(ex.text) if ex.text else []
    signals += identifier_signals(found)
    if ex.hidden_text:
        signals.append(_sig("hidden_text", "The document contains text that is hidden from view", Direction.suspicious, 0.6, 0.7,
                            f"{ex.hidden_text} hidden run(s) of text"))
    if ex.hidden_sheets:
        signals.append(_sig("hidden_sheet", "The workbook contains hidden sheets", Direction.suspicious, 0.4, 0.6,
                            f"{ex.hidden_sheets} hidden sheet(s)"))
    # Pressure wording inside the document itself (urgency, secrecy, changed payment details, hidden instructions to an AI).
    for s in find_signals(ex.text):
        # Every invoice and receipt has amounts, so a bare "INR 2050" is not pressure. Message checks still count it.
        if s.id == "text.payment_pressure" and s.spans and all(BARE_AMOUNT.match(ex.text[a:b].strip()) for a, b in s.spans):
            continue
        signals.append(s)
    signals += wording_checks(ex.text)
    identifiers = [Identifier(kind=f.kind, value=f.value, valid=f.valid, note=f.note) for f in found]
    return signals, identifiers


def build_content_report(ex: Extracted, identifiers: list[Identifier]) -> ContentReport:
    return ContentReport(
        extracted=bool(ex.text or ex.image_b64), characters=len(ex.text), truncated=ex.truncated, pages=ex.pages,
        links=ex.links, identifiers=identifiers, excerpt=ex.text[:600], notes=ex.notes)


def analyze_full(data: bytes, filename: str = "", vendor: Optional[str] = None):
    """Metadata check plus contents check. Returns (report, extracted_text, clean_image_b64)."""
    from .document import analyze_document

    report = analyze_document(data, filename, vendor)
    if report.format == "unknown" or any(s.id in ("document.unreadable", "document.encrypted") for s in report.signals):
        report.content = ContentReport(extracted=False, notes=["The contents could not be read."])
        return report, "", None
    ex = extract(data, report.format)
    signals, identifiers = content_signals(ex)
    report.signals += signals
    report.content = build_content_report(ex, identifiers)
    if ex.links:
        report.could_not_check.append(f"{len(ex.links)} link(s) inside the document were not analysed")
    if identifiers:
        report.could_not_check.append(
            "Whether the tax, bank or payment identifiers belong to the named vendor (that needs an official registry lookup)")
    report.could_not_check += ex.notes
    return report, ex.text, ex.image_b64
