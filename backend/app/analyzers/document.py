"""Document metadata detector: PDFs, Office files (docx/xlsx/pptx) and images.

Reads what a file says about itself (which program made it, when, by whom, whether it was
saved again afterwards, whether it carries active content) and turns that into signals.

Metadata is easy to strip and easy to fake, so every finding is weak-to-moderate evidence and
a missing field is "unknown", never suspicious. Files are handled in memory only and parsed
defensively: size caps, no macro or script execution, safe XML parsing, zip-bomb guard.
"""
from __future__ import annotations

import io
import re
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

import defusedxml.ElementTree as ET

from ..models import Category, Direction, DocumentReport, Signal

MAX_BYTES = 10 * 1024 * 1024
MAX_UNCOMPRESSED = 60 * 1024 * 1024  # total declared size of a zip container
MAX_PART = 5 * 1024 * 1024  # largest single XML part we will read

IMAGE_EDITORS = re.compile(
    r"photoshop|gimp|canva|pixlr|pixelmator|paint\.net|affinity (photo|designer)|picsart|snapseed|lightroom|illustrator|"
    r"coreldraw|fotor|photopea|inkscape", re.I)
ONLINE_CONVERTERS = re.compile(
    r"ilovepdf|smallpdf|sejda|pdf24|pdfescape|sodapdf|pdfcandy|online2pdf|pdf2go|freepdfconvert|pdffiller", re.I)
ACCOUNTING = re.compile(
    r"tally|zoho|quickbooks|xero|\bsap\b|busy accounting|sage |freshbooks|odoo|myob|marg|vyapar|cleartax|oracle|netsuite", re.I)
COMMON = re.compile(
    r"microsoft|word|excel|powerpoint|libreoffice|openoffice|wps|google docs|skia|chrome|cairo|pdflib|itext|"
    r"reportlab|wkhtml|prince|quartz|pdfmaker|acrobat distiller|ghostscript|apple", re.I)

VENDOR_STOP = {"pvt", "ltd", "limited", "private", "llp", "inc", "co", "the", "and", "of", "company", "corp", "corporation"}


@dataclass
class Metadata:
    format: str = "unknown"  # pdf | docx | xlsx | pptx | image | unknown
    fields: dict[str, str] = field(default_factory=dict)
    tool: str = ""  # everything that names software, joined, for pattern matching
    author: str = ""
    company: str = ""
    created: Optional[datetime] = None
    modified: Optional[datetime] = None
    versions: int = 1  # incremental saves (PDF)
    active_content: list[str] = field(default_factory=list)
    macros: bool = False
    external_template: bool = False
    tracked_changes: bool = False
    encrypted: bool = False
    unreadable: bool = False
    has_any_metadata: bool = False


# ----------------------------------------------------------------------------- helpers

def _utc(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def _clean(v) -> str:
    return re.sub(r"[\x00-\x1f\x7f]", " ", str(v)).strip()[:200] if v not in (None, "") else ""


def _fmt(dt: Optional[datetime]) -> str:
    return dt.strftime("%Y-%m-%d %H:%M UTC") if dt else ""


def _parse_iso(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        return _utc(datetime.fromisoformat(s.strip().replace("Z", "+00:00")))
    except ValueError:
        return None


def detect_format(data: bytes) -> str:
    if data.startswith(b"%PDF-"):
        return "pdf"
    if data.startswith(b"\xff\xd8\xff") or data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image"
    if data.startswith(b"PK\x03\x04"):
        try:
            names = zipfile.ZipFile(io.BytesIO(data)).namelist()
        except zipfile.BadZipFile:
            return "unknown"
        if any(n.startswith("word/") for n in names):
            return "docx"
        if any(n.startswith("xl/") for n in names):
            return "xlsx"
        if any(n.startswith("ppt/") for n in names):
            return "pptx"
    return "unknown"


# ----------------------------------------------------------------------------- extraction

def _extract_pdf(data: bytes, m: Metadata) -> None:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data), strict=False)
    if reader.is_encrypted:
        try:
            if not reader.decrypt(""):
                m.encrypted = True
                return
        except Exception:
            m.encrypted = True
            return
    meta = reader.metadata
    if meta:
        m.has_any_metadata = True
        producer, creator, author = _clean(meta.producer), _clean(meta.creator), _clean(meta.author)
        m.tool = " ".join(x for x in (producer, creator) if x)
        m.author = author
        try:
            m.created, m.modified = _utc(meta.creation_date), _utc(meta.modification_date)
        except Exception:
            pass
        for label, val in (("Made with (producer)", producer), ("Created with (creator)", creator),
                           ("Author", author), ("Title", _clean(meta.title))):
            if val:
                m.fields[label] = val
    try:
        xmp = reader.xmp_metadata
        if xmp and xmp.xmp_creator_tool:
            t = _clean(xmp.xmp_creator_tool)
            m.tool = f"{m.tool} {t}".strip()
            m.fields["Creator tool (XMP)"] = t
            m.has_any_metadata = True
    except Exception:
        pass
    m.fields["Pages"] = str(len(reader.pages))
    m.versions = max(1, data.count(b"%%EOF"))
    if m.versions > 1:
        m.fields["Saved versions"] = str(m.versions)
    for marker, label in ((b"/JavaScript", "JavaScript"), (b"/JS", "JavaScript"), (b"/Launch", "launch action"),
                          (b"/EmbeddedFile", "embedded file")):
        if marker in data and label not in m.active_content:
            m.active_content.append(label)


def _read_part(z: zipfile.ZipFile, name: str) -> Optional[bytes]:
    try:
        info = z.getinfo(name)
    except KeyError:
        return None
    if info.file_size > MAX_PART:
        return None
    return z.read(name)


def _xml_text(root, tag_suffix: str) -> str:
    for el in root.iter():
        if el.tag.endswith("}" + tag_suffix) or el.tag == tag_suffix:
            return _clean(el.text or "")
    return ""


def _extract_ooxml(data: bytes, m: Metadata) -> None:
    z = zipfile.ZipFile(io.BytesIO(data))
    if sum(i.file_size for i in z.infolist()) > MAX_UNCOMPRESSED:
        raise ValueError("container expands to an unsafe size")
    names = z.namelist()
    core = _read_part(z, "docProps/core.xml")
    app = _read_part(z, "docProps/app.xml")
    if core:
        r = ET.fromstring(core)
        m.has_any_metadata = True
        creator, last_by = _xml_text(r, "creator"), _xml_text(r, "lastModifiedBy")
        m.author = creator
        m.created = _parse_iso(_xml_text(r, "created"))
        m.modified = _parse_iso(_xml_text(r, "modified"))
        revision = _xml_text(r, "revision")
        for label, val in (("Author", creator), ("Last saved by", last_by), ("Title", _xml_text(r, "title")),
                           ("Revision", revision)):
            if val:
                m.fields[label] = val
    if app:
        r = ET.fromstring(app)
        m.has_any_metadata = True
        application = _xml_text(r, "Application")
        m.company = _xml_text(r, "Company")
        m.tool = application
        for label, val in (("Made with (application)", application), ("Company", m.company),
                           ("Editing time (min)", _xml_text(r, "TotalTime"))):
            if val:
                m.fields[label] = val
    m.macros = any(n.lower().endswith("vbaproject.bin") for n in names)
    rels = _read_part(z, "word/_rels/document.xml.rels")
    if rels and b"attachedTemplate" in rels and b'TargetMode="External"' in rels:
        m.external_template = True
    doc = _read_part(z, "word/document.xml")
    if doc and (b"<w:ins " in doc or b"<w:del " in doc):
        m.tracked_changes = True


def _extract_image(data: bytes, m: Metadata) -> None:
    from PIL import Image

    img = Image.open(io.BytesIO(data))
    exif = img.getexif()
    software = _clean(exif.get(305) or img.info.get("Software", ""))
    stamp = _clean(exif.get(306) or "")
    try:
        original = _clean(exif.get_ifd(0x8769).get(36867, ""))
    except Exception:
        original = ""
    make, model = _clean(exif.get(271)), _clean(exif.get(272))
    m.tool = software
    m.has_any_metadata = bool(exif) or bool(img.info.get("Software"))
    for label, val in (("Software", software), ("Camera", " ".join(x for x in (make, model) if x)),
                       ("Date/time", stamp), ("Original capture time", original),
                       ("Size", f"{img.width} x {img.height}")):
        if val:
            m.fields[label] = val
    if exif.get(0x8825):
        m.fields["Contains GPS location"] = "yes"
    for raw in (original, stamp):
        try:
            if raw:
                m.created = _utc(datetime.strptime(raw, "%Y:%m:%d %H:%M:%S"))
                break
        except ValueError:
            continue


def extract_metadata(data: bytes) -> Metadata:
    m = Metadata(format=detect_format(data))
    try:
        if m.format == "pdf":
            _extract_pdf(data, m)
        elif m.format in ("docx", "xlsx", "pptx"):
            _extract_ooxml(data, m)
        elif m.format == "image":
            _extract_image(data, m)
        else:
            m.unreadable = True
    except Exception:
        m.unreadable = True
    if m.created:
        m.fields["Created"] = _fmt(m.created)
    if m.modified:
        m.fields["Modified"] = _fmt(m.modified)
    return m


# ----------------------------------------------------------------------------- signals

def _sig(id_, finding, direction, strength, confidence, evidence=""):
    return Signal(id=f"document.{id_}", category=Category.document, finding=finding, direction=direction,
                  strength=strength, confidence=confidence, evidence=evidence)


def _tokens(s: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9]+", s.lower()) if t not in VENDOR_STOP and len(t) > 1}


def build_signals(m: Metadata, vendor: Optional[str] = None, now: Optional[datetime] = None) -> list[Signal]:
    now = now or datetime.now(timezone.utc)
    S, R, N, U = Direction.suspicious, Direction.reassuring, Direction.neutral, Direction.unknown
    out: list[Signal] = []

    if m.unreadable:
        return [_sig("unreadable", "The file could not be read as a PDF, Office file or image", U, 0.0, 1.0)]
    if m.encrypted:
        return [_sig("encrypted", "The file is password-protected, so its metadata could not be read", U, 0.0, 1.0)]

    tool = m.tool
    if tool:
        if IMAGE_EDITORS.search(tool):
            out.append(_sig("editing_tool", "Made or edited in an image editor, which is unusual for an official document",
                            S, 0.7, 0.7, f"Software: {tool}"))
        elif ONLINE_CONVERTERS.search(tool):
            out.append(_sig("online_converter", "Produced by an online PDF tool, often used to change a document after it was made",
                            S, 0.3, 0.5, f"Software: {tool}"))
        elif ACCOUNTING.search(tool):
            out.append(_sig("accounting_software", "Made by accounting or business software, as genuine invoices usually are",
                            R, 0.4, 0.6, f"Software: {tool}"))
        elif COMMON.search(tool):
            out.append(_sig("common_tool", "Made by ordinary office or document software", N, 0.0, 0.5, f"Software: {tool}"))
        else:
            out.append(_sig("unrecognised_tool", "Made by software this checker does not recognise", N, 0.0, 0.3, f"Software: {tool}"))

    c, mod = m.created, m.modified
    if c and c > now + timedelta(days=1) or mod and mod > now + timedelta(days=1):
        out.append(_sig("future_date", "A date inside the file is in the future", S, 0.6, 0.7,
                        f"Created {_fmt(c)}, modified {_fmt(mod)}"))
    if c and mod:
        if mod < c - timedelta(minutes=1):
            out.append(_sig("dates_inconsistent", "The modified date is earlier than the created date", S, 0.5, 0.6,
                            f"Created {_fmt(c)}, modified {_fmt(mod)}"))
        elif mod - c > timedelta(hours=1):
            out.append(_sig("modified_after_creation", "The file was changed some time after it was first created", S, 0.4, 0.6,
                            f"Created {_fmt(c)}, modified {_fmt(mod)}"))
    if c and timedelta(0) <= now - c <= timedelta(days=7):
        days = max(0, (now - c).days)
        out.append(_sig("recently_created", "Created very recently, which matters if it claims to be an older document", S, 0.25, 0.5,
                        f"Created {days} day(s) ago"))
    if not c and not mod:
        out.append(_sig("no_dates", "The file records no creation or modification date", U, 0.0, 1.0))

    if m.format == "pdf" and m.versions > 1:
        out.append(_sig("incremental_updates", "The PDF was saved more than once, so changes may have been made after the first version",
                        S, 0.4, 0.5, f"{m.versions} saved versions (signed documents also do this)"))
    if m.active_content:
        active = [a for a in m.active_content if a != "embedded file"]
        if active:
            out.append(_sig("active_content", "The file contains active content that can run code", S, 0.7, 0.7,
                            ", ".join(active)))
        if "embedded file" in m.active_content:
            out.append(_sig("embedded_file", "The PDF has another file hidden inside it", S, 0.4, 0.5, "embedded file"))
    if m.macros:
        out.append(_sig("macros", "The file contains macros, which an ordinary invoice or letter does not need", S, 0.8, 0.8))
    if m.external_template:
        out.append(_sig("external_template", "The document loads a template from an outside address", S, 0.7, 0.7))
    if m.tracked_changes:
        out.append(_sig("tracked_changes", "The document still contains tracked changes, unusual for a final version", S, 0.3, 0.6))

    if vendor and (m.company or m.author):
        who = m.company or m.author
        if _tokens(vendor) and not (_tokens(vendor) & _tokens(who)):
            out.append(_sig("author_vendor_mismatch",
                            "The file's author or company does not match the vendor name (weak: authors are often individuals)",
                            S, 0.3, 0.4, f"File says: {who}; expected: {vendor}"))

    if not m.has_any_metadata:
        out.append(_sig("no_metadata", "The file carries no metadata (stripped, or made by a tool that does not write it)", U, 0.0, 1.0))
    return out


def analyze_document(data: bytes, filename: str = "", vendor: Optional[str] = None,
                     now: Optional[datetime] = None) -> DocumentReport:
    m = extract_metadata(data)
    signals = build_signals(m, vendor, now)
    suspicious = [s for s in signals if s.direction == Direction.suspicious]
    if m.unreadable:
        summary = "This file could not be read, so nothing could be checked."
    elif m.encrypted:
        summary = "This file is password-protected, so nothing could be checked."
    elif suspicious:
        summary = (f"{len(suspicious)} thing(s) about how this file was made are worth a second look. "
                   "Metadata can be faked or removed, so this is a reason to check, not proof.")
    else:
        summary = ("Nothing unusual in how this file was made. That does not prove the content is genuine: "
                   "metadata is easy to remove or fake.")
    unknown = [s.finding for s in signals if s.direction == Direction.unknown]
    return DocumentReport(
        filename=re.sub(r"[\x00-\x1f\x7f/\\]", "", filename)[:100], format=m.format, size_bytes=len(data),
        fields=m.fields, signals=signals, could_not_check=unknown, summary=summary)
