"""
Domain model as plain dataclasses -- no SQLAlchemy, no Pydantic, no external deps.

This is deliberate: the rules engine and ToC cross-validator are the parts of this
platform whose *correctness* actually matters commercially (a wrong PASS is a safety
concern, not just a bug). Keeping them dependent on nothing but the standard library
means they can be unit-tested in any Python environment -- including this sandbox,
where outbound package installs are currently blocked -- with no excuse for "works on
my machine". app/models.py (SQLAlchemy) is a thin persistence adapter that converts
to/from these dataclasses; it never appears in rules/ or toc/ imports.
"""
from __future__ import annotations

from dataclasses import dataclass, field

ELEMENT_TYPES = [
    "Distant Signal", "Inner Distant Signal", "IB Distant Signal", "IB Inner Distant Signal",
    "Mainline Starter", "Loopline Starter", "Intermediate Starter", "Advanced Starter Signal",
    "IB Stop Signal", "Gate Stop Signal", "Calling-on Signal", "Gate Distant Signal",
    "Gate Inner Distant Signal", "Main Home without Junction Route Indicator",
    "Main Home with Junction Route Indicator", "Routing Home without Junction Type Route Indicator",
    "Routing Home with Junction Type Route Indicator", "Advanced Starter-cum-Gate Signal",
    "BSLB Board", "Stop Board/Buffer Stop", "Berthing Track End", "Gate-cum-Distant Signal",
    "Auto Signal (Excludes Gate Stop Signal in Auto Territory)",
    "Semi-Automatic Signal with A-marker lit", "Semi Automatic Signal without A marker lit",
    "Various Home Signals", "Gate Cum IB Distant Signal", "Gate Cum IB Inner Distant Signal",
    "Advanced Starter-cum-Distant Signal", "Gate Stop Signal in Auto Territory",
    "Advance Starter-cum-Gate Inner Distant Signal", "Gate-cum-Inner Distant Signal",
    "Gate Inner Distant-cum-Distant Signal", "IB Signal-cum-Gate Distant Signal",
    "IB Signal-cum-Gate Inner Distant Signal", "IB Signal-cum-Distant Signal",
    "Advanced Starter-cum-IB Distant", "Starter-cum-IB Distant Signal",
    "Various types of Starter Signals", "Advance Starter-cum-Gate Distant Signal",
    "Other Misc Signals",
]
# NOTE: the previous list included non-signal physical elements -- "LC Gate",
# "Turnout/Facing Point", "Marker Board", "Fouling Mark", "LSS" -- that are absent
# from this new signal-focused taxonomy. Nothing in the current rules engine
# strictly requires them (H2.9's gate-tag check works off the linked_element_id
# generically, not off an element_type match), but they were meaningful physical
# elements on a real layout. If dropping them was not intentional, they should be
# re-added alongside this list rather than instead of it.

TAG_TYPES = ["N", "S", "T", "X", "D", "G", "L", "A"]


TAG_TYPE_LABELS = {
    "N": "Normal / Inline section tag",
    "S": "Signal Foot Tag",
    "T": "TIN Discrimination / Turnout Tag",
    "X": "Exit Tag",
    "D": "Dead Stop Tag",
    "G": "LC Gate Tag",
    "L": "Adjacent Line Info Tag",
    "A": "Adjustment / Junction Tag",
}


def requires_signal_foot_tag(element_type: str) -> bool:
    """Whether an Element of this type should have a linked Signal Foot ('S') Tag,
    per Annexure-H clause H2.6 ("Every Main signal, Subsidiary signal, Stop board,
    Ends of berthing track...and BSLB shall be provided with Signal foot tag").

    IMPORTANT -- this is a keyword-based heuristic over the 41-entry signal-type
    taxonomy above, NOT a verbatim mapping confirmed against Annexure-H (which only
    names broad categories, not every one of these specific sub-types). It should
    be treated as a first draft for a signalling domain expert to review, not as
    settled ground truth -- see the classification notes shipped alongside this
    change for exactly which types were included/excluded and why, so it's easy to
    spot and correct anything wrong here.

    Rule of thumb applied: Home signals, Starter signals (including every
    "...-cum-Starter..." combination signal, since the Starter function is itself
    a stop signal even when combined with a Distant function), Stop signals,
    Calling-on signals, Auto/Semi-Automatic signals, Stop Board/Buffer Stop, BSLB,
    and Berthing Track End are treated as requiring a foot tag (they function as
    stop/authority-limit signals). Pure Distant-signal types (including Gate/IB
    Distant combinations that do NOT also include a Starter/Home/Stop function) are
    treated as NOT requiring one, since a Distant signal is cautionary rather than
    a stop signal. "Other Misc Signals" is deliberately excluded (too generic to
    classify safely either way) -- if used, its Signal Foot Tag requirement should
    be confirmed by hand.
    """
    t = element_type
    keywords = ("Home", "Starter", "Stop Signal", "Stop Board", "Buffer Stop",
                "Berthing Track End", "BSLB", "Calling-on", "Calling on",
                "Auto Signal", "Semi-Automatic", "Semi Automatic")
    return any(k in t for k in keywords)


def is_starter_signal_eligible_for_h2_7_exception(element_type: str) -> bool:
    """H2.7's exception ("minimum distance can be less than 150m for Advanced
    Starter or Intermediate Starter") -- broadened from an exact-string match to a
    keyword match so it also covers the various "...-cum-Starter..." combination
    signal types, which still have a genuine Starter function even when combined
    with a Distant/Gate/IB role. Same review caveat as requires_signal_foot_tag()
    above."""
    t = element_type
    return "Starter" in t and ("Advance" in t or "Intermediate" in t)


ROLES = ["designer", "checker", "approver", "project_manager", "config_manager", "admin"]


@dataclass
class User:
    id: int | None
    username: str
    full_name: str
    role: str  # one of ROLES
    email: str = ""
    password_hash: str = ""   # never serialized out to the API
    password_salt: str = ""
    is_active: bool = True


@dataclass
class WorkflowEvent:
    id: int | None
    station_id: int
    from_status: str
    to_status: str
    action: str
    actor_username: str
    actor_role: str
    comment: str = ""
    timestamp: str = ""              # ISO 8601, set by caller so this stays a pure dataclass
    verification_fail_count: int | None = None
    target_username: str | None = None  # e.g. the checker a submission was assigned to


@dataclass
class Station:
    id: int | None = None
    name: str = ""
    kavach_station_id: str = ""
    sip_drawing_number: str = ""
    kavach_version: str = ""   # X
    sip_version: str = ""       # Y
    guideline_version: str = ""  # Z
    drawn_to_scale: bool = True
    not_to_scale_note_present: bool = False
    status: str = "draft"
    created_by: str | None = None  # username of the creator, for self-service deletion
    assigned_checker: str | None = None  # username of the checker this station was submitted to

    @property
    def layout_version(self) -> str:
        if not (self.kavach_version and self.sip_version and self.guideline_version):
            return "INCOMPLETE"
        return f"{self.kavach_version}.{self.sip_version}.{self.guideline_version}"


@dataclass
class Element:
    id: int
    element_ref: str
    element_type: str
    location_m: float
    direction: str | None = None
    remarks: str = ""


@dataclass
class Tag:
    id: int
    tag_ref: str
    tag_type: str
    location_m: float
    tag_number: int | None = None
    direction: str | None = None
    tin_no: int | None = None
    linked_element_id: int | None = None
    is_duplicate: bool = False
    pair_group_id: str | None = None
    legend_shape: str | None = None
    exit_set: str | None = None
    is_border_tag: bool = False  # BRD BR-005 / Annexure-H H2.16 -- station border marker
    remarks: str = ""


@dataclass
class TIN:
    tin_no: int
    section_type: str  # Station / Block
    start_m: float
    end_m: float
    color: str | None = None
    direction: str | None = None
    is_non_kavach_territory: bool = False
    remarks: str = ""


@dataclass
class StationLayout:
    """Convenience bundle for passing a full station's data into the rules engine
    and ToC cross-validator in one call."""
    station: Station
    elements: list[Element] = field(default_factory=list)
    tags: list[Tag] = field(default_factory=list)
    tins: list[TIN] = field(default_factory=list)
