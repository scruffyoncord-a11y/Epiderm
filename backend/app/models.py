"""Shared data contracts for TrustGuard.

Every analyzer returns Signal objects in the same shape, so the scorer, the
explanation UI and the tests never need to know which analyzer produced them.
"""
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class Direction(str, Enum):
    suspicious = "suspicious"
    neutral = "neutral"
    reassuring = "reassuring"
    unknown = "unknown"  # could not be verified; NOT the same as suspicious


class Category(str, Enum):
    ip = "ip"
    device = "device"
    location = "location"
    auth = "auth"
    behaviour = "behaviour"
    text = "text"
    url = "url"
    document = "document"
    biometric = "biometric"


class Band(str, Enum):
    allow = "allow"
    step_up = "step_up"
    verify = "verify"


class Signal(BaseModel):
    id: str = Field(description="Stable machine id, e.g. 'url.lookalike_domain'")
    category: Category
    finding: str = Field(description="Plain-language statement of what was found")
    direction: Direction
    strength: float = Field(ge=0, le=1, description="How strongly this points in its direction")
    confidence: float = Field(ge=0, le=1, description="How sure we are the finding is correct")
    evidence: str = Field(default="", description="The concrete data behind the finding")
    spans: list[tuple[int, int]] = Field(default_factory=list, description="Char ranges in the chat text to highlight")


class CheckResult(str, Enum):
    consistent = "consistent"
    inconsistent = "inconsistent"
    cannot_verify = "cannot_verify"


class ConsistencyCheck(BaseModel):
    id: str
    label: str
    result: CheckResult
    detail: str = ""


# ---------------------------------------------------------------- event input

class ActionType(str, Enum):
    view = "view"
    profile_change = "profile_change"
    payment = "payment"


class Action(BaseModel):
    type: ActionType
    amount: Optional[float] = None
    payee: Optional[str] = None
    payee_account_holder: Optional[str] = None


class Session(BaseModel):
    ip: str
    ip_country: str
    ip_is_vpn: bool = False
    ip_is_datacentre: bool = False
    device_id: str
    device_is_emulator: bool = False
    location_country: str = Field(description="Country the browser/timezone claims")
    location_city: Optional[str] = None
    hour_local: int = Field(ge=0, le=23)
    minutes_since_last_login: Optional[int] = None


class TwoFA(BaseModel):
    status: str = Field(description="passed | failed | skipped")
    method: str = Field(default="none", description="app | passkey | sms | none")
    failed_attempts: int = 0


class Biometric(BaseModel):
    match_score: Optional[float] = Field(default=None, ge=0, le=1)
    liveness: Optional[bool] = None


class Auth(BaseModel):
    twofa: TwoFA
    biometric: Biometric = Biometric()


class Chat(BaseModel):
    sender_claimed: str
    text: str


class UrlEvidence(BaseModel):
    url: str
    claimed_org: str


class Invoice(BaseModel):
    vendor_name: str
    account_holder: str
    creator_tool: Optional[str] = None
    created_days_ago: Optional[int] = None
    modified_days_ago: Optional[int] = None


class Evidence(BaseModel):
    chat: Optional[Chat] = None
    url: Optional[UrlEvidence] = None
    invoice: Optional[Invoice] = None


class Event(BaseModel):
    user_id: str
    action: Action
    session: Session
    auth: Auth
    evidence: Evidence = Evidence()


# ------------------------------------------------------------- scenario files

class Expected(BaseModel):
    band: Band
    rationale: str
    must_flag: list[str] = Field(default_factory=list, description="Signal ids that must appear as suspicious")
    must_not_flag: list[str] = Field(default_factory=list, description="Signal ids that must NOT be suspicious")


class Scenario(BaseModel):
    id: str
    title: str
    description: str
    simulated: bool = True
    event: Event
    expected: Expected


# ----------------------------------------------------------------- analysis output

class DocumentReport(BaseModel):
    filename: str
    format: str = Field(description="pdf | docx | xlsx | pptx | image | unknown")
    size_bytes: int
    fields: dict[str, str] = Field(default_factory=dict, description="What the file says about itself")
    signals: list[Signal]
    could_not_check: list[str] = Field(default_factory=list)
    summary: str = ""


class ReasoningInfo(BaseModel):
    """What the reasoning model contributed, shown to the user before the scored result."""
    status: str = Field(description="used | unavailable | failed")
    model: Optional[str] = None
    provider: Optional[str] = Field(default=None, description="anthropic | ollama")
    local: bool = Field(default=False, description="True when the text never left this machine")
    note: str = Field(default="", description="Why it was not used, or a caveat")
    summary: str = ""
    concern: Optional[str] = Field(default=None, description="Advisory only: low | medium | high. Never sets the band.")
    claimed_identity: Optional[str] = None
    request_type: Optional[str] = None
    inconsistencies: list[str] = Field(default_factory=list)
    innocent_explanations: list[str] = Field(default_factory=list)
    unknowns: list[str] = Field(default_factory=list)


class Analysis(BaseModel):
    scenario_id: Optional[str] = None
    band: Band
    trust_score: int = Field(ge=0, le=100)
    trust_low: int
    trust_high: int
    required_trust: int
    impact: float
    signals: list[Signal]
    checks: list[ConsistencyCheck]
    could_not_check: list[str]
    verification_steps: list[str] = Field(default_factory=list)
    summary: str = ""
    reasoning: Optional[ReasoningInfo] = None
    is_placeholder: bool = Field(default=False, description="True while results are hand-written stand-ins, not engine output")
