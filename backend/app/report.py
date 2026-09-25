"""Builds the downloadable PDF report from a finished result.

The report is made from data the person already has on screen (the result JSON), so nothing new is analysed
and nothing is stored: the PDF is generated in memory and streamed back. It deliberately leaves out the raw
text of the message and the document, keeping only the findings, so it is safe to forward to a bank or the
cybercrime portal without leaking the whole document.
"""
from __future__ import annotations

import datetime as dt
import io
from typing import Optional
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import HRFlowable, KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from .models import Direction, DocumentReport, EmailResult, RiskSummary, Signal

TONE = {"legit": colors.HexColor("#0f9d6b"), "suspicious": colors.HexColor("#d98a00"), "not_legit": colors.HexColor("#d92d2d")}
INK = colors.HexColor("#1b1b1f")
MUTED = colors.HexColor("#5b5b66")
LINE = colors.HexColor("#d8d8de")
SOFT = colors.HexColor("#f4f4f7")

_base = getSampleStyleSheet()
BODY = ParagraphStyle("body", parent=_base["BodyText"], fontName="Helvetica", fontSize=9.5, leading=13.5, textColor=INK)
SMALL = ParagraphStyle("small", parent=BODY, fontSize=8, leading=11, textColor=MUTED)
SMALL_KEEP = ParagraphStyle("smallkeep", parent=SMALL, keepWithNext=1)
H2 = ParagraphStyle("h2", parent=BODY, fontName="Helvetica-Bold", fontSize=11, leading=14, spaceBefore=12, spaceAfter=5, keepWithNext=1)
BRAND = ParagraphStyle("brand", parent=BODY, fontName="Times-Bold", fontSize=20, leading=24)
SCORE = ParagraphStyle("score", parent=BODY, fontName="Times-Bold", fontSize=54, leading=58, alignment=TA_CENTER)
SCORE_LABEL = ParagraphStyle("scorelabel", parent=SMALL, alignment=TA_CENTER, fontSize=7.5, textColor=MUTED)


def _p(text: object, style: ParagraphStyle = BODY) -> Paragraph:
    return Paragraph(escape(str(text)), style)


def _clean(text: str, limit: int = 240) -> str:
    """Report text is short, single-spaced and free of control characters."""
    t = " ".join("".join(ch for ch in str(text) if ch.isprintable() or ch in "\n\t").split())
    return t if len(t) <= limit else t[: limit - 1] + "…"


def _bar(value: int, tone: colors.Color, width: float = 60 * mm) -> Table:
    filled = max(0.5, width * max(0, min(100, value)) / 100)
    t = Table([["", ""]], colWidths=[filled, max(width - filled, 0.1)], rowHeights=[3.2 * mm])
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (0, 0), tone), ("BACKGROUND", (1, 0), (1, 0), colors.HexColor("#e6e6eb")),
                           ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                           ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0)]))
    return t


def _risk_tone(value: int) -> colors.Color:
    return TONE["not_legit"] if value >= 70 else TONE["suspicious"] if value >= 40 else colors.HexColor("#c9a800") if value > 0 else colors.HexColor("#9a9aa5")


def _signals_table(signals: list[Signal]) -> Optional[Table]:
    rows = [[_p("Finding", SMALL), _p("Type", SMALL), _p("Weight", SMALL)]]
    warn = sorted((s for s in signals if s.direction == Direction.suspicious), key=lambda s: -(s.strength * s.confidence))
    for s in warn[:12]:
        detail = f"<b>{escape(_clean(s.finding, 130))}</b>"
        if s.evidence:
            detail += f"<br/><font size=7.5 color='#5b5b66'>{escape(_clean(s.evidence, 170))}</font>"
        rows.append([Paragraph(detail, BODY), _p("Warning", SMALL), _p(round(100 * s.strength * s.confidence), SMALL)])
    if len(rows) == 1:
        return None
    t = Table(rows, colWidths=[118 * mm, 22 * mm, 20 * mm], repeatRows=1)
    t.setStyle(TableStyle([("LINEBELOW", (0, 0), (-1, -1), 0.4, LINE), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                           ("BACKGROUND", (0, 0), (-1, 0), SOFT), ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
    return t


def _list(items: list[str]) -> list:
    return [Paragraph("• " + escape(_clean(i, 260)), BODY) for i in items if i]


def _doc_section(att: DocumentReport) -> list:
    out: list = [Paragraph("The attachment", H2), _p(f"{att.filename or 'file'} · {att.format} · {round(att.size_bytes / 1024) or 1} KB", SMALL_KEEP)]
    c = att.content
    if c and c.facts:
        f = c.facts
        rows = [(k, v) for k, v in (("Looks like", f.document_type.replace("_", " ")), ("Issued by", f.issuer), ("Addressed to", f.recipient),
                                    ("Total", f.total_amount), ("Pay to", f.account_holder), ("Dates", ", ".join(f.dates))) if v]
        if rows:
            t = Table([[_p(k, SMALL), _p(_clean(v, 120))] for k, v in rows], colWidths=[32 * mm, 128 * mm])
            t.setStyle(TableStyle([("LINEBELOW", (0, 0), (-1, -1), 0.4, LINE), ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]))
            out += [Spacer(1, 3), t]
    if c and c.identifiers:
        out += [Paragraph("Identifiers found", H2)]
        out += _list([f"{i.kind} {i.value}: " + ("impossible (fails its own check)" if i.valid is False else "passes its check" if i.valid else "not checkable") for i in c.identifiers])
    sig = _signals_table(att.signals)
    if sig is not None:
        out += [Paragraph("Warning signs in the attachment", H2), sig]
    return out


def build_pdf(result: EmailResult, when: Optional[dt.datetime] = None) -> bytes:
    when = when or dt.datetime.now()
    risk: Optional[RiskSummary] = result.risk
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=20 * mm, rightMargin=20 * mm, topMargin=18 * mm, bottomMargin=18 * mm,
                            title="Epiderm verification report", author="Epiderm")

    def footer(canvas, d):
        canvas.saveState()
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(MUTED)
        canvas.drawString(20 * mm, 10 * mm, "Epiderm · a risk assessment, not proof. A person makes the final decision.")
        canvas.drawRightString(A4[0] - 20 * mm, 10 * mm, f"Page {d.page}")
        canvas.restoreState()

    story: list = [
        Paragraph("Epiderm", BRAND),
        _p(f"Verification report · {when.strftime('%d %b %Y, %H:%M')}", SMALL),
        HRFlowable(width="100%", thickness=0.6, color=LINE, spaceBefore=6, spaceAfter=8),
    ]

    if risk is not None:
        tone = TONE.get(risk.verdict, MUTED)
        head = Table([[Paragraph(f"<font color='{tone.hexval().replace('0x', '#')}'>{risk.security_score}</font>", SCORE),
                       [Paragraph(f"<font color='{tone.hexval().replace('0x', '#')}'><b>{escape(risk.verdict_label)}</b></font>",
                                  ParagraphStyle("v", parent=BRAND, fontSize=24, leading=28)),
                        Spacer(1, 3),
                        _p(f"{risk.level.title()} risk · risk score {risk.risk_score}/100 · {risk.suspicious} warning sign(s), "
                           f"{risk.reassuring} reassuring, {risk.unknown} could not be verified")]]],
                      colWidths=[45 * mm, 125 * mm])
        head.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("BOX", (0, 0), (-1, -1), 0.8, tone), ("BACKGROUND", (0, 0), (-1, -1), SOFT),
                                  ("TOPPADDING", (0, 0), (-1, -1), 10), ("BOTTOMPADDING", (0, 0), (-1, -1), 10)]))
        story += [head, Paragraph("SECURITY SCORE (higher is safer)", SCORE_LABEL)]

        if risk.parts:
            story += [Paragraph("Checked together", H2)]
            for part in risk.parts:
                story.append(KeepTogether([Table([[_p(_clean(part.name, 60)), _bar(part.risk_score, _risk_tone(part.risk_score), 60 * mm), _p(f"risk {part.risk_score}", SMALL)]],
                                                 colWidths=[62 * mm, 66 * mm, 30 * mm])]))
        if risk.areas:
            story += [Paragraph("Risk by area", H2)]
            t = Table([[_p(a.name), _bar(a.risk, _risk_tone(a.risk)), _p(f"{a.risk}/100 · {a.suspicious} warning(s)", SMALL)] for a in risk.areas],
                      colWidths=[48 * mm, 66 * mm, 46 * mm])
            t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]))
            story.append(t)
        if risk.matrix:
            story += [Paragraph("Biggest warning signs", H2)]
            rows = [[_p("Finding", SMALL), _p("Area", SMALL), _p("Likelihood", SMALL), _p("Impact", SMALL)]]
            rows += [[_p(_clean(f.label, 110)), _p(f"{f.area}" + (f" ({f.source.split(':')[0].lower()})" if f.source else ""), SMALL), _p(f"{f.likelihood}/5", SMALL), _p(f"{f.impact}/5", SMALL)] for f in risk.matrix[:8]]
            t = Table(rows, colWidths=[80 * mm, 48 * mm, 16 * mm, 16 * mm], repeatRows=1)
            t.setStyle(TableStyle([("LINEBELOW", (0, 0), (-1, -1), 0.4, LINE), ("BACKGROUND", (0, 0), (-1, 0), SOFT),
                                   ("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]))
            story.append(t)

    m = result.message
    if m is not None:
        story += [Paragraph("The message", H2)]
        if m.summary:
            story.append(_p(_clean(m.summary, 500)))
        if m.reasoning and m.reasoning.status == "used" and m.reasoning.summary:
            story += [Spacer(1, 3), _p(f"Reasoning model ({m.reasoning.model}{', run on this computer' if m.reasoning.local else ''}): {_clean(m.reasoning.summary, 500)}", SMALL)]
        if m.official_contact:
            story += [Spacer(1, 3), _p(f"Official domains on record for {m.official_contact.organisation}: {', '.join(m.official_contact.domains[:6])}", SMALL)]
        sig = _signals_table(m.signals)
        if sig is not None:
            story += [Spacer(1, 4), sig]

    if result.attachment is not None:
        story += _doc_section(result.attachment)

    steps: list[str] = []
    for src in (m, result.attachment):
        for s in (src.verification_steps if src else []):
            if s not in steps:
                steps.append(s)
    if steps:
        story += [Paragraph("What to do before you pay or reply", H2)] + _list(steps[:8])

    unchecked: list[str] = []
    for src in (m, result.attachment):
        for s in (src.could_not_check if src else []):
            if s not in unchecked:
                unchecked.append(s)
    if unchecked:
        story += [Paragraph("What could not be checked", H2)] + _list(unchecked[:10])
        story.append(_p("Unchecked is not the same as suspicious.", SMALL))

    story += [Spacer(1, 10), HRFlowable(width="100%", thickness=0.6, color=LINE, spaceAfter=6),
              _p("How the score works: the verdict comes from transparent rules. The score sits inside that verdict's range and rises with the "
                 "combined weight of the warning signs. A reasoning model can add concerns but never lowers a verdict. The full text of the "
                 "message and document is not included in this report, and Epiderm does not store it.", SMALL)]
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return buf.getvalue()
