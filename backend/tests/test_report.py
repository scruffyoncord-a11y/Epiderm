import io

from fastapi.testclient import TestClient
from pypdf import PdfReader

import app.main as main
from app import report
from tests.corpus import CORPUS

client = TestClient(main.app)


def doc(doc_id):
    return next(d for d in CORPUS if d["id"] == doc_id)


def pdf_text(res) -> str:
    assert res.status_code == 200 and res.headers["content-type"] == "application/pdf", res.text[:200]
    assert res.content.startswith(b"%PDF")
    return " ".join(page.extract_text() for page in PdfReader(io.BytesIO(res.content)).pages)


def email_result(text="Hi, please pay the attached invoice today.", file_id="forged_invoice_pdf"):
    files = {"file": ("invoice.pdf", doc(file_id)["build"](), "application/pdf")} if file_id else None
    res = client.post("/analyze-email/stream", data={"text": text}, files=files)
    import json
    return json.loads(res.text.strip().splitlines()[-1])["result"]


def test_the_report_of_a_forged_invoice_states_the_verdict_score_and_findings():
    result = email_result()
    text = pdf_text(client.post("/report", json=result))
    assert "NOT LEGIT" in text and str(result["risk"]["security_score"]) in text
    assert "SECURITY SCORE" in text and "Risk by area" in text and "The attachment" in text
    assert "changed payment details" in text.lower() or "changed our bank" in text.lower()
    assert "not proof" in text


def test_a_message_only_report_and_a_document_only_report_both_work():
    assert "The message" in pdf_text(client.post("/report", json=email_result(file_id=None, text="Urgent: transfer Rs 50,000 today, keep this between us.")))
    only_doc = email_result(text="", file_id="genuine_invoice_pdf")
    text = pdf_text(client.post("/report", json=only_doc))
    assert "LOOKS LEGIT" in text and "The message" not in text


def test_the_report_never_includes_the_raw_document_text_and_masks_account_numbers():
    text = pdf_text(client.post("/report", json=email_result()))
    assert "91020034455661" not in text  # the raw account number is not in the report
    assert "Text we read" not in text


def test_an_attachment_result_on_its_own_gets_a_risk_summary_built_for_it():
    d = doc("forged_invoice_pdf")
    att = client.post("/analyze-document", files={"file": ("f.pdf", d["build"](), "application/pdf")}).json()
    text = pdf_text(client.post("/report", json={"attachment": att}))
    assert "NOT LEGIT" in text


def test_an_empty_report_is_refused_and_junk_is_rejected():
    assert client.post("/report", json={}).status_code == 422
    assert client.post("/report", json={"attachment": {"nonsense": True}}).status_code == 422


def test_hostile_text_cannot_break_the_pdf():
    result = email_result(text="<b>Urgent</b> </para><font color=red> transfer Rs 50,000 & keep it secret \x00\x07 " + "A" * 4000)
    pdf_text(client.post("/report", json=result))


def test_clean_helper_strips_control_characters_and_shortens():
    assert report._clean("a\x00b\x07  c\n\nd") == "ab c d"
    assert len(report._clean("x" * 500, 50)) == 50
