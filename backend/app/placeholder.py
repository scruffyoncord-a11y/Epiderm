"""Hand-written stand-in results so the UI can be built before the engine exists.

Every result is flagged is_placeholder=True and the UI shows a badge. This module
is deleted once the real analyzers and scorer produce Analysis objects.
"""
from .models import (
    Analysis, Band, Category, CheckResult, ConsistencyCheck, Direction, Scenario, Signal,
)


def _sig(id, cat, finding, direction, strength, confidence, evidence="", text=None, phrases=()):
    spans = []
    if text:
        low = text.lower()
        for ph in phrases:
            i = low.find(ph.lower())
            if i >= 0:
                spans.append((i, i + len(ph)))
    return Signal(id=id, category=cat, finding=finding, direction=direction,
                  strength=strength, confidence=confidence, evidence=evidence, spans=spans)


S, R, N, U = Direction.suspicious, Direction.reassuring, Direction.neutral, Direction.unknown
OK, BAD, NA = CheckResult.consistent, CheckResult.inconsistent, CheckResult.cannot_verify

VERIFY_STEPS = [
    "Call the requester on a phone number you already have saved, not the number in this chat.",
    "Check the payment link's domain on the organisation's official website.",
    "Confirm the bank account name with the vendor through a previously known contact.",
    "Ask the requester a question only they would know, or request a live video call.",
    "If anything still looks wrong, hold the payment and report it (cybercrime helpline 1930, cybercrime.gov.in).",
]


def placeholder_analysis(sc: Scenario) -> Analysis:
    chat = sc.event.evidence.chat.text if sc.event.evidence.chat else ""
    base = dict(scenario_id=sc.id, is_placeholder=True)

    if sc.id == "scam_bundle":
        return Analysis(**base, band=Band.verify, trust_score=9, trust_low=4, trust_high=16,
            required_trust=94, impact=0.95,
            signals=[
                _sig("url.lookalike_domain", Category.url, "Link domain imitates the official one", S, 0.9, 0.9, "acmecorp-pay.com vs acmecorp.com"),
                _sig("document.editing_tool", Category.document, "Invoice was made in an image editor", S, 0.8, 0.8, "Producer: Adobe Photoshop 25.0, created 1 day ago"),
                _sig("document.vendor_account_mismatch", Category.document, "Bank account holder does not match the vendor", S, 0.85, 0.85, "Sunrise Traders vs R K Enterprises"),
                _sig("text.secrecy", Category.text, "Asks the reader to keep the request secret", S, 0.8, 0.85, "\"don't discuss this with anyone\"", chat, ["Please don't discuss this with anyone in the team"]),
                _sig("text.urgency", Category.text, "Creates urgency and blocks normal verification", S, 0.7, 0.85, "\"urgent\", \"can't take calls\"", chat, ["I'm in a meeting and can't take calls", "This is urgent"]),
                _sig("device.new_device", Category.device, "Device never seen for this user", S, 0.6, 0.9, "dev-9f3a-unknown"),
                _sig("ip.datacentre_vpn", Category.ip, "Request comes from a datacentre / VPN address", S, 0.6, 0.8, "185.220.101.14 (RO)"),
                _sig("location.mismatch", Category.location, "Browser says India, network says Romania", S, 0.7, 0.8, "IN vs RO"),
                _sig("auth.repeated_failures", Category.auth, "3 failed 2FA attempts before success; SMS method", S, 0.65, 0.85, "3 failures, method sms"),
                _sig("biometric.liveness_failed", Category.biometric, "Face match low and liveness check failed", S, 0.8, 0.7, "match 0.41, liveness false"),
                _sig("behaviour.off_hours_large", Category.behaviour, "Large first-time payment at 3 AM", S, 0.75, 0.8, "Rs 2.4L, usual range 9-19h, typical Rs 18k"),
            ],
            checks=[
                ConsistencyCheck(id="device_location", label="Device vs expected location", result=BAD, detail="Unknown device, foreign network"),
                ConsistencyCheck(id="ip_location", label="IP vs claimed location", result=BAD, detail="RO vs IN"),
                ConsistencyCheck(id="url_org", label="Link vs claimed organisation", result=BAD, detail="Lookalike domain"),
                ConsistencyCheck(id="vendor_account", label="Invoice vendor vs bank account holder", result=BAD, detail="Different names"),
                ConsistencyCheck(id="biometric", label="Face vs enrolled identity", result=BAD, detail="Low match, no liveness"),
                ConsistencyCheck(id="hours", label="Activity time vs usual hours", result=BAD, detail="03:00 vs 09:00-19:00"),
            ],
            could_not_check=["Voice sample (none provided)", "Writing style vs the CFO's past messages"],
            verification_steps=VERIFY_STEPS,
            summary="Many independent signals disagree with this user's normal pattern and with the claimed identity. Hold the payment and verify through a channel you already trust.")

    if sc.id == "legit_traveller":
        return Analysis(**base, band=Band.step_up, trust_score=71, trust_low=64, trust_high=78,
            required_trust=87, impact=0.7,
            signals=[
                _sig("location.new_country", Category.location, "First activity from a new country", S, 0.5, 0.8, "AE; usual: IN"),
                _sig("device.known_device", Category.device, "Known device", R, 0.6, 0.9, "dev-anita-phone"),
                _sig("auth.strong_2fa", Category.auth, "Authenticator-app 2FA passed", R, 0.6, 0.9, "app, 0 failures"),
                _sig("biometric.match_live", Category.biometric, "Face matches and liveness passed", R, 0.7, 0.85, "match 0.93"),
                _sig("behaviour.normal_payment", Category.behaviour, "Known payee, normal amount, working hours", R, 0.5, 0.85, "Rs 18,000 to Zenith"),
                _sig("url.official_domain", Category.url, "Link is on the official domain", R, 0.5, 0.9, "acmecorp.com"),
            ],
            checks=[
                ConsistencyCheck(id="device_location", label="Device vs expected location", result=NA, detail="Known device, new country"),
                ConsistencyCheck(id="ip_location", label="IP vs claimed location", result=OK, detail="AE matches AE"),
                ConsistencyCheck(id="url_org", label="Link vs claimed organisation", result=OK),
                ConsistencyCheck(id="vendor_account", label="Invoice vendor vs bank account holder", result=OK),
                ConsistencyCheck(id="biometric", label="Face vs enrolled identity", result=OK),
                ConsistencyCheck(id="hours", label="Activity time vs usual hours", result=OK),
            ],
            could_not_check=["Travel plans (no itinerary linked)"],
            verification_steps=["Confirm with a quick authenticator prompt or face re-check before releasing the payment."],
            summary="Only the new country is unusual; everything else supports the real user. An extra check is enough. This is not treated as fraud.")

    if sc.id == "clean_request":
        return Analysis(**base, band=Band.allow, trust_score=93, trust_low=88, trust_high=97,
            required_trust=87, impact=0.7,
            signals=[
                _sig("device.known_device", Category.device, "Known device", R, 0.6, 0.9, "dev-anita-laptop"),
                _sig("location.usual_country", Category.location, "Usual country and city", R, 0.5, 0.9, "IN / Kochi"),
                _sig("auth.strong_2fa", Category.auth, "Authenticator-app 2FA passed", R, 0.6, 0.9),
                _sig("biometric.match_live", Category.biometric, "Face matches and liveness passed", R, 0.7, 0.85, "match 0.95"),
                _sig("behaviour.normal_payment", Category.behaviour, "Known payee, normal amount, working hours", R, 0.5, 0.85),
                _sig("url.official_domain", Category.url, "Link is on the official domain", R, 0.5, 0.9),
                _sig("document.genuine_source", Category.document, "Invoice from accounting software", R, 0.4, 0.8, "Tally Prime"),
            ],
            checks=[
                ConsistencyCheck(id="device_location", label="Device vs expected location", result=OK),
                ConsistencyCheck(id="ip_location", label="IP vs claimed location", result=OK),
                ConsistencyCheck(id="url_org", label="Link vs claimed organisation", result=OK),
                ConsistencyCheck(id="vendor_account", label="Invoice vendor vs bank account holder", result=OK),
                ConsistencyCheck(id="biometric", label="Face vs enrolled identity", result=OK),
                ConsistencyCheck(id="hours", label="Activity time vs usual hours", result=OK),
            ],
            could_not_check=[],
            verification_steps=[],
            summary="Everything is consistent with this user's normal pattern.")

    # legit_urgent
    return Analysis(**base, band=Band.step_up, trust_score=78, trust_low=70, trust_high=85,
        required_trust=92, impact=0.85,
        signals=[
            _sig("text.urgency", Category.text, "Urgent tone", S, 0.4, 0.8, "\"urgent\", \"due today\"", chat, ["urgent", "due today"]),
            _sig("device.new_device", Category.device, "Device never seen for this user", S, 0.5, 0.9, "dev-anita-new-tablet"),
            _sig("auth.strong_2fa", Category.auth, "Authenticator-app 2FA passed", R, 0.6, 0.9),
            _sig("biometric.match_live", Category.biometric, "Face matches and liveness passed", R, 0.7, 0.85, "match 0.90"),
            _sig("url.official_domain", Category.url, "Link is on the official domain", R, 0.5, 0.9),
            _sig("document.genuine_source", Category.document, "Invoice from accounting software; vendor matches account", R, 0.5, 0.85, "Tally Prime"),
            _sig("behaviour.known_payee", Category.behaviour, "Known payee; location and time usual", R, 0.4, 0.85),
        ],
        checks=[
            ConsistencyCheck(id="device_location", label="Device vs expected location", result=NA, detail="New device, usual location"),
            ConsistencyCheck(id="ip_location", label="IP vs claimed location", result=OK),
            ConsistencyCheck(id="url_org", label="Link vs claimed organisation", result=OK),
            ConsistencyCheck(id="vendor_account", label="Invoice vendor vs bank account holder", result=OK),
            ConsistencyCheck(id="biometric", label="Face vs enrolled identity", result=OK),
            ConsistencyCheck(id="hours", label="Activity time vs usual hours", result=OK),
        ],
        could_not_check=["Writing style vs the CFO's past messages"],
        verification_steps=["Confirm the request with the CFO on a saved number or in person before releasing Rs 95,000."],
        summary="Urgency and a new device are weak signals, and the amount is large, so one extra check is right. The rest supports a genuine request; this is not treated as fraud.")
