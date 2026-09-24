import base64
import io

import pytest
from PIL import Image

from app import documents
from app.analyzers import content
from app.analyzers.content import analyze_full, extract, sanitise
from app.analyzers.identifiers import check_gstin, check_iban, find_identifiers, gstin_check_char, identifier_signals, mask
from app.analyzers.text import find_signals
from app.models import Band, Direction
from tests import corpus
from tests.corpus import CORPUS, docx_bytes, invalid_gstin, pdf_bytes, pptx_bytes, valid_gstin, xlsx_bytes

SUS = Direction.suspicious


def sus_ids(report):
    return {s.id for s in report.signals if s.direction == SUS}


# ------------------------------------------------------------------------------------ identifiers

def test_gstin_check_digit_accepts_real_structure_and_rejects_tampering():
    good = valid_gstin()
    assert check_gstin(good)[0] is True
    for i in range(len(good) - 1, len(good) - 4, -1):  # any changed check-relevant character breaks it
        tampered = good[:i] + ("A" if good[i] != "A" else "B") + good[i + 1:]
        assert check_gstin(tampered)[0] is False or tampered == good
    assert check_gstin("00" + good[2:])[0] is False  # not a real state code
    assert check_gstin("27AAPFU0939F1ZV")[0] is True  # the widely published sample number


def test_pan_ifsc_iban_upi_and_account_number_handling():
    text = ("PAN AAPFU0939F  bad PAN AAPXU0939F  IFSC HDFC0001234  IBAN GB82 WEST 1234 5698 7654 32  "
            "bad IBAN GB82 WEST 1234 5698 7654 33  UPI shop@okhdfcbank  A/c No: 501001234567")
    kinds = {(f.kind, f.valid) for f in find_identifiers(text)}
    assert ("PAN", True) in kinds and ("PAN", False) in kinds  # 4th letter P vs X
    assert ("IFSC", None) in kinds and ("UPI", None) in kinds
    assert ("IBAN", True) in kinds and ("IBAN", False) in kinds
    acct = next(f for f in find_identifiers(text) if f.kind == "ACCOUNT")
    assert acct.value == mask("501001234567") and "5010" not in acct.value  # never shown in full


def test_only_impossible_identifiers_raise_a_flag_and_valid_ones_are_neutral():
    sigs = identifier_signals(find_identifiers(f"GSTIN {valid_gstin()} and IFSC HDFC0001234"))
    assert sigs == []  # valid-looking is not reassuring, and not suspicious either
    bad = identifier_signals(find_identifiers(f"GSTIN {invalid_gstin()}"))
    assert [s.id for s in bad] == ["content.invalid_gstin"] and bad[0].strength >= 0.7


def test_iban_needs_the_word_iban_unless_it_passes_so_random_codes_are_not_flagged():
    assert [f for f in find_identifiers("Order code AB12 CDEF GHIJ KLMN") if f.kind == "IBAN"] == []


def test_identifiers_inside_a_gstin_are_not_double_counted():
    found = find_identifiers(f"GSTIN {valid_gstin()}")
    assert [f.kind for f in found] == ["GSTIN"]


# ------------------------------------------------------------------------------------ the wording rule added for documents

def test_changed_payment_details_is_detected_and_ordinary_text_is_not():
    hits = [
        "We have changed our bank details. Please update your records.",
        "Kindly use the new bank account below for all future payments.",
        "Our updated payment instructions are attached.",
    ]
    for t in hits:
        assert "text.changed_payment_details" in {s.id for s in find_signals(t)}, t
    for t in ("The bank is closed on Sunday.", "Please pay by the due date.", "Thanks for your payment last week."):
        assert "text.changed_payment_details" not in {s.id for s in find_signals(t)}, t


# ------------------------------------------------------------------------------------ extraction, format by format

def test_pdf_text_pages_and_links_are_extracted():
    data = pdf_bytes([["Invoice 42", "Total: 5000"], ["Page two text"]], links=["https://example.com/pay"])
    ex = extract(data, "pdf")
    assert "Invoice 42" in ex.text and "Page two text" in ex.text and ex.pages == 2
    assert ex.links == ["https://example.com/pay"]


def test_a_long_pdf_is_truncated_not_swallowed():
    ex = extract(pdf_bytes([["x" * 80] * 40 for _ in range(30)]), "pdf")
    assert ex.truncated and len(ex.text) <= content.MAX_TEXT
    assert ex.pages == 30


def test_docx_text_hidden_text_and_comments():
    ex = extract(docx_bytes(["Visible paragraph."], hidden=["Secret instruction"]), "docx")
    assert "Visible paragraph." in ex.text and "Secret instruction" in ex.text  # kept, so it can be examined
    assert ex.hidden_text == 1


def test_xlsx_cells_and_hidden_sheets():
    ex = extract(xlsx_bytes([["Item", "Amount"], ["Consulting", 45000]], hidden_sheet_rows=[["hidden note"]]), "xlsx")
    assert "Consulting" in ex.text and "45000" in ex.text and ex.hidden_sheets == 1


def test_pptx_slides():
    ex = extract(pptx_bytes([["Title", "Point one"], ["Second slide"]]), "pptx")
    assert "Point one" in ex.text and "Second slide" in ex.text and ex.pages == 2


def test_sanitise_removes_control_characters_and_collapses_whitespace():
    assert sanitise("a\x00b\x07c   d\n\n\n\n\ne  f") == "a b c d\n\ne f"


def test_unreadable_and_hostile_files_do_not_crash():
    for name in ("zip_bomb_docx", "corrupt_pdf", "encrypted_pdf", "scanned_pdf_no_text"):
        data = next(d for d in CORPUS if d["id"] == name)["build"]()
        report, text, image = analyze_full(data, name)
        assert report.content is not None and text == "" and image is None
    notes = analyze_full(corpus.encrypted_pdf(), "e.pdf")[0].content
    assert notes.extracted is False


def test_a_scanned_pdf_says_it_has_no_selectable_text():
    report, _, _ = analyze_full(next(d for d in CORPUS if d["id"] == "scanned_pdf_no_text")["build"](), "scan.pdf")
    assert any("no selectable text" in c for c in report.could_not_check)


# ------------------------------------------------------------------------------------ images: a clean copy for the vision model

def jpeg_b64_dims(b64):
    img = Image.open(io.BytesIO(base64.b64decode(b64)))
    return img.format, img.size, dict(img.getexif())


def test_an_image_is_reencoded_small_clean_and_without_its_metadata():
    src = Image.new("RGB", (2600, 1900), "white")
    exif = Image.Exif()
    exif[305] = "Secret Editor 9"
    buf = io.BytesIO()
    src.save(buf, "JPEG", exif=exif)
    ex = extract(buf.getvalue(), "image")
    fmt, size, tags = jpeg_b64_dims(ex.image_b64)
    assert fmt == "JPEG" and max(size) <= content.IMAGE_MAX_SIDE and tags == {}  # metadata is gone
    assert len(base64.b64decode(ex.image_b64)) <= content.IMAGE_MAX_BYTES


def test_a_decompression_bomb_image_is_refused_safely():
    buf = io.BytesIO()
    Image.new("1", (9000, 9000)).save(buf, "PNG")  # tiny file, 81 million pixels
    ex = extract(buf.getvalue(), "image")
    assert ex.image_b64 is None and ex.notes


# ------------------------------------------------------------------------------------ the fixed checks and verdict across the corpus (no AI)

FIXED_BAND = {d["id"]: d["band"] for d in CORPUS if not d["id"].endswith("_png")}


@pytest.mark.parametrize("doc_id", sorted(FIXED_BAND))
def test_fixed_checks_reach_the_expected_verdict(doc_id):
    doc = next(d for d in CORPUS if d["id"] == doc_id)
    report, _, _ = analyze_full(doc["build"](), doc_id, doc["vendor"] or None)
    assert documents.document_band(report.signals) == Band(FIXED_BAND[doc_id]), sorted(sus_ids(report))


def test_the_forged_invoice_trips_each_independent_warning():
    doc = next(d for d in CORPUS if d["id"] == "forged_invoice_pdf")
    report, _, _ = analyze_full(doc["build"](), "forged.pdf", "Sunrise Traders")
    assert {"content.invalid_gstin", "document.editing_tool", "document.modified_after_creation", "text.changed_payment_details",
            "text.urgency", "text.secrecy"} <= sus_ids(report)


def test_the_genuine_invoice_raises_nothing_and_its_identifiers_are_listed_as_neutral():
    doc = next(d for d in CORPUS if d["id"] == "genuine_invoice_pdf")
    report, text, _ = analyze_full(doc["build"](), "genuine.pdf", "Zenith Office Supplies")
    assert sus_ids(report) - {"document.recently_created"} == set()
    kinds = {i.kind: i.valid for i in report.content.identifiers}
    assert kinds["GSTIN"] is True and "IFSC" in kinds and "ACCOUNT" in kinds
    assert any("official registry" in c for c in report.could_not_check)  # we say what we did not verify


def test_links_inside_a_document_are_listed_as_unchecked():
    report, _, _ = analyze_full(pdf_bytes([["Pay here"]], {"Producer": "Tally"}, links=["http://pay-now.example/x"]), "l.pdf")
    assert report.content.links == ["http://pay-now.example/x"]
    assert any("link(s) inside the document were not analysed" in c for c in report.could_not_check)


# ------------------------------------------------------------------------------------ everyday fraud tells, and paid receipts

import datetime as dt

from app.analyzers.content import Extracted, content_signals, wording_checks

RECEIPT = """Customer Details
Name Rahul K R
Email ID Rahulk.renjith@gmail.com
Select Program Artificial Intelligence
INR 2050.00 paid on 19 Sep 2026, 10:13 PM
Description Qty Unit Price(INR) Amount(INR)
Fee 1 2050 2050
Total INR 2050.00
Offers & Charges INR 0.00
Amount Paid INR 2050.00"""
TODAY = dt.date(2026, 9, 25)


def ids(text, today=TODAY):
    sigs, _ = content_signals(Extracted(text=text))
    return {s.id for s in sigs if s.direction == SUS} | {s.id for s in wording_checks(text, today) if s.direction == SUS}


def test_an_already_paid_receipt_is_not_flagged_for_having_amounts():
    """Regression from a real receipt: 'INR 2050' and 'INR 0' were treated as pressure to pay."""
    assert ids(RECEIPT) == set()


def test_an_amount_is_still_pressure_in_a_message_check_wording():
    assert "text.payment_pressure" in {s.id for s in find_signals("Send INR 5000 now")}


def test_asking_to_pay_first_is_flagged_but_not_on_a_paid_receipt():
    assert "content.advance_payment" in ids("Offer letter. Pay a registration fee of Rs 5000 first to confirm your seat.")
    assert "content.advance_payment" in ids("Pay in advance before we release the parcel.")
    assert "content.advance_payment" not in ids(RECEIPT + "\nRegistration fee received")


def test_lookalike_email_domains_are_flagged_and_real_ones_are_not():
    for bad in ("rahul@gmial.com", "rahul@gmail.con", "hr@yahooo.com", "a@hotmial.com"):
        assert "content.email_lookalike" in ids(f"Contact {bad}"), bad
    for good in ("rahul@gmail.com", "info@zenith-supplies.in", "a@outlook.com"):
        assert "content.email_lookalike" not in ids(f"Contact {good}"), good


def test_dates_that_contradict_each_other_are_flagged():
    assert "content.future_paid_date" in ids("INR 500 paid on 12 Dec 2026", TODAY)
    assert "content.dates_out_of_order" in ids("Invoice date: 20-09-2026\nDue date: 05-09-2026")
    assert "content.dates_out_of_order" in ids("Invoice date: 20-09-2026\nPaid on 01-09-2026")
    assert "content.impossible_date" in ids("Invoice date 45/45/2026")
    assert "content.future_issue_date" in ids("Invoice date: 01-01-2027")
    assert not ids("Invoice date: 10-09-2026\nDue date: 25-09-2026")
