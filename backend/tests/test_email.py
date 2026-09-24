from types import SimpleNamespace

from fastapi.testclient import TestClient

import app.reasoning as r
from app.analyzers.email import analyze_sender, find_org, load_directory, parse_email
from app.main import app
from app.models import Band, Direction
from app.reasoning import Assessment, Concern, RequestType

DIRECTORY = load_directory()
client = TestClient(app)
SUS, REASSURING = Direction.suspicious, Direction.reassuring


def ids(res, direction=None):
    sigs = res.signals if hasattr(res, "signals") else res
    return {s.id.removeprefix("email.") for s in sigs if direction is None or s.direction == direction}


# ------------------------------------------------------------------ the analyzer

def test_official_sounding_message_from_gmail_is_flagged():
    res = analyze_sender("acme.support@gmail.com", "Acme Corp", "This is Acme Corp support", DIRECTORY)
    assert "free_provider" in ids(res, SUS)


def test_an_individual_using_gmail_is_normal():
    res = analyze_sender("priya123@gmail.com", None, "Hey, are we still on for lunch?", DIRECTORY)
    assert ids(res, SUS) == set() and "free_provider_neutral" in ids(res)


def test_official_domain_and_subdomain_are_reassuring_but_never_proof():
    for addr in ("billing@acmecorp.com", "no-reply@mail.acmecorp.com"):
        res = analyze_sender(addr, "Acme Corp", "invoice", DIRECTORY)
        assert ids(res, REASSURING) == {"domain_matches_official"}
    sig = analyze_sender("billing@acmecorp.com", "Acme Corp", "", DIRECTORY).signals[0]
    assert "forged" in sig.finding and sig.strength <= 0.5


def test_lookalike_domains_are_flagged_strongly():
    for addr in ("pay@acmecorp-pay.com", "pay@acmecorp.co", "pay@acmecorp.com.evil.net", "pay@acmec0rp.com", "pay@acmecorpp.com"):
        res = analyze_sender(addr, "Acme Corp", "", DIRECTORY)
        assert "lookalike_domain" in ids(res, SUS), addr
    assert next(s for s in res.signals if s.id == "email.lookalike_domain").strength >= 0.8


def test_unrelated_domain_is_flagged_as_not_on_record():
    res = analyze_sender("hello@totally-different.org", "Acme Corp", "", DIRECTORY)
    assert ids(res, SUS) == {"domain_not_official"}


def test_unknown_company_is_unknown_never_invented():
    res = analyze_sender("hr@somecompany.in", "Zylophone Industries", "", DIRECTORY)
    assert res.org is None
    assert ids(res, Direction.unknown) == {"org_unknown"}
    assert ids(res, SUS) == set()
    assert "do not use contact details from the message" in res.signals[0].finding


def test_government_claim_needs_a_government_domain():
    bad = analyze_sender("officer.kumar@gmail.com", None, "This is Officer Kumar from the cyber crime police", DIRECTORY)
    assert "gov_claim_non_gov" in ids(bad, SUS)
    ok = analyze_sender("officer@delhipolice.gov.in", None, "This is the police", DIRECTORY)
    assert "gov_claim_non_gov" not in ids(ok)
    rbi = analyze_sender("notice@rbi.org.in", "RBI", "Reserve Bank notice", DIRECTORY)
    assert "gov_claim_non_gov" not in ids(rbi) and "domain_matches_official" in ids(rbi, REASSURING)


def test_directory_matching_is_exact_not_fuzzy():
    assert find_org("Amazon India", DIRECTORY).name == "Amazon"
    assert find_org("Acmecorp Pvt Ltd", DIRECTORY).name.startswith("Acme")
    assert find_org("Amazon Web Foo", DIRECTORY) is None
    assert find_org("", DIRECTORY) is None and find_org(None, DIRECTORY) is None


def test_invalid_addresses_are_unknown():
    for bad in ("not-an-email", "a@b", "x" * 300 + "@gmail.com", "two@@gmail.com"):
        res = analyze_sender(bad, "Acme Corp", "", DIRECTORY)
        assert ids(res, Direction.unknown) == {"invalid"}, bad
    assert parse_email(" <Boss@Gmail.com> ") == ("Boss", "gmail.com")


def test_directory_file_carries_a_notice_and_no_free_provider_domains():
    import json
    from app.analyzers.email import DIRECTORY_FILE, FREE_PROVIDERS
    raw = json.loads(DIRECTORY_FILE.read_text(encoding="utf8"))
    assert "NOT exhaustive" in raw["_notice"] and "AI never supplies" in raw["_notice"]
    for org in raw["organisations"]:
        assert not set(d.lower() for d in org["domains"]) & FREE_PROVIDERS


# ------------------------------------------------------------------ in the pipeline

SCAM = ("Hi, this is Rahul from the Acme Corp CFO office. I'm in a meeting and can't take calls. "
        "Urgent: transfer Rs 2,40,000 today and don't tell anyone.")


def fake_provider(monkeypatch, org="Acme Corp"):
    a = Assessment(claimed_identity="Rahul, CFO", claimed_organisation=org, request_type=RequestType.payment, tactics=[],
                   inconsistencies=[], innocent_explanations=[], unknowns=[], concern=Concern.high, summary="Scam-like.")
    calls = []

    def ask(client, text):
        calls.append(text)
        return a, ""

    monkeypatch.setattr(r, "_ask_model", ask)
    return calls


def test_model_supplies_the_company_name_and_the_directory_supplies_the_facts(monkeypatch):
    fake_provider(monkeypatch)
    a = r.analyze_with_reasoning(SCAM, client=SimpleNamespace(), sender_email="rahul.acme@gmail.com")
    assert "email.free_provider" in {s.id for s in a.signals if s.direction == SUS}
    assert a.official_contact.organisation.startswith("Acme") and a.official_contact.domains == ["acmecorp.com"]


def test_a_company_the_model_names_but_we_do_not_know_gets_no_official_contact(monkeypatch):
    fake_provider(monkeypatch, org="Zylophone Industries")
    a = r.analyze_with_reasoning(SCAM, client=SimpleNamespace(), sender_email="hr@zylophone.in")
    assert a.official_contact is None
    assert any(s.id == "email.org_unknown" for s in a.signals)


def test_gmail_sender_lowers_trust_on_a_scam_like_message(monkeypatch):
    fake_provider(monkeypatch)
    without = r.analyze_with_reasoning(SCAM, client=SimpleNamespace())
    with_gmail = r.analyze_with_reasoning(SCAM, client=SimpleNamespace(), sender_email="rahul.acme@gmail.com")
    assert with_gmail.trust_score <= without.trust_score and with_gmail.band == Band.verify


def test_it_asks_for_the_sender_address_when_none_was_given(monkeypatch):
    fake_provider(monkeypatch)
    a = r.analyze_with_reasoning(SCAM, client=SimpleNamespace())
    assert [f.id for f in a.follow_ups] == ["sender_email"] and "Gmail" in a.follow_ups[0].question
    b = r.analyze_with_reasoning(SCAM, client=SimpleNamespace(), sender_email="rahul@acmecorp.com")
    assert b.follow_ups == []
    fake_provider(monkeypatch, org=None)  # a message that names no company
    plain = r.analyze_with_reasoning("Lunch at one on Friday?", client=SimpleNamespace())
    assert plain.follow_ups == []


def test_it_asks_for_the_company_when_only_an_address_is_known(monkeypatch):
    fake_provider(monkeypatch, org=None)
    a = r.analyze_with_reasoning("Please review the attached.", client=SimpleNamespace(), sender_email="x@gmail.com")
    assert [f.id for f in a.follow_ups] == ["organisation"]


def test_an_address_inside_the_message_is_checked_but_labelled(monkeypatch):
    fake_provider(monkeypatch)
    a = r.analyze_with_reasoning("Acme Corp support: reply to acme.helpdesk@gmail.com to claim your refund.", client=SimpleNamespace())
    sig = next(s for s in a.signals if s.id == "email.free_provider")
    assert "found in the message text" in sig.evidence


def test_rechecking_with_an_address_reuses_the_models_reading(monkeypatch):
    calls = fake_provider(monkeypatch)
    r._CACHE.clear()
    r.analyze_with_reasoning(SCAM, client=SimpleNamespace(), use_cache=True)
    r.analyze_with_reasoning(SCAM, client=SimpleNamespace(), sender_email="a@gmail.com", use_cache=True)
    assert len(calls) == 1
    r.analyze_with_reasoning("a different message", client=SimpleNamespace(), use_cache=True)
    assert len(calls) == 2


def test_no_model_still_checks_the_address(monkeypatch):
    a = r.analyze_with_reasoning("This is the Acme Corp billing team, please pay today.", sender_email="acme.billing@gmail.com",
                                 organisation="Acme Corp")
    assert a.reasoning.status == "unavailable"
    assert "email.free_provider" in {s.id for s in a.signals if s.direction == SUS}


def test_prompt_forbids_the_model_from_inventing_contact_details():
    assert "Never state or guess any email address" in r.SYSTEM_PROMPT


def test_endpoint_accepts_the_new_fields_and_limits_them():
    body = client.post("/analyze-text", json={"text": "Acme Corp support here, pay now", "sender_email": "acme@gmail.com",
                                              "organisation": "Acme Corp"}).json()
    assert any(s["id"] == "email.free_provider" for s in body["signals"])
    assert body["official_contact"]["domains"] == ["acmecorp.com"]
    assert client.post("/analyze-text", json={"text": "hi", "sender_email": "a" * 300}).status_code == 422


def test_company_named_in_the_text_is_found_without_the_model(monkeypatch):
    """Regression: Gemma returned no company for 'Rahul from Acme Corp finance', so no follow-up was asked."""
    fake_provider(monkeypatch, org=None)
    text = "Hi, this is Rahul from Acme Corp finance. I'm in a meeting and can't take calls. Urgent: transfer Rs 2,40,000 today."
    a = r.analyze_with_reasoning(text, client=SimpleNamespace())
    assert [f.id for f in a.follow_ups] == ["sender_email"]
    b = r.analyze_with_reasoning(text, client=SimpleNamespace(), sender_email="rahul@gmail.com")
    assert "email.free_provider" in {s.id for s in b.signals if s.direction == SUS}
    assert b.official_contact.domains == ["acmecorp.com"]


def test_directory_mentions_are_whole_words_only():
    from app.analyzers.email import find_org_mention
    assert find_org_mention("Your Amazon order is late", DIRECTORY).name == "Amazon"
    assert find_org_mention("Visit the Amazonian rainforest", DIRECTORY) is None
    assert find_org_mention("my hdfcbankish note", DIRECTORY) is None


def test_follow_up_is_asked_for_flagged_or_identity_claiming_messages_but_not_for_chat(monkeypatch):
    fake_provider(monkeypatch, org=None)
    flagged = r.analyze_with_reasoning("Send the money now and keep this between us.", client=SimpleNamespace())
    assert [f.id for f in flagged.follow_ups] == ["sender_email"]
    claiming = r.analyze_with_reasoning("Hello, this is Priya from the payments desk.", client=SimpleNamespace())
    assert [f.id for f in claiming.follow_ups] == ["sender_email"]
    chat = r.analyze_with_reasoning("Are we still on for lunch on Friday?", client=SimpleNamespace())
    assert chat.follow_ups == []


def test_identity_claim_pattern_matches_whole_words_only(monkeypatch):
    from app.analyzers.email import IDENTITY_CLAIM
    assert IDENTITY_CLAIM.search("Hi, this is Rahul from Acme Corp")
    assert IDENTITY_CLAIM.search("I'm writing on behalf of the bank")
    for benign in ("This is a great offer, thanks", "I am so glad it went well", "That is what I wanted to say"):
        assert not IDENTITY_CLAIM.search(benign), benign
    fake_provider(monkeypatch, org=None)
    assert r.analyze_with_reasoning("This is a great offer, thanks", client=SimpleNamespace()).follow_ups == []
