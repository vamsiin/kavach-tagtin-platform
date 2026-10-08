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

SIGNAL_ELEMENT_TYPES = [
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
    "Shunt Signal", "Other Misc Signals",
]
# Physical, non-signal elements a layout must show (Annexure-H H2.9, H2.10, H2.22,
# H2.27): LC gates, points/turnouts (switch location), fouling marks, IB/other marker
# boards, axle counters and whistle boards (the W/L alternative in H2.9). BSLB, stop
# boards and berthing-track ends are already in the list above.
LC_GATE = "LC Gate"
POINTS = "Points / Turnout"
NON_SIGNAL_ELEMENT_TYPES = [
    LC_GATE, POINTS, "Fouling Mark", "Marker Board", "Axle Counter", "Whistle Board (W/L)",
]
ELEMENT_TYPES = SIGNAL_ELEMENT_TYPES + NON_SIGNAL_ELEMENT_TYPES

LC_CLASSES = ["Special", "A", "B", "C", "D"]
LC_MANNING = ["Manned interlocked", "Manned non-interlocked", "Unmanned"]

# Track / line model (step 2 of the Annexure-H plan). A station's layout is a set
# of named lines (DN MAIN, UP MAIN, COMMON LOOP, sidings, block lines) joined by
# points. Elements, tags and TINs are placed on a line.
TRACK_TYPES = ["Main", "Loop", "Siding", "Block", "Other"]

# Line-type classification (QFTL requirement, Oct 2026): the five running lines get
# their own class; every other line -- sidings, goods / tower-wagon lines, IB block
# lines that are not one of the five -- is OTHER.
LINE_TYPES = ["UP MAIN", "DN MAIN", "UP LOOP", "DN LOOP", "COMMON LOOP", "OTHER"]


def guess_line_type(name: str | None) -> str:
    """Line type from a line's name as written on the layout: 'DN MAIN', 'DN.MAIN',
    'Up Loop 2', 'DOWN MAIN' ... -> the class; anything else -> OTHER."""
    import re
    n = re.sub(r"[\s._\-]+", " ", (name or "").upper()).strip()
    n = re.sub(r"^DOWN ", "DN ", n)
    n = re.sub(r" LINE$", "", n)
    for lt in LINE_TYPES[:-1]:
        if n == lt or re.match(rf"^{lt}( ?(NO\.? ?)?\d+)?$", n):
            return lt
    return "OTHER"


def expected_line_direction(line_type: str | None, dn_direction: str = "Nominal") -> str | None:
    """Direction a line of this type normally runs, by the zone's convention
    (SCR: DN = Nominal; ECR: DN = Reverse). COMMON LOOP runs both ways; OTHER: none."""
    other = "Reverse" if dn_direction == "Nominal" else "Nominal"
    if line_type in ("DN MAIN", "DN LOOP"):
        return dn_direction
    if line_type in ("UP MAIN", "UP LOOP"):
        return other
    if line_type == "COMMON LOOP":
        return "Both"
    return None
LINE_CONFIGS = ["Single", "Double", "Multiple"]


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
    Calling-on signals, Shunt signals (QFTL 26.09.2026: every signal, stop board and
    shunt signal has its own S tag; a dependent shunt signal shares its main signal's),
    Auto/Semi-Automatic signals, Stop Board/Buffer Stop, BSLB,
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
                "Auto Signal", "Semi-Automatic", "Semi Automatic", "Shunt")
    return any(k in t for k in keywords)


# What a tag of each type is placed FOR -- the element its "linked element" should be.
LINK_HINTS = {
    "S": "the signal, stop board, BSLB or shunt signal this foot tag is at",
    "T": "the points / turnout this TIN-discrimination tag is for",
    "G": "the LC gate this gate tag protects",
    "L": "the last stop signal (Advanced Starter) the adjacent-line tag follows",
    "D": "the points or dead end this dead-stop tag protects",
    "X": "the points leading to the siding / non-KAVACH line",
    "N": "optional: the signal this approach tag announces",
    "A": "optional",
}


def suitable_link(tag_type: str, element_type: str) -> bool:
    """Whether an element of this type is a sensible 'linked element' for the tag."""
    if tag_type == "S":
        return requires_signal_foot_tag(element_type)
    if tag_type in ("T", "X"):
        return element_type == POINTS
    if tag_type == "G":
        return element_type == LC_GATE
    if tag_type == "L":
        return "Starter" in element_type or "Stop Signal" in element_type
    if tag_type == "D":
        return element_type in (POINTS, "Stop Board/Buffer Stop", "Berthing Track End")
    if tag_type == "N":
        return element_type in SIGNAL_ELEMENT_TYPES
    return True


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
class Track:
    id: int
    name: str                   # as written on the layout, e.g. "DN MAIN", "COMMON LOOP"
    track_type: str             # one of TRACK_TYPES
    start_m: float
    end_m: float
    direction: str | None = None   # normal direction of travel, if any
    is_kavach: bool = True         # False = non-KAVACH line (shown white, H2.18)
    remarks: str = ""
    line_type: str = "OTHER"       # one of LINE_TYPES


@dataclass
class StationBorder:
    """Border line location on one line (H2.16). On a double line the border with a
    neighbour usually lies at a different chainage on each line, each marked by its
    own border tag."""
    line_label: str                  # as on the layout, e.g. "DN line", "UP line"
    border_m: float
    border_tag_ref: str = ""
    track_id: int | None = None      # this station's line
    neighbour_line: str = ""         # the line it continues as at the neighbour, e.g. "DN MAIN"


def line_config_from_borders(borders) -> str | None:
    """Section line configuration derived from the line-wise border mapping: one line
    crossing the border = Single, two = Double, more = Multiple."""
    lines = {(b.track_id if b.track_id is not None else (b.line_label or "").strip().lower()) for b in borders}
    lines.discard("")
    if not lines:
        return None
    return "Single" if len(lines) == 1 else "Double" if len(lines) == 2 else "Multiple"


@dataclass
class AdjacentStation:
    """A neighbouring station on one side of this one: where the border between the
    two lies (H2.16) and whether the section between them is single or double line
    (H2.22)."""
    id: int
    name: str
    side: str                        # direction towards it, e.g. "Nominal" / "Reverse"
    kavach_station_id: str = ""
    border_m: float | None = None    # absolute location of the station border line
    distance_m: float | None = None  # centre line to centre line, as on the layout
    line_config: str | None = None   # one of LINE_CONFIGS
    remarks: str = ""
    borders: list[StationBorder] = field(default_factory=list)   # per-line borders


@dataclass
class AllotmentEntry:
    """One row of an RFID Tag / TIN allotment chart (a station or block section)."""
    name: str
    station_id: str = ""
    tags: frozenset = frozenset()
    tins: frozenset = frozenset()
    tag_text: str = ""
    tin_text: str = ""


@dataclass
class StationAllotment:
    """What the current allotment chart gives this station (BR-001): its own row and
    the rows of its adjacent block sections, whose numbers may also appear on its
    layout (e.g. R-774 on the Aler layout is in the Wangapalli-Aler IB range)."""
    chart_ref: str
    own: AllotmentEntry | None = None
    adjacent: list = field(default_factory=list)      # [(adjacent station name, AllotmentEntry)]
    unmatched_adjacent: list = field(default_factory=list)   # adjacent names not found in the chart


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
    centre_line_m: float | None = None   # station centre line absolute location (H2.4 / H2.28)
    tracks: list[Track] = field(default_factory=list)
    adjacent: list[AdjacentStation] = field(default_factory=list)
    allotment: StationAllotment | None = None   # None = no allotment chart loaded
    dn_direction: str = "Nominal"   # workspace convention: KAVACH direction of the SIP's "Down"
    workspace_code: str = ""

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
    track_id: int | None = None
    to_track_id: int | None = None   # points only: the line the turnout leads to
    lc_class: str | None = None      # LC gates only
    lc_manning: str | None = None    # LC gates only


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
    track_id: int | None = None


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
    track_id: int | None = None


@dataclass
class StationLayout:
    """Convenience bundle for passing a full station's data into the rules engine
    and ToC cross-validator in one call."""
    station: Station
    elements: list[Element] = field(default_factory=list)
    tags: list[Tag] = field(default_factory=list)
    tins: list[TIN] = field(default_factory=list)
