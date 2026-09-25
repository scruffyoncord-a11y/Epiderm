import json

from fastapi.testclient import TestClient

import app.main as main
from app import risk
from app.models import Band, Category, Direction, Signal
from tests.corpus import CORPUS

client = TestClient(main.app)
SCAM = "Urgent: transfer Rs 50,000 today and keep this between us."


def sig(id_, strength=0.7, confidence=0.8, direction=Direction.suspicious):
    return Signal(id=id_, category=Category.text, finding=id_, direction=direction, strength=strength, confidence=confidence)


def doc(doc_id):
    return next(d for d in CORPUS if d["id"] == doc_id)


def result(res):
    lines = [json.loads(line) for line in res.text.splitlines() if line.strip()]
    assert lines[-1]["stage"] == "done", lines[-1]
    return [e["stage"] for e in lines], lines[-1]["result"]


# ------------------------------------------------------------------------------------ the score

def test_the_score_always_sits_inside_its_verdicts_range():
    for band, (lo, hi) in risk.BAND_RANGE.items():
        assert lo <= risk.summarise([], band).risk_score <= hi
        many = [sig(f"text.x{i}", 1.0, 1.0) for i in range(6)]
        assert lo <= risk.summarise(many, band).risk_score <= hi
    assert risk.summarise([sig("text.a", 1, 1)] * 3, Band.allow).risk_score < risk.summarise([], Band.step_up).risk_score


def test_more_and_stronger_evidence_raises_the_score_and_security_is_its_inverse():
    one = risk.summarise([sig("text.a")], Band.verify)
    three = risk.summarise([sig("text.a"), sig("email.b"), sig("content.c")], Band.verify)
    assert three.risk_score > one.risk_score and three.security_score == 100 - three.risk_score


def test_reassuring_signals_never_lower_the_score():
    base = [sig("text.a")]
    calm = base + [sig("email.ok", 1.0, 1.0, Direction.reassuring)]
    assert risk.summarise(calm, Band.step_up).risk_score == risk.summarise(base, Band.step_up).risk_score
    assert risk.summarise(calm, Band.step_up).reassuring == 1


def test_verdict_words_follow_the_band():
    assert [risk.summarise([], b).verdict_label for b in (Band.allow, Band.step_up, Band.verify)] == ["LOOKS LEGIT", "SUSPICIOUS", "NOT LEGIT"]


def test_breakdown_by_area_and_the_matrix():
    s = risk.summarise([sig("text.a", 0.9, 0.9), sig("email.b", 0.3, 0.3), sig("content.c", 0.5, 1.0),
                        sig("document.d", 0.2, 0.5, Direction.unknown)], Band.verify)
    areas = {a.name: a for a in s.areas}
    assert areas["Wording & tactics"].risk == 81 and areas["File metadata"].risk == 0 and areas["File metadata"].unknown == 1
    assert [a.name for a in s.areas][0] == "Wording & tactics"  # riskiest first
    top = s.matrix[0]
    assert (top.id, top.likelihood, top.impact, top.weight) == ("text.a", 5, 5, 81)
    assert all(f.id != "document.d" for f in s.matrix)  # only warnings go on the matrix


# ------------------------------------------------------------------------------------ combining a message and its attachment

def test_the_worst_verdict_wins_when_combining():
    clean = risk.summarise([], Band.allow)
    bad = risk.summarise([sig("content.x")], Band.verify)
    both = risk.combine([("Message", clean), ("Attachment: a.pdf", bad)])
    assert both.band == Band.verify and both.verdict_label == "NOT LEGIT" and both.risk_score >= bad.risk_score
    assert [p.name for p in both.parts] == ["Message", "Attachment: a.pdf"]


def test_two_warnings_score_higher_than_one():
    warn = risk.summarise([sig("text.x")], Band.step_up)
    assert risk.combine([("a", warn), ("b", warn)]).risk_score > warn.risk_score


def test_one_part_is_returned_unchanged():
    one = risk.summarise([sig("text.x")], Band.step_up)
    assert risk.combine([("Message", one)]) is one and risk.combine([]) is None


# ------------------------------------------------------------------------------------ every check carries a risk summary

def test_the_message_check_returns_a_risk_summary():
    _, res = result(client.post("/analyze-text/stream", json={"text": SCAM}))
    assert res["risk"]["verdict"] in ("suspicious", "not_legit") and res["risk"]["matrix"]


def test_the_document_check_returns_a_risk_summary():
    d = doc("forged_invoice_pdf")
    res = client.post("/analyze-document", files={"file": ("f.pdf", d["build"](), "application/pdf")})
    assert res.json()["risk"]["verdict_label"] == "NOT LEGIT"


def test_an_email_with_an_attachment_runs_both_pipelines_and_combines_them():
    d = doc("forged_invoice_pdf")
    stages, res = result(client.post("/analyze-email/stream", data={"text": "Hi, please find the invoice attached. Thanks."},
                                     files={"file": ("invoice.pdf", d["build"](), "application/pdf")}))
    assert stages[:2] == ["started", "verifying"] and "attachment" in stages and "attachment_verifying" in stages
    assert res["message"]["band"] == "allow" and res["attachment"]["band"] == "verify"
    assert res["risk"]["verdict_label"] == "NOT LEGIT" and len(res["risk"]["parts"]) == 2  # a polite message cannot hide a forged invoice


def test_an_attachment_alone_is_enough_and_a_message_alone_still_works():
    d = doc("genuine_invoice_pdf")
    _, res = result(client.post("/analyze-email/stream", files={"file": ("g.pdf", d["build"](), "application/pdf")}))
    assert res["message"] is None and res["attachment"] is not None and res["risk"]["parts"] == []
    _, res = result(client.post("/analyze-email/stream", data={"text": SCAM}))
    assert res["attachment"] is None and res["risk"]["verdict"] != "legit"


def test_an_empty_email_check_is_refused():
    assert client.post("/analyze-email/stream", data={"text": "  "}).status_code == 422
