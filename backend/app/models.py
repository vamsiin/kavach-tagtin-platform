"""
SQLAlchemy persistence layer. This is intentionally a thin adapter: it maps ORM rows
to/from the plain dataclasses in app.domain, which is what the rules engine and ToC
cross-validator actually operate on (see domain.py docstring for why). Routers should
convert to domain objects immediately after a DB read and convert back immediately
before a DB write -- domain objects should be what flows through business logic.
"""
from sqlalchemy import (
    Column, Integer, String, Float, ForeignKey, DateTime, Text, Boolean
)
from sqlalchemy.orm import relationship
from datetime import datetime, timezone

from .database import Base
from . import domain


class StationORM(Base):
    __tablename__ = "stations"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    kavach_station_id = Column(String, unique=True, nullable=False)
    sip_drawing_number = Column(String, nullable=True)
    kavach_version = Column(String, nullable=True)
    sip_version = Column(String, nullable=True)
    guideline_version = Column(String, nullable=True)
    drawn_to_scale = Column(Boolean, default=True)
    not_to_scale_note_present = Column(Boolean, default=False)
    status = Column(String, default="draft")
    created_by = Column(String, nullable=True)  # username of the creator
    assigned_checker = Column(String, nullable=True)  # username of the checker this was submitted to
    assigned_designer = Column(String, nullable=True)  # set by a Project Manager (Phase 6); None = any designer
    centre_line_m = Column(Float, nullable=True)       # station centre line absolute location (H2.4 / H2.28)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    elements = relationship("ElementORM", back_populates="station", cascade="all, delete-orphan")
    tags = relationship("TagORM", back_populates="station", cascade="all, delete-orphan")
    tins = relationship("TINORM", back_populates="station", cascade="all, delete-orphan")
    revisions = relationship("RevisionORM", back_populates="station", cascade="all, delete-orphan")
    documents = relationship("InputDocumentORM", back_populates="station", cascade="all, delete-orphan")
    railway_submissions = relationship("RailwaySubmissionORM", back_populates="station",
                                       cascade="all, delete-orphan")
    observations = relationship("ObservationORM", back_populates="station",
                                cascade="all, delete-orphan")
    generated_reports = relationship("GeneratedReportORM", back_populates="station",
                                     cascade="all, delete-orphan")
    checklist_responses = relationship("ChecklistResponseORM", back_populates="station",
                                       cascade="all, delete-orphan")
    changes = relationship("StationChangeORM", back_populates="station", cascade="all, delete-orphan")
    baselines = relationship("BaselineORM", back_populates="station", cascade="all, delete-orphan")
    tracks = relationship("TrackORM", back_populates="station", cascade="all, delete-orphan",
                          order_by="TrackORM.sort_order, TrackORM.id")
    adjacent_stations = relationship("AdjacentStationORM", back_populates="station",
                                     cascade="all, delete-orphan", order_by="AdjacentStationORM.id")

    def to_domain(self) -> domain.Station:
        return domain.Station(
            id=self.id, name=self.name, kavach_station_id=self.kavach_station_id,
            sip_drawing_number=self.sip_drawing_number or "",
            kavach_version=self.kavach_version or "", sip_version=self.sip_version or "",
            guideline_version=self.guideline_version or "",
            created_by=self.created_by, assigned_checker=self.assigned_checker,
            drawn_to_scale=bool(self.drawn_to_scale),
            not_to_scale_note_present=bool(self.not_to_scale_note_present),
            status=self.status,
            centre_line_m=self.centre_line_m,
            tracks=[t.to_domain() for t in self.tracks],
            adjacent=[a.to_domain() for a in self.adjacent_stations],
            allotment=self._allotment(),
        )

    def _allotment(self):
        from sqlalchemy.orm import object_session
        from .allotment.service import station_allotment
        db = object_session(self)
        return station_allotment(db, self) if db is not None else None

    @property
    def layout_version(self) -> str:
        """Duplicated logic from domain.Station.layout_version (same formula,
        independent of kavach/sip/guideline version) so this property is directly
        accessible on the ORM object itself -- this is what lets _station_out() in
        routers/stations.py use Pydantic's from_attributes=True to build the
        response schema instead of manually listing every field by hand, which is
        what caused two separate real bugs (created_by, then assigned_checker,
        both silently missing from API responses after being added to the model)
        before this property existed."""
        if not (self.kavach_version and self.sip_version and self.guideline_version):
            return "INCOMPLETE"
        return f"{self.kavach_version}.{self.sip_version}.{self.guideline_version}"


class ElementORM(Base):
    __tablename__ = "elements"

    id = Column(Integer, primary_key=True)
    station_id = Column(Integer, ForeignKey("stations.id"), nullable=False)
    element_ref = Column(String, nullable=False)
    element_type = Column(String, nullable=False)
    location_m = Column(Float, nullable=False)
    direction = Column(String, nullable=True)
    remarks = Column(Text, nullable=True)
    source_document_id = Column(Integer, ForeignKey("input_documents.id"), nullable=True)
    track_id = Column(Integer, ForeignKey("tracks.id"), nullable=True)
    to_track_id = Column(Integer, ForeignKey("tracks.id"), nullable=True)   # points: diverging line
    lc_class = Column(String, nullable=True)
    lc_manning = Column(String, nullable=True)

    station = relationship("StationORM", back_populates="elements")

    def to_domain(self) -> domain.Element:
        return domain.Element(
            id=self.id, element_ref=self.element_ref, element_type=self.element_type,
            location_m=self.location_m, direction=self.direction,
            remarks=self.remarks or "", track_id=self.track_id, to_track_id=self.to_track_id,
            lc_class=self.lc_class, lc_manning=self.lc_manning,
        )


class TagORM(Base):
    __tablename__ = "tags"

    id = Column(Integer, primary_key=True)
    station_id = Column(Integer, ForeignKey("stations.id"), nullable=False)
    tag_ref = Column(String, nullable=False)
    tag_number = Column(Integer, nullable=True)
    tag_type = Column(String, nullable=False)
    direction = Column(String, nullable=True)
    location_m = Column(Float, nullable=False)
    tin_no = Column(Integer, nullable=True)
    linked_element_id = Column(Integer, ForeignKey("elements.id"), nullable=True)
    is_duplicate = Column(Boolean, default=False)
    pair_group_id = Column(String, nullable=True)
    legend_shape = Column(String, nullable=True)
    exit_set = Column(String, nullable=True)
    is_border_tag = Column(Boolean, default=False)
    remarks = Column(Text, nullable=True)
    source_document_id = Column(Integer, ForeignKey("input_documents.id"), nullable=True)
    track_id = Column(Integer, ForeignKey("tracks.id"), nullable=True)

    station = relationship("StationORM", back_populates="tags")

    def to_domain(self) -> domain.Tag:
        return domain.Tag(
            id=self.id, tag_ref=self.tag_ref, tag_type=self.tag_type,
            location_m=self.location_m, tag_number=self.tag_number,
            direction=self.direction, tin_no=self.tin_no,
            linked_element_id=self.linked_element_id, is_duplicate=bool(self.is_duplicate),
            pair_group_id=self.pair_group_id, legend_shape=self.legend_shape,
            exit_set=self.exit_set, is_border_tag=bool(self.is_border_tag),
            remarks=self.remarks or "", track_id=self.track_id,
        )


class TINORM(Base):
    __tablename__ = "tins"

    id = Column(Integer, primary_key=True)
    station_id = Column(Integer, ForeignKey("stations.id"), nullable=False)
    tin_no = Column(Integer, nullable=False)
    section_type = Column(String, nullable=False)
    color = Column(String, nullable=True)
    start_m = Column(Float, nullable=False)
    end_m = Column(Float, nullable=False)
    direction = Column(String, nullable=True)
    is_non_kavach_territory = Column(Boolean, default=False)
    remarks = Column(Text, nullable=True)
    source_document_id = Column(Integer, ForeignKey("input_documents.id"), nullable=True)
    track_id = Column(Integer, ForeignKey("tracks.id"), nullable=True)

    station = relationship("StationORM", back_populates="tins")

    def to_domain(self) -> domain.TIN:
        return domain.TIN(
            tin_no=self.tin_no, section_type=self.section_type, color=self.color,
            start_m=self.start_m, end_m=self.end_m, direction=self.direction,
            is_non_kavach_territory=bool(self.is_non_kavach_territory),
            remarks=self.remarks or "", track_id=self.track_id,
        )


class TrackORM(Base):
    """A named line in the station layout (DN MAIN, UP LOOP, a siding, a block line).
    Elements, tags and TINs reference the line they sit on; points join two lines."""
    __tablename__ = "tracks"

    id = Column(Integer, primary_key=True)
    station_id = Column(Integer, ForeignKey("stations.id"), nullable=False)
    name = Column(String, nullable=False)
    track_type = Column(String, nullable=False)
    start_m = Column(Float, nullable=False)
    end_m = Column(Float, nullable=False)
    direction = Column(String, nullable=True)
    is_kavach = Column(Boolean, default=True)
    sort_order = Column(Integer, default=0)
    remarks = Column(Text, nullable=True)
    source_document_id = Column(Integer, ForeignKey("input_documents.id"), nullable=True)

    station = relationship("StationORM", back_populates="tracks")

    def to_domain(self) -> domain.Track:
        return domain.Track(id=self.id, name=self.name, track_type=self.track_type,
                            start_m=self.start_m, end_m=self.end_m, direction=self.direction,
                            is_kavach=self.is_kavach is not False, remarks=self.remarks or "")


class AdjacentStationORM(Base):
    """A neighbouring station: border line location (H2.16) and section line
    configuration (H2.22)."""
    __tablename__ = "adjacent_stations"

    id = Column(Integer, primary_key=True)
    station_id = Column(Integer, ForeignKey("stations.id"), nullable=False)
    name = Column(String, nullable=False)
    side = Column(String, nullable=False)
    kavach_station_id = Column(String, nullable=True)
    border_m = Column(Float, nullable=True)
    distance_m = Column(Float, nullable=True)
    line_config = Column(String, nullable=True)
    remarks = Column(Text, nullable=True)

    station = relationship("StationORM", back_populates="adjacent_stations")
    borders = relationship("StationBorderORM", back_populates="adjacent", cascade="all, delete-orphan",
                           order_by="StationBorderORM.id")

    def to_domain(self) -> domain.AdjacentStation:
        return domain.AdjacentStation(
            id=self.id, name=self.name, side=self.side, kavach_station_id=self.kavach_station_id or "",
            border_m=self.border_m, distance_m=self.distance_m, line_config=self.line_config,
            remarks=self.remarks or "",
            borders=[domain.StationBorder(line_label=b.line_label, border_m=b.border_m,
                                          border_tag_ref=b.border_tag_ref or "", track_id=b.track_id)
                     for b in self.borders])


class StationBorderORM(Base):
    """Border line location with a neighbouring station on one line (H2.16)."""
    __tablename__ = "station_borders"

    id = Column(Integer, primary_key=True)
    adjacent_station_id = Column(Integer, ForeignKey("adjacent_stations.id"), nullable=False)
    line_label = Column(String, nullable=False)
    track_id = Column(Integer, ForeignKey("tracks.id"), nullable=True)
    border_m = Column(Float, nullable=False)
    border_tag_ref = Column(String, nullable=True)

    adjacent = relationship("AdjacentStationORM", back_populates="borders")


class AllotmentChartORM(Base):
    """An RFID Tag / TIN allotment chart as issued by RDSO / the Railway for a
    division (BR-001). Reference data shared by all stations. Never edited: a
    revised chart is loaded as a new chart that supersedes the current one."""
    __tablename__ = "allotment_charts"

    id = Column(Integer, primary_key=True)
    title = Column(String, nullable=False)
    division = Column(String, nullable=False)
    reference_no = Column(String, nullable=True)
    issued_on = Column(String, nullable=True)       # YYYY-MM-DD as on the letter
    issued_by = Column(String, nullable=True)
    remarks = Column(Text, nullable=True)
    is_current = Column(Boolean, default=True)
    source_filename = Column(String, nullable=True)
    source_path = Column(String, nullable=True)
    source_sha256 = Column(String, nullable=True)
    created_by = Column(String, nullable=False)
    created_at = Column(String, nullable=False)
    superseded_by_id = Column(Integer, ForeignKey("allotment_charts.id"), nullable=True)

    rows = relationship("AllotmentRowORM", back_populates="chart", cascade="all, delete-orphan",
                        order_by="AllotmentRowORM.id")


class AllotmentRowORM(Base):
    __tablename__ = "allotment_rows"

    id = Column(Integer, primary_key=True)
    chart_id = Column(Integer, ForeignKey("allotment_charts.id"), nullable=False)
    s_no = Column(String, nullable=True)
    name = Column(String, nullable=False)
    division_code = Column(String, nullable=True)
    station_code = Column(String, nullable=True)
    station_id = Column(String, nullable=True)
    tin_ranges = Column(String, nullable=True)
    tin_allotted = Column(String, nullable=True)
    tag_ranges = Column(String, nullable=True)
    tag_total = Column(Integer, nullable=True)       # as printed on the chart
    remarks = Column(Text, nullable=True)

    chart = relationship("AllotmentChartORM", back_populates="rows")


class RevisionORM(Base):
    __tablename__ = "revisions"

    id = Column(Integer, primary_key=True)
    station_id = Column(Integer, ForeignKey("stations.id"), nullable=False)
    rev_no = Column(String, nullable=False)
    date = Column(String, nullable=True)          # revision date as written on the drawing (YYYY-MM-DD)
    description = Column(Text, nullable=False)
    # Phase 4: previously dead code, now wired (routers/revisions.py). Who recorded the
    # entry, when, and the layout X.Y.Z it applied to.
    layout_version = Column(String, nullable=True)
    created_by = Column(String, nullable=True)
    created_at = Column(String, nullable=True)

    station = relationship("StationORM", back_populates="revisions")


class UserORM(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    username = Column(String, unique=True, nullable=False, index=True)
    full_name = Column(String, nullable=False)
    email = Column(String, nullable=True)
    role = Column(String, nullable=False)  # designer | checker | approver | admin
    password_hash = Column(String, nullable=False)
    password_salt = Column(String, nullable=False)
    is_active = Column(Boolean, default=True)

    def to_domain(self) -> domain.User:
        return domain.User(
            id=self.id, username=self.username, full_name=self.full_name,
            email=self.email or "", role=self.role, password_hash=self.password_hash,
            password_salt=self.password_salt, is_active=bool(self.is_active),
        )


class WorkflowEventORM(Base):
    __tablename__ = "workflow_events"

    id = Column(Integer, primary_key=True)
    station_id = Column(Integer, ForeignKey("stations.id"), nullable=False)
    from_status = Column(String, nullable=False)
    to_status = Column(String, nullable=False)
    action = Column(String, nullable=False)
    actor_username = Column(String, nullable=False)
    actor_role = Column(String, nullable=False)
    comment = Column(Text, nullable=True)
    timestamp = Column(String, nullable=False)
    verification_fail_count = Column(Integer, nullable=True)
    target_username = Column(String, nullable=True)  # e.g. checker a submission was assigned to
    # FR-011 traceability: JSON list of the CURRENT input document revisions
    # ({id, doc_type, revision, sha256, original_filename}) at the moment of this
    # transition. This is what lets an approval be traced back to the exact SIP /
    # Site Survey / Allocation Chart revision it was based on, even after newer
    # revisions of those inputs are uploaded later.
    input_snapshot = Column(Text, nullable=True)
    layout_version = Column(String, nullable=True)  # X.Y.Z at the moment of the transition

    def to_domain(self) -> domain.WorkflowEvent:
        return domain.WorkflowEvent(
            id=self.id, station_id=self.station_id, from_status=self.from_status,
            to_status=self.to_status, action=self.action,
            actor_username=self.actor_username, actor_role=self.actor_role,
            comment=self.comment or "", timestamp=self.timestamp,
            verification_fail_count=self.verification_fail_count,
            target_username=self.target_username,
        )



class InputDocumentORM(Base):
    """FR-001: a design input attached to a station -- SIP drawing, Site Survey,
    RFID Tag Allocation Chart, Adjacent Station Layout, Table of Control, or other.

    Each upload is an immutable revision: re-uploading the same doc_type creates
    revision N+1 rather than overwriting, so anything traced to revision N (a Tag
    imported from it, a workflow snapshot that recorded it) keeps pointing at the
    exact bytes it was derived from. sha256 is stored so that integrity can be
    re-verified later against the file on disk.
    """
    __tablename__ = "input_documents"

    id = Column(Integer, primary_key=True)
    station_id = Column(Integer, ForeignKey("stations.id"), nullable=False, index=True)
    doc_type = Column(String, nullable=False)
    revision = Column(Integer, nullable=False)
    version_label = Column(String, nullable=True)  # the drawing's own rev label, e.g. "SIP Rev-3"
    original_filename = Column(String, nullable=False)
    stored_path = Column(String, nullable=False)  # relative to UPLOAD_DIR
    content_type = Column(String, nullable=True)
    size_bytes = Column(Integer, nullable=False)
    sha256 = Column(String, nullable=False)
    uploaded_by = Column(String, nullable=False)
    uploaded_at = Column(String, nullable=False)  # ISO-8601 UTC, same convention as WorkflowEventORM
    notes = Column(Text, nullable=True)

    station = relationship("StationORM", back_populates="documents")


class RailwaySubmissionORM(Base):
    """BRD FR-009 terminal step: the approved layout package as formally sent to the
    Railway. Freezes what was sent -- layout version, the full register contents,
    and the input-document revisions -- so later edits (after an admin reopen)
    can never change the record of what the Railway actually received."""
    __tablename__ = "railway_submissions"

    id = Column(Integer, primary_key=True)
    station_id = Column(Integer, ForeignKey("stations.id"), nullable=False, index=True)
    workflow_event_id = Column(Integer, ForeignKey("workflow_events.id"), nullable=True)
    layout_version = Column(String, nullable=False)
    reference_no = Column(String, nullable=False)       # covering letter / package reference
    submitted_on = Column(String, nullable=False)       # date the package was sent (YYYY-MM-DD)
    addressed_to = Column(String, nullable=True)        # e.g. "Sr. DSTE / Zone"
    remarks = Column(Text, nullable=True)
    recorded_by = Column(String, nullable=False)
    recorded_at = Column(String, nullable=False)
    verification_fail_count = Column(Integer, nullable=True)
    layout_snapshot = Column(Text, nullable=False)      # JSON: elements/tags/tins as sent
    input_snapshot = Column(Text, nullable=True)        # JSON: input document revisions

    station = relationship("StationORM", back_populates="railway_submissions")


class ObservationORM(Base):
    """BRD FR-008: a review observation raised against a station's layout -- one
    tracked, individually resolvable item, as opposed to the single free-text comment
    a workflow transition carries.

    Lifecycle (see app/observations/rules.py):
        open / reopened --resolve (designer)--> resolved --close (reviewer)--> closed
        resolved / closed --reopen (reviewer)--> reopened
        open / reopened / resolved --withdraw (raiser/admin)--> withdrawn

    The subject (tag / element / TIN / document / station) is stored as a kind + id +
    a text snapshot of its ref, deliberately WITHOUT a foreign key: the designer may
    delete or rename the tag as the fix, and the observation must survive that.
    """
    __tablename__ = "observations"

    id = Column(Integer, primary_key=True)
    station_id = Column(Integer, ForeignKey("stations.id"), nullable=False, index=True)
    obs_no = Column(Integer, nullable=False)            # per-station sequence -> "OBS-003"
    description = Column(Text, nullable=False)
    severity = Column(String, nullable=False)           # major | minor | info
    category = Column(String, nullable=True)            # annexure-h | toc | drafting | data | inputs | other
    clause = Column(String, nullable=True)              # e.g. "H2.5"
    subject_kind = Column(String, nullable=False, default="station")
    subject_id = Column(Integer, nullable=True)
    subject_ref = Column(String, nullable=True)
    status = Column(String, nullable=False, default="open")
    raised_by = Column(String, nullable=False)
    raised_by_role = Column(String, nullable=False)
    raised_at = Column(String, nullable=False)
    raised_at_status = Column(String, nullable=True)    # station status when raised
    layout_version = Column(String, nullable=True)      # layout X.Y.Z when raised
    resolved_by = Column(String, nullable=True)
    resolved_at = Column(String, nullable=True)
    closed_by = Column(String, nullable=True)
    closed_at = Column(String, nullable=True)

    station = relationship("StationORM", back_populates="observations")
    comments = relationship("ObservationCommentORM", back_populates="observation",
                            cascade="all, delete-orphan",
                            order_by="ObservationCommentORM.id")


class ObservationCommentORM(Base):
    """Append-only thread on an observation. Every lifecycle action writes one of
    these (action = raise/resolve/close/reopen/withdraw), plain replies have
    action = 'comment' -- so the thread IS the observation's audit trail."""
    __tablename__ = "observation_comments"

    id = Column(Integer, primary_key=True)
    observation_id = Column(Integer, ForeignKey("observations.id"), nullable=False, index=True)
    action = Column(String, nullable=False)
    from_status = Column(String, nullable=True)
    to_status = Column(String, nullable=True)
    author = Column(String, nullable=False)
    author_role = Column(String, nullable=False)
    text = Column(Text, nullable=True)
    created_at = Column(String, nullable=False)

    observation = relationship("ObservationORM", back_populates="comments")


class GeneratedReportORM(Base):
    """FR-007: log of every report generated, and the stored file for reports archived
    automatically at workflow steps (so the verification evidence behind a check or an
    approval is kept exactly as it was, not regenerated from today's data)."""
    __tablename__ = "generated_reports"

    id = Column(Integer, primary_key=True)
    station_id = Column(Integer, ForeignKey("stations.id"), nullable=False, index=True)
    report_type = Column(String, nullable=False)
    report_id = Column(String, nullable=False)
    fmt = Column(String, nullable=False)                # pdf | docx
    generated_by = Column(String, nullable=False)
    generated_at = Column(String, nullable=False)
    layout_version = Column(String, nullable=True)
    station_status = Column(String, nullable=True)
    sha256 = Column(String, nullable=False)
    size_bytes = Column(Integer, nullable=False)
    archived = Column(Boolean, default=False)           # file kept on disk?
    stored_path = Column(String, nullable=True)         # relative to UPLOAD_DIR, when archived
    workflow_event_id = Column(Integer, nullable=True)  # set for auto-archived reports
    trigger = Column(String, nullable=True)             # e.g. "self_check", "approve", "manual"

    station = relationship("StationORM", back_populates="generated_reports")


class ChecklistRuleORM(Base):
    """BRD FR-006: one configurable checklist rule (see app/rules/checklist.py).
    Global (applies to every station). Built-in rules are seeded on startup and can be
    edited/disabled but never deleted; custom rules are soft-deleted (deleted=True) so
    that past manual responses and change history keep pointing at a real row."""
    __tablename__ = "checklist_rules"

    id = Column(Integer, primary_key=True)
    key = Column(String, unique=True, nullable=False)
    kind = Column(String, nullable=False)
    builtin = Column(String, nullable=True)
    clause = Column(String, nullable=False)
    title = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    params = Column(Text, nullable=False, default="{}")   # JSON
    severity = Column(String, nullable=False, default="FAIL")
    enabled = Column(Boolean, default=True)
    blocking = Column(Boolean, default=False)
    sort_order = Column(Integer, nullable=False, default=0)
    deleted = Column(Boolean, default=False)
    updated_by = Column(String, nullable=True)
    updated_at = Column(String, nullable=True)


class ChecklistChangeORM(Base):
    """Append-only audit of every checklist configuration change. Its row count is the
    configuration version stamped on verification results and reports."""
    __tablename__ = "checklist_changes"

    id = Column(Integer, primary_key=True)
    rule_id = Column(Integer, nullable=True)
    rule_key = Column(String, nullable=True)
    action = Column(String, nullable=False)     # seed | create | update | delete | reorder | reset
    before = Column(Text, nullable=True)        # JSON
    after = Column(Text, nullable=True)         # JSON
    reason = Column(Text, nullable=True)
    changed_by = Column(String, nullable=False)
    changed_at = Column(String, nullable=False)


class ChecklistResponseORM(Base):
    """A reviewer's confirmation of a MANUAL checklist item for one station, in one
    review cycle. Responses are never deleted: a new cycle (after rework / revise /
    reopen) simply makes earlier ones non-current (see cycle_event_id)."""
    __tablename__ = "checklist_responses"

    id = Column(Integer, primary_key=True)
    station_id = Column(Integer, ForeignKey("stations.id"), nullable=False, index=True)
    rule_id = Column(Integer, ForeignKey("checklist_rules.id"), nullable=False)
    cycle_event_id = Column(Integer, nullable=False, default=0)  # id of the cycle-start event (0 = first cycle)
    status = Column(String, nullable=False)     # PASS | FAIL | NA
    note = Column(Text, nullable=True)
    responded_by = Column(String, nullable=False)
    responded_by_role = Column(String, nullable=False)
    responded_at = Column(String, nullable=False)
    layout_version = Column(String, nullable=True)

    station = relationship("StationORM", back_populates="checklist_responses")


class StationChangeORM(Base):
    """Audited change to a station's own particulars made outside the registers --
    version numbers (Configuration Manager) and designer assignment (Project Manager).
    Workflow transitions have their own log (WorkflowEventORM)."""
    __tablename__ = "station_changes"

    id = Column(Integer, primary_key=True)
    station_id = Column(Integer, ForeignKey("stations.id"), nullable=False, index=True)
    field = Column(String, nullable=False)
    before = Column(String, nullable=True)
    after = Column(String, nullable=True)
    reason = Column(Text, nullable=True)
    changed_by = Column(String, nullable=False)
    changed_by_role = Column(String, nullable=False)
    changed_at = Column(String, nullable=False)

    station = relationship("StationORM", back_populates="changes")


class BaselineORM(Base):
    """Configuration baseline (BRD Configuration Manager role): a named, frozen copy of
    an APPROVED layout -- registers, input revisions, checklist version and the
    verification result -- that later revisions can be compared against."""
    __tablename__ = "baselines"

    id = Column(Integer, primary_key=True)
    station_id = Column(Integer, ForeignKey("stations.id"), nullable=False, index=True)
    label = Column(String, nullable=False)
    layout_version = Column(String, nullable=False)
    station_status = Column(String, nullable=False)
    notes = Column(Text, nullable=True)
    layout_snapshot = Column(Text, nullable=False)   # JSON
    input_snapshot = Column(Text, nullable=True)     # JSON
    checklist_version = Column(Integer, nullable=True)
    verification_summary = Column(Text, nullable=True)  # JSON
    created_by = Column(String, nullable=False)
    created_at = Column(String, nullable=False)

    station = relationship("StationORM", back_populates="baselines")
