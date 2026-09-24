import time

from fastapi.testclient import TestClient

import app.reasoning as r
from app.analyzers.headers import MAX_HEADER_CHARS, header_signals, parse_headers, same_organisation
from app.analyzers.ip import analyze_ip
from app.main import app
from app.models import Band, Direction

client = TestClient(app)
SUS, REASSURING = Direction.suspicious, Direction.reassuring
RECIPIENT = "recipient@example.com"

# The shape of a real Gmail "Show original" raw header block (a newsletter that passes every check).
# The recipient's address is a placeholder; long signature values are shortened.
GMAIL_RAW = f"""Delivered-To: {RECIPIENT}
Received: by 2002:a05:6214:5843:b0:90c:8112:305 with SMTP id ml3csp10069808qvb;
        Wed, 23 Sep 2026 02:51:33 -0700 (PDT)
ARC-Authentication-Results: i=1; mx.google.com; dkim=pass header.i=@info.bigbasket.com header.s=nc2048 header.b=tQjfZTm1;
       dkim=pass header.i=@env.etransmail.com header.s=fnc header.b=jShek05q;
       spf=pass (google.com: domain of 17901027733040782-33104-1-gmail.com@env.info.bigbasket.com designates 202.162.237.215 as permitted sender) smtp.mailfrom=17901027733040782-33104-1-gmail.com@env.info.bigbasket.com;
       dmarc=pass (p=REJECT sp=REJECT dis=NONE) header.from=info.bigbasket.com
Return-Path: <17901027733040782-33104-1-gmail.com@env.info.bigbasket.com>
Received: from 215.edm.info.bigbasket.com (215.edm.info.bigbasket.com. [202.162.237.215])
        by mx.google.com with ESMTPS id d75a77b69052e-532eaecc67bsi19055751cf.299.2026.09.23.02.51.32
        for <{RECIPIENT}>
        (version=TLS1_3 cipher=TLS_AES_256_GCM_SHA384 bits=256/256);
        Wed, 23 Sep 2026 02:51:33 -0700 (PDT)
Received-SPF: pass (google.com: domain of 17901027733040782-33104-1-gmail.com@env.info.bigbasket.com designates 202.162.237.215 as permitted sender) client-ip=202.162.237.215;
Authentication-Results: mx.google.com;
       dkim=pass header.i=@info.bigbasket.com header.s=nc2048 header.b=tQjfZTm1;
       dkim=pass header.i=@env.etransmail.com header.s=fnc header.b=jShek05q;
       spf=pass (google.com: domain of 17901027733040782-33104-1-gmail.com@env.info.bigbasket.com designates 202.162.237.215 as permitted sender) smtp.mailfrom=17901027733040782-33104-1-gmail.com@env.info.bigbasket.com;
       dmarc=pass (p=REJECT sp=REJECT dis=NONE) header.from=info.bigbasket.com
From: bigbasket <alert@info.bigbasket.com>
To: {RECIPIENT}
MIME-Version: 1.0
Subject: =?utf-8?q?Questions_about_organic_produce=2C_Rahul=3F_=F0=9F=A7=90?=
"""

GMAIL_SUMMARY = f"""Original Message
Message ID	<20260923094725.166AEC00009F@smtpgcus-27-rl.pepipost.com>
Created at:	Wed, Sep 23, 2026 at 3:21 PM (Delivered after 1 second)
From:	bigbasket <alert@info.bigbasket.com> Using NetcoreCloud Mailer
To:	{RECIPIENT}
Subject:	Questions about organic produce, Rahul?
SPF:	PASS with IP 202.162.237.215 Learn more
DKIM:	'PASS' with domain info.bigbasket.com Learn more
DMARC:	'PASS' Learn more
"""


def fail_headers(from_line="From: Acme Billing <billing@acmecorp-pay.com>", extra=""):
    return f"""Authentication-Results: mx.google.com; dkim=fail header.i=@acmecorp-pay.com; spf=fail smtp.mailfrom=billing@acmecorp-pay.com; dmarc=fail (p=NONE) header.from=acmecorp-pay.com
Received: from unknown (mail.evil.example [9.9.9.9]) by mx.google.com
{from_line}
{extra}Subject: Invoice overdue
"""


class FakeResolver:
    def __init__(self, ptr=None, forward=None):
        self.ptr, self.fwd = ptr, forward or []

    def reverse(self, ip):
        return self.ptr

    def forward(self, name):
        return self.fwd


def ids(sigs, direction=None):
    return {s.id.removeprefix("email.").removeprefix("ip.") for s in sigs if direction is None or s.direction == direction}


# ------------------------------------------------------------------ parsing

def test_real_gmail_raw_headers_are_read_correctly():
    i = parse_headers(GMAIL_RAW)
    assert (i.from_display, i.from_email) == ("bigbasket", "alert@info.bigbasket.com")
    assert (i.spf, i.dkim, i.dmarc) == ("pass", "pass", "pass")
    assert i.sending_ip == "202.162.237.215"
    assert i.return_path.endswith("@env.info.bigbasket.com")
    assert i.subject == "Questions about organic produce, Rahul? \U0001F9D0"  # encoded subject is decoded


def test_gmail_summary_block_is_read_correctly():
    i = parse_headers(GMAIL_SUMMARY)
    assert (i.from_email, i.spf, i.dkim, i.dmarc, i.sending_ip) == ("alert@info.bigbasket.com", "pass", "pass", "pass", "202.162.237.215")
    assert i.dkim_domain == "info.bigbasket.com"


def test_sending_ip_falls_back_to_the_earliest_received_line_and_ignores_private_addresses():
    raw = """Received: from a (a.example [10.0.0.5]) by b
Received: from mid (mid.example [1.1.1.1]) by mx
Received: from origin (origin.example [9.9.9.9]) by relay
From: x@example.org
"""
    assert parse_headers(raw).sending_ip == "9.9.9.9"  # the last Received header is the earliest hop
    assert parse_headers("Received: from a ([192.168.1.4]) by b\nFrom: x@example.org\n").sending_ip is None


def test_folded_lines_and_windows_line_endings_are_handled():
    raw = "Authentication-Results: mx.google.com;\r\n       spf=fail smtp.mailfrom=x@y.com;\r\n       dmarc=fail header.from=y.com\r\nFrom: x@y.com\r\n"
    i = parse_headers(raw)
    assert (i.spf, i.dmarc) == ("fail", "fail")


def test_garbage_and_oversized_input_do_not_crash_or_hang():
    assert parse_headers("").found_anything is False
    assert "headers_unreadable" in ids(header_signals(parse_headers("hello, just some text")))
    start = time.time()
    for blob in ("a" * (MAX_HEADER_CHARS * 3), "Received: " + "[" * 50_000, ("From: " + "<" * 20_000 + "\n") * 5, "\n ".join(["x"] * 50_000)):
        parse_headers(blob)
    assert time.time() - start < 5


# ------------------------------------------------------------------ signals

def test_all_three_passing_is_mildly_reassuring_and_says_it_is_not_proof():
    sigs = header_signals(parse_headers(GMAIL_RAW))
    assert ids(sigs, REASSURING) == {"auth_pass"} and ids(sigs, SUS) == set()
    s = next(x for x in sigs if x.id == "email.auth_pass")
    assert s.strength <= 0.4 and "does not show the content is honest" in s.finding


def test_failures_are_strong_signals():
    sigs = header_signals(parse_headers(fail_headers()))
    assert {"spf_fail", "dkim_fail", "dmarc_fail"} <= ids(sigs, SUS)
    assert next(s for s in sigs if s.id == "email.dmarc_fail").strength >= 0.8


def test_reply_to_mismatch_and_free_provider_reply_to():
    raw = "Authentication-Results: mx; spf=pass; dkim=pass; dmarc=pass\nFrom: Acme <billing@acmecorp.com>\nReply-To: acme.refunds@gmail.com\n"
    s = next(x for x in header_signals(parse_headers(raw)) if x.id == "email.reply_to_mismatch")
    assert s.strength >= 0.7 and "free email account" in s.finding
    same = "Authentication-Results: mx; spf=pass; dkim=pass; dmarc=pass\nFrom: a@info.acmecorp.com\nReply-To: support@acmecorp.com\n"
    assert "reply_to_mismatch" not in ids(header_signals(parse_headers(same)))
    assert same_organisation("mail.example.co.in", "example.co.in") and not same_organisation("example.com", "example.org")


def test_missing_authentication_results_are_unknown_not_suspicious():
    sigs = header_signals(parse_headers("From: a@b.com\nSubject: hi\n"))
    assert ids(sigs, Direction.unknown) == {"auth_missing"} and ids(sigs, SUS) == set()


# ------------------------------------------------------------------ mail-server rDNS rules

def test_mail_context_treats_hosting_names_as_normal_but_flags_home_connections_and_missing_rdns():
    host = analyze_ip("8.8.4.4", FakeResolver("smtp-out.mailer-service.com", ["8.8.4.4"]), context="mail")
    assert ids(host.signals, SUS) == set()
    aws = analyze_ip("8.8.4.4", FakeResolver("ec2-8-8-4-4.compute-1.amazonaws.com", ["8.8.4.4"]), context="mail")
    assert ids(aws.signals, SUS) == set()  # cloud mail is normal; in "sender" context the same name IS flagged
    assert "rdns_hosting" in ids(analyze_ip("8.8.4.4", FakeResolver("ec2-8-8-4-4.compute-1.amazonaws.com", ["8.8.4.4"])).signals, SUS)
    home = analyze_ip("8.8.4.4", FakeResolver("dynamic-8-8-4-4.broadband.example.in", ["8.8.4.4"]), context="mail")
    assert "mail_from_home" in ids(home.signals, SUS)
    assert "mail_no_rdns" in ids(analyze_ip("8.8.4.4", FakeResolver(None), context="mail").signals, SUS)
    assert "mail_rdns_unconfirmed" in ids(analyze_ip("8.8.4.4", FakeResolver("mail.example.net", ["1.2.3.4"]), context="mail").signals, SUS)
    tor = analyze_ip("8.8.4.4", FakeResolver("tor-exit-1.example.org", ["8.8.4.4"]), context="mail")
    assert "rdns_anonymiser" in ids(tor.signals, SUS)


# ------------------------------------------------------------------ the pipeline

BIGBASKET = FakeResolver("215.edm.info.bigbasket.com", ["202.162.237.215"])


def test_a_genuine_newsletter_passes_cleanly_with_headers_only():
    a = r.analyze_with_reasoning("", headers=GMAIL_RAW, resolver=BIGBASKET)
    assert a.band == Band.allow
    assert not [s for s in a.signals if s.direction == SUS]
    assert a.reasoning.status == "unavailable" and "No message text was given" in a.reasoning.note
    assert a.header_summary.sending_ip == "202.162.237.215" and a.header_summary.sending_host == "215.edm.info.bigbasket.com"
    assert a.header_summary.spf == "pass" and a.header_summary.subject.startswith("Questions about organic produce")
    assert any(s.id == "ip.mail_server_named" for s in a.signals)


def test_the_recipients_address_and_raw_headers_are_never_returned():
    a = r.analyze_with_reasoning("", headers=GMAIL_RAW, resolver=BIGBASKET)
    dump = a.model_dump_json()
    assert RECIPIENT not in dump and "Delivered-To" not in dump and "ARC-Seal" not in dump


def test_forged_sender_with_failed_authentication_is_held():
    a = r.analyze_with_reasoning("Your invoice is overdue, pay today.", headers=fail_headers(), resolver=FakeResolver("mail.evil.example", ["9.9.9.9"]))
    sus = {s.id for s in a.signals if s.direction == SUS}
    assert {"email.spf_fail", "email.dmarc_fail", "email.dkim_fail"} <= sus
    assert a.band == Band.verify


def test_display_name_of_a_known_company_on_the_wrong_domain_is_caught_but_people_are_not_flagged():
    spoof = "Authentication-Results: mx; spf=pass; dkim=pass; dmarc=pass\nFrom: Amazon Support <help@amzn-support-desk.com>\n"
    a = r.analyze_with_reasoning("", headers=spoof, resolver=FakeResolver(None))
    assert {"email.lookalike_domain", "email.domain_not_official"} & {s.id for s in a.signals if s.direction == SUS}
    person = "Authentication-Results: mx; spf=pass; dkim=pass; dmarc=pass\nFrom: Rahul Kumar <rahul.kumar@gmail.com>\n"
    b = r.analyze_with_reasoning("", headers=person, resolver=FakeResolver(None))
    assert not any(s.id == "email.free_provider" for s in b.signals)


def test_an_ip_typed_by_the_user_wins_over_the_one_in_the_headers():
    a = r.analyze_with_reasoning("", headers=GMAIL_RAW, ip="185.220.101.14", resolver=FakeResolver("tor-exit-1.example.org", ["185.220.101.14"]))
    assert any(s.id == "ip.rdns_anonymiser" for s in a.signals)


def test_endpoint_accepts_headers_alone_and_validates(monkeypatch):
    monkeypatch.setattr(r, "analyze_ip", lambda ip, resolver=None, **kw: analyze_ip(ip, BIGBASKET, **kw))  # no real DNS in tests
    ok = client.post("/analyze-text", json={"headers": GMAIL_SUMMARY})
    assert ok.status_code == 200 and ok.json()["header_summary"]["from_email"] == "alert@info.bigbasket.com"
    assert RECIPIENT not in ok.text
    assert client.post("/analyze-text", json={"text": "", "headers": "   "}).status_code == 422
    assert client.post("/analyze-text", json={"headers": "x" * 70_000}).status_code == 422
