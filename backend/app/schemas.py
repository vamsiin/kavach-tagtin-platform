import json

from pydantic import BaseModel, Field, computed_field, field_validator, model_validator
from .domain import ELEMENT_TYPES, TAG_TYPES



class StationCreate(BaseModel):
    name: str
    kavach_station_id: str
    sip_drawing_number: str | None = None
    kavach_version: str | None = None
    sip_version: str | None = None
    guideline_version: str | None = None
    drawn_to_scale: bool = True
    not_to_scale_note_present: bool = False
    centre_line_m: float | None = None


class StationCreateRequest(StationCreate):
    """Create payload: may also carry the neighbouring stations (H2.16 border lines)."""
    adjacent_stations: list["AdjacentStationCreate"] = Field(default_factory=list)
    workspace_id: int | None = Field(default=None, description="Railway zone workspace; defaults to the "
                                     "user's only workspace")


class StationOut(StationCreate):
    id: int
    workspace_id: int | None = None
    workspace_code: str | None = None
    status: str
    layout_version: str
    created_by: str | None = None
    assigned_checker: str | None = None
    assigned_designer: str | None = None

    class Config:
        from_attributes = True


class ElementCreate(BaseModel):
    element_ref: str
    element_type: str = Field(description=f"One of: {', '.join(ELEMENT_TYPES)}")
    location_m: float
    direction: str | None = None
    remarks: str | None = None
    source_document_id: int | None = Field(
        default=None, description="Input document (SIP/DXF etc.) this row was derived from -- FR-011")
    track_id: int | None = Field(default=None, description="Line this element sits on")
    to_track_id: int | None = Field(default=None, description="Points only: the line the turnout leads to")
    lc_class: str | None = Field(default=None, description="LC gates only: Special / A / B / C / D")
    lc_manning: str | None = Field(default=None, description="LC gates only")



class ElementOut(ElementCreate):
    id: int


    class Config:
        from_attributes = True


class TagCreate(BaseModel):
    tag_ref: str
    tag_type: str = Field(description=f"One of: {', '.join(TAG_TYPES)}")
    location_m: float
    tag_number: int | None = None
    direction: str | None = None
    tin_no: int | None = None
    linked_element_id: int | None = None
    is_duplicate: bool = False
    pair_group_id: str | None = None
    legend_shape: str | None = None
    exit_set: str | None = None
    is_border_tag: bool = False
    remarks: str | None = None
    source_document_id: int | None = Field(
        default=None, description="Input document (SIP/DXF/Allocation Chart) this tag was derived from -- FR-011/BR-001")
    track_id: int | None = Field(default=None, description="Line this tag sits on")


    @field_validator("is_duplicate", "is_border_tag", mode="before")
    @classmethod
    def _coerce_none_bool_to_false(cls, v):
        """Defensive coercion for both boolean fields on this schema. is_border_tag
        is confirmed vulnerable (added via the auto-migration to an already-
        populated table, so pre-existing rows get NULL, not False -- see the
        regression test this validator was written to satisfy). is_duplicate
        SHOULD always have a non-null value in practice (its SQLAlchemy column has
        had default=False since the very first schema, so every row created
        through the ORM has always gotten an explicit value) -- but the exact same
        raw-SQL-insert test that caught the is_border_tag bug incidentally proved
        this field has the identical failure mode if a row's value were ever NULL
        for any other reason (a manual DB edit, a future refactor, etc.), so it's
        covered here too rather than left as a narrower landmine."""
        return bool(v)


class TagOut(TagCreate):
    id: int


    class Config:
        from_attributes = True


class TINCreate(BaseModel):
    tin_no: int
    section_type: str  # Station | Block
    color: str | None = None
    start_m: float
    end_m: float
    direction: str | None = None
    is_non_kavach_territory: bool = False
    remarks: str | None = None
    source_document_id: int | None = None
    track_id: int | None = Field(default=None, description="Line this TIN section is on")



class TINOut(TINCreate):
    id: int


    class Config:
        from_attributes = True


class TrackCreate(BaseModel):
    name: str
    track_type: str
    start_m: float
    end_m: float
    direction: str | None = None
    line_type: str | None = Field(default=None, description="UP MAIN, DN MAIN, UP LOOP, DN LOOP, COMMON LOOP "
                                  "or OTHER; taken from the name when left out")
    is_kavach: bool = True
    sort_order: int = 0
    remarks: str | None = None
    source_document_id: int | None = None

    @field_validator("is_kavach", mode="before")
    @classmethod
    def _none_is_true(cls, v):
        return True if v is None else bool(v)


class TrackOut(TrackCreate):
    id: int

    class Config:
        from_attributes = True


class StationBorderIn(BaseModel):
    line_label: str
    border_m: float
    border_tag_ref: str | None = None
    track_id: int | None = None


class StationBorderOut(StationBorderIn):
    id: int

    class Config:
        from_attributes = True


class AdjacentStationCreate(BaseModel):
    name: str
    side: str
    kavach_station_id: str | None = None
    border_m: float | None = Field(default=None, description="Single border location; use `borders` "
                                   "when it differs by line")
    distance_m: float | None = None
    line_config: str | None = None
    remarks: str | None = None
    borders: list[StationBorderIn] = Field(default_factory=list, description="Border location per line (H2.16)")


class AdjacentStationOut(AdjacentStationCreate):
    id: int
    borders: list[StationBorderOut] = Field(default_factory=list)

    class Config:
        from_attributes = True


class CentreLineUpdate(BaseModel):
    centre_line_m: float | None = None


class AllotmentRowIn(BaseModel):
    s_no: str | None = None
    name: str
    division_code: str | None = None
    station_code: str | None = None
    station_id: str | None = None
    tin_ranges: str | None = None
    tin_allotted: str | None = None
    tag_ranges: str | None = None
    tag_total: int | None = None
    remarks: str | None = None


class AllotmentRowOut(AllotmentRowIn):
    id: int | None = None
    tag_count: int = 0
    tin_count: int = 0
    problems: list[str] = Field(default_factory=list)


class AllotmentChartCreate(BaseModel):
    title: str
    division: str
    reference_no: str | None = None
    issued_on: str | None = None
    issued_by: str | None = None
    remarks: str | None = None
    rows: list[AllotmentRowIn]
    supersede_current: bool = Field(default=True, description="Make this the current chart for its division")
    workspace_id: int | None = Field(default=None, description="Railway zone workspace; defaults to the "
                                     "user's only workspace")


class AllotmentChartOut(BaseModel):
    id: int
    title: str
    division: str
    reference_no: str | None = None
    issued_on: str | None = None
    issued_by: str | None = None
    remarks: str | None = None
    is_current: bool
    source_filename: str | None = None
    source_sha256: str | None = None
    created_by: str
    created_at: str
    superseded_by_id: int | None = None
    row_count: int = 0
    workspace_id: int | None = None
    workspace_code: str | None = None


class AllotmentChartDetail(AllotmentChartOut):
    rows: list[AllotmentRowOut]
    warnings: list[str] = Field(default_factory=list)


class AllotmentParseOut(BaseModel):
    rows: list[AllotmentRowOut]
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class NumberUse(BaseModel):
    number: int
    ref: str
    owner: str | None = None


class AllotmentUsage(BaseModel):
    allotted: int
    used_in_own: int
    free: int
    free_ranges: str
    next_free_odd: int | None = None
    next_free_even: int | None = None
    used: list[NumberUse]
    outside: list[NumberUse]


class AdjacentAllotment(BaseModel):
    adjacent_name: str
    row: AllotmentRowOut | None = None


class StationAllotmentOut(BaseModel):
    chart: AllotmentChartOut | None = None
    own: AllotmentRowOut | None = None
    adjacent: list[AdjacentAllotment] = Field(default_factory=list)
    tags: AllotmentUsage | None = None
    tins: AllotmentUsage | None = None


class WorkspaceIn(BaseModel):
    code: str
    name: str
    dn_direction: str = Field(default="Nominal", description="KAVACH direction of the SIP's Down movements")
    open_to_all: bool = False
    remarks: str | None = None


class WorkspaceOut(WorkspaceIn):
    id: int
    created_by: str | None = None
    created_at: str | None = None
    members: list[str] = Field(default_factory=list)
    station_count: int = 0
    override_count: int = 0


class WorkspaceMembersUpdate(BaseModel):
    usernames: list[str]


class MoveStationRequest(BaseModel):
    workspace_id: int
    reason: str = Field(min_length=1)


class RuleOverrideIn(BaseModel):
    params: dict | None = None
    severity: str | None = None
    enabled: bool | None = None
    reason: str = Field(min_length=1)


class CheckResultOut(BaseModel):
    clause: str
    title: str
    status: str
    message: str
    subject_ref: str | None = None


class VerificationReportOut(BaseModel):
    results: list[CheckResultOut]
    summary: dict
    manual_clauses: dict[str, str]
    checklist_version: int | None = None   # FR-006 configuration version used
    rules_disabled: list[str] = []         # automated rules switched off by an admin
    deviations_unused: list[str] = []      # recorded deviations that no longer match a failing check


class DeviationIn(BaseModel):
    clause: str = Field(min_length=1)
    subject_ref: str | None = None
    reason: str = Field(min_length=5, description="Why the rule does not fit this station")
    reference: str | None = Field(default=None, description="SIP / LC document reference")


class DeviationOut(DeviationIn):
    id: int
    created_by: str
    created_by_role: str
    created_at: str
    in_use: bool = True

    class Config:
        from_attributes = True


class ChainCheckResultOut(BaseModel):
    route_s_no: str
    entry_signal: str
    exit_signal: str
    status: str
    message: str
    tag_ref: str | None = None


class ToCCrossValidationOut(BaseModel):
    results: list[ChainCheckResultOut]
    summary: dict


class UserCreate(BaseModel):
    username: str
    full_name: str
    email: str = ""
    role: str  # designer | checker | approver | admin
    password: str


class UserUpdate(BaseModel):
    """Edit an existing user's profile/role/active status. Password is deliberately
    excluded here -- use the dedicated reset-password flows instead, so editing a
    user's name/email/role never accidentally touches their credentials."""
    full_name: str
    email: str = ""
    role: str
    is_active: bool = True


class UserOut(BaseModel):
    id: int
    username: str
    full_name: str
    email: str = ""
    role: str
    is_active: bool

    @field_validator("email", mode="before")
    @classmethod
    def _coerce_none_email_to_empty_string(cls, v):
        """Accounts created before the `email` column existed (or created directly
        via the DB) have NULL there. `str = ""` as a field default only applies
        when the field is ABSENT from the input -- Pydantic does NOT apply it when
        the field is explicitly present with value None, which is exactly what
        happens when this schema validates straight off an ORM object via
        from_attributes (getattr returns None, not "missing"). Without this
        validator, logging in as any account that predates email support throws a
        500 -- this happened for real, not hypothetically; see
        tests/test_user_management.py's test_login_works_for_user_with_null_email."""
        return v or ""

    @computed_field
    @property
    def role_label(self) -> str:
        from .auth.permissions import ROLE_LABELS
        return ROLE_LABELS.get(self.role, self.role)

    @computed_field
    @property
    def permissions(self) -> list[str]:
        """Capabilities from app/auth/permissions.py -- the UI shows/hides controls from
        this list rather than duplicating the role rules."""
        from .auth.permissions import capabilities_for
        return capabilities_for(self.role)

    class Config:
        from_attributes = True


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


class WorkflowActionRequest(BaseModel):
    comment: str = ""


class SubmitForCheckRequest(BaseModel):
    assigned_checker_username: str
    comment: str = ""


class WorkflowEventOut(BaseModel):
    id: int
    station_id: int
    from_status: str
    to_status: str
    action: str
    actor_username: str
    actor_role: str
    comment: str
    timestamp: str
    verification_fail_count: int | None = None
    target_username: str | None = None
    input_snapshot: list[dict] | None = None
    layout_version: str | None = None

    @field_validator("input_snapshot", mode="before")
    @classmethod
    def _parse_snapshot(cls, v):
        if v is None or isinstance(v, list):
            return v
        try:
            return json.loads(v)
        except (ValueError, TypeError):
            return None

    @field_validator("comment", mode="before")
    @classmethod
    def _coerce_none_comment_to_empty_string(cls, v):
        """Defensive, same pattern/reason as UserOut.email above -- comment maps to
        a nullable DB column (WorkflowEventORM.comment) but is typed as a required
        str here. Every event created through this app's own API always supplies
        comment="" at minimum (never None), so this hasn't been observed to fail
        in practice the way the email case did -- but it's the identical landmine
        shape, and cheap enough to close pre-emptively rather than wait for a
        directly-inserted row or a future refactor to hit it."""
        return v or ""

    class Config:
        from_attributes = True


class WorkflowStatusOut(BaseModel):
    status: str
    submitted_by: str | None
    checked_by: str | None
    assigned_checker: str | None
    self_checked_by: str | None = None
    assigned_designer: str | None = None
    allowed_actions: list[str]
    history: list[WorkflowEventOut]


class ForgotPasswordRequest(BaseModel):
    username: str


class ForgotPasswordResponse(BaseModel):
    message: str


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str


class AdminResetPasswordRequest(BaseModel):
    new_password: str


# ---------------------------------------------------------------------------
# Phase 1: input documents, DXF import, traceability
# ---------------------------------------------------------------------------
class InputDocumentOut(BaseModel):
    id: int
    station_id: int
    doc_type: str
    revision: int
    version_label: str | None = None
    original_filename: str
    content_type: str | None = None
    size_bytes: int
    sha256: str
    uploaded_by: str
    uploaded_at: str
    notes: str | None = None
    is_current: bool = False

    class Config:
        from_attributes = True


class DocTypeOut(BaseModel):
    code: str
    label: str
    extensions: list[str]
    required: bool


class DxfCandidateOut(BaseModel):
    index: int
    text: str
    layer: str
    x: float
    y: float
    kind: str
    suggested_location_m: float | None = None


class DxfImportOut(BaseModel):
    document: InputDocumentOut
    candidates: list[DxfCandidateOut]
    warnings: list[str]
    layers: list[str]


class DxfCommitTag(TagCreate):
    # Lets a tag in the same commit batch link to an element by its ref (the
    # element may be created in this very batch, so it has no id yet).
    linked_element_ref: str | None = None


class DxfCommitRequest(BaseModel):
    elements: list[ElementCreate] = []
    tags: list[DxfCommitTag] = []


class DxfCommitOut(BaseModel):
    document_id: int
    elements_created: int
    tags_created: int
    element_ids: list[int]
    tag_ids: list[int]


class TraceDocRef(BaseModel):
    id: int
    doc_type: str
    revision: int
    version_label: str | None = None
    original_filename: str
    is_current: bool


class TraceRow(BaseModel):
    kind: str  # tag | element | tin
    id: int
    ref: str
    type: str | None = None
    location_m: float | None = None
    source: TraceDocRef | None = None
    source_outdated: bool = False
    linked_element_ref: str | None = None


class TraceabilityOut(BaseModel):
    station_id: int
    station_name: str
    layout_version: str
    status: str
    inputs: list[InputDocumentOut]
    rows: list[TraceRow]
    workflow: list[WorkflowEventOut]
    gaps: list[str]
    summary: dict


# ---------------------------------------------------------------------------
# Phase 2: self-check, railway submission
# ---------------------------------------------------------------------------
class SelfCheckFailedOut(BaseModel):
    message: str
    fail_count: int
    clauses_failing: list[str]


class RailwaySubmitRequest(BaseModel):
    reference_no: str = Field(min_length=1, description="Covering letter / package reference number")
    submitted_on: str = Field(description="Date the package was sent to the Railway, YYYY-MM-DD")
    addressed_to: str | None = None
    remarks: str | None = None

    @field_validator("reference_no")
    @classmethod
    def _strip_ref(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("reference_no is required")
        return v

    @field_validator("submitted_on")
    @classmethod
    def _iso_date(cls, v: str) -> str:
        from datetime import date
        try:
            return date.fromisoformat(v.strip()).isoformat()
        except ValueError:
            raise ValueError("submitted_on must be a date in YYYY-MM-DD format")


class RailwaySubmissionOut(BaseModel):
    id: int
    station_id: int
    workflow_event_id: int | None = None
    layout_version: str
    reference_no: str
    submitted_on: str
    addressed_to: str | None = None
    remarks: str | None = None
    recorded_by: str
    recorded_at: str
    verification_fail_count: int | None = None
    layout_snapshot: dict
    input_snapshot: list[dict] | None = None

    @field_validator("layout_snapshot", mode="before")
    @classmethod
    def _parse_layout(cls, v):
        return json.loads(v) if isinstance(v, str) else v

    @field_validator("input_snapshot", mode="before")
    @classmethod
    def _parse_inputs(cls, v):
        if v is None or isinstance(v, list):
            return v
        try:
            return json.loads(v)
        except (ValueError, TypeError):
            return None

    class Config:
        from_attributes = True


# ---------------------------------------------------------------------------
# Phase 3: observations (FR-008)
# ---------------------------------------------------------------------------
class ObservationCreate(BaseModel):
    description: str = Field(min_length=1)
    severity: str = "major"
    category: str | None = None
    clause: str | None = None
    subject_kind: str = "station"
    subject_id: int | None = None
    # Alternative to subject_id: identify the tag/element by its ref (e.g. from a
    # verification result row, which carries subject_ref but not an id).
    subject_ref: str | None = None


class ObservationActionRequest(BaseModel):
    comment: str = ""


class ObservationCommentOut(BaseModel):
    id: int
    action: str
    from_status: str | None = None
    to_status: str | None = None
    author: str
    author_role: str
    text: str | None = None
    created_at: str

    class Config:
        from_attributes = True


class ObservationOut(BaseModel):
    id: int
    station_id: int
    obs_no: int
    label: str = ""
    description: str
    severity: str
    category: str | None = None
    clause: str | None = None
    subject_kind: str
    subject_id: int | None = None
    subject_ref: str | None = None
    subject_exists: bool = True
    status: str
    raised_by: str
    raised_by_role: str
    raised_at: str
    raised_at_status: str | None = None
    layout_version: str | None = None
    resolved_by: str | None = None
    resolved_at: str | None = None
    closed_by: str | None = None
    closed_at: str | None = None
    comments: list[ObservationCommentOut] = []
    allowed_actions: list[str] = []

    class Config:
        from_attributes = True


class ObservationListOut(BaseModel):
    observations: list[ObservationOut]
    summary: dict


# ---------------------------------------------------------------------------
# Phase 4: revisions, reports
# ---------------------------------------------------------------------------
class RevisionCreate(BaseModel):
    rev_no: str = Field(min_length=1)
    date: str | None = None
    description: str = Field(min_length=1)

    @field_validator("date")
    @classmethod
    def _iso(cls, v):
        if v in (None, ""):
            return None
        from datetime import date
        try:
            return date.fromisoformat(v.strip()).isoformat()
        except ValueError:
            raise ValueError("date must be YYYY-MM-DD")


class RevisionOut(BaseModel):
    id: int
    rev_no: str
    date: str | None = None
    description: str
    layout_version: str | None = None
    created_by: str | None = None
    created_at: str | None = None

    class Config:
        from_attributes = True


class ReportTypeOut(BaseModel):
    code: str
    title: str
    description: str
    formats: list[str]


class GeneratedReportOut(BaseModel):
    id: int
    report_type: str
    report_id: str
    fmt: str
    generated_by: str
    generated_at: str
    layout_version: str | None = None
    station_status: str | None = None
    sha256: str
    size_bytes: int
    archived: bool = False
    workflow_event_id: int | None = None
    trigger: str | None = None

    @field_validator("archived", mode="before")
    @classmethod
    def _b(cls, v):
        return bool(v)

    class Config:
        from_attributes = True


# ---------------------------------------------------------------------------
# Phase 5: configurable checklist (FR-006)
# ---------------------------------------------------------------------------
class ChecklistRuleOut(BaseModel):
    id: int
    key: str
    kind: str
    builtin: str | None = None
    clause: str
    title: str
    description: str | None = None
    params: dict
    severity: str
    enabled: bool
    blocking: bool
    sort_order: int
    is_builtin: bool = False
    updated_by: str | None = None
    updated_at: str | None = None
    param_schema: list[dict] = []
    override: dict | None = None     # this workspace's override (GET /checklist?workspace_id=)
    effective: dict | None = None    # {params, severity, enabled} as applied in that workspace

    @field_validator("params", mode="before")
    @classmethod
    def _p(cls, v):
        return json.loads(v) if isinstance(v, str) else (v or {})

    @field_validator("enabled", "blocking", mode="before")
    @classmethod
    def _b(cls, v):
        return bool(v)

    class Config:
        from_attributes = True


class ChecklistOut(BaseModel):
    config_version: int
    rules: list[ChecklistRuleOut]
    kinds: dict[str, list[dict]]
    can_edit: bool


class ChecklistRuleCreate(BaseModel):
    kind: str
    clause: str = Field(min_length=1)
    title: str = Field(min_length=1)
    description: str | None = None
    params: dict = {}
    severity: str = "FAIL"
    enabled: bool = True
    blocking: bool = False
    reason: str = Field(min_length=1, description="Why this change is being made (audited)")


class ChecklistRuleUpdate(BaseModel):
    clause: str | None = None
    title: str | None = None
    description: str | None = None
    params: dict | None = None
    severity: str | None = None
    enabled: bool | None = None
    blocking: bool | None = None
    reason: str = Field(min_length=1)


class ChecklistReorder(BaseModel):
    ordered_ids: list[int]
    reason: str = Field(min_length=1)


class ChecklistReason(BaseModel):
    reason: str = Field(min_length=1)


class ChecklistChangeOut(BaseModel):
    id: int
    rule_id: int | None = None
    rule_key: str | None = None
    action: str
    before: dict | list | None = None
    after: dict | list | None = None
    reason: str | None = None
    changed_by: str
    changed_at: str

    @field_validator("before", "after", mode="before")
    @classmethod
    def _j(cls, v):
        return json.loads(v) if isinstance(v, str) else v

    class Config:
        from_attributes = True


class ManualItemOut(BaseModel):
    rule_id: int
    clause: str
    title: str
    description: str | None = None
    blocking: bool
    severity: str
    status: str | None = None      # PASS | FAIL | NA | None (pending)
    note: str | None = None
    responded_by: str | None = None
    responded_at: str | None = None


class ManualChecklistOut(BaseModel):
    items: list[ManualItemOut]
    summary: dict
    can_respond: bool


class ManualResponseIn(BaseModel):
    status: str
    note: str = ""


# ---------------------------------------------------------------------------
# Phase 6: roles -- Project Manager & Configuration Manager
# ---------------------------------------------------------------------------
class DashboardRow(BaseModel):
    id: int
    name: str
    workspace_code: str | None = None
    kavach_station_id: str
    status: str
    layout_version: str
    assigned_designer: str | None = None
    assigned_checker: str | None = None
    created_by: str | None = None
    days_in_status: int | None = None
    last_action: str | None = None
    last_actor: str | None = None
    last_at: str | None = None
    fail_count: int
    warn_count: int
    open_observations: int
    unverified_observations: int
    missing_inputs: int
    tags: int
    railway_reference: str | None = None
    baselines: int = 0


class DashboardOut(BaseModel):
    stations: list[DashboardRow]
    by_status: dict[str, int]
    total: int


class AssignDesignerRequest(BaseModel):
    designer_username: str | None = None   # None / "" = unassign (any designer)
    comment: str = ""


class VersionUpdateRequest(BaseModel):
    kavach_version: str | None = None
    sip_version: str | None = None
    guideline_version: str | None = None
    sip_drawing_number: str | None = None
    reason: str = Field(min_length=1)


class StationChangeOut(BaseModel):
    id: int
    field: str
    before: str | None = None
    after: str | None = None
    reason: str | None = None
    changed_by: str
    changed_by_role: str
    changed_at: str

    class Config:
        from_attributes = True


class BaselineCreate(BaseModel):
    label: str = Field(min_length=1)
    notes: str | None = None


class BaselineOut(BaseModel):
    id: int
    label: str
    layout_version: str
    station_status: str
    notes: str | None = None
    checklist_version: int | None = None
    verification_summary: dict | None = None
    input_snapshot: list[dict] | None = None
    counts: dict = {}
    created_by: str
    created_at: str

    @field_validator("verification_summary", "input_snapshot", mode="before")
    @classmethod
    def _j(cls, v):
        return json.loads(v) if isinstance(v, str) else v

    @model_validator(mode="before")
    @classmethod
    def _from_orm_with_counts(cls, data):
        """Add element/tag/TIN counts from the (not exposed) layout snapshot."""
        if isinstance(data, dict):
            return data
        out = {f: getattr(data, f) for f in cls.model_fields if hasattr(data, f)}
        try:
            snap = json.loads(getattr(data, "layout_snapshot", "") or "{}")
            out["counts"] = {x: len(snap.get(x, [])) for x in ("elements", "tags", "tins")}
        except ValueError:
            pass
        return out

    class Config:
        from_attributes = True


class DiffRow(BaseModel):
    item: str
    change: str          # added | removed | changed
    details: list[str] = []


class BaselineDiffOut(BaseModel):
    baseline: BaselineOut
    current_layout_version: str
    current_status: str
    rows: list[DiffRow]
    inputs_changed: list[str]
    identical: bool


StationCreateRequest.model_rebuild()
