import json

from pydantic import BaseModel, Field, field_validator
from .domain import ELEMENT_TYPES, TAG_TYPES, MAX_CHAINAGE_KM


def _check_km(v, field_name: str):
    if v is not None and abs(v) > MAX_CHAINAGE_KM:
        raise ValueError(
            f"{field_name}={v:g} is not a plausible km value (max {MAX_CHAINAGE_KM:g}). "
            f"Locations are in km -- did you mean {v / 1000:g}?")
    return v


class StationCreate(BaseModel):
    name: str
    kavach_station_id: str
    sip_drawing_number: str | None = None
    kavach_version: str | None = None
    sip_version: str | None = None
    guideline_version: str | None = None
    drawn_to_scale: bool = True
    not_to_scale_note_present: bool = False


class StationOut(StationCreate):
    id: int
    status: str
    layout_version: str
    created_by: str | None = None
    assigned_checker: str | None = None

    class Config:
        from_attributes = True


class ElementCreate(BaseModel):
    element_ref: str
    element_type: str = Field(description=f"One of: {', '.join(ELEMENT_TYPES)}")
    location_km: float
    direction: str | None = None
    remarks: str | None = None
    source_document_id: int | None = Field(
        default=None, description="Input document (SIP/DXF etc.) this row was derived from -- FR-011")

    @field_validator("location_km")
    @classmethod
    def _km(cls, v):
        return _check_km(v, "location_km")


class ElementOut(ElementCreate):
    id: int

    # Output must never fail on legacy rows that predate the km guard (e.g. values
    # stored in metres) -- override the input validator with a pass-through so they
    # can still be listed, fixed, and flagged by the DATA-UNITS verification check.
    @field_validator("location_km")
    @classmethod
    def _km(cls, v, info=None):
        return v

    class Config:
        from_attributes = True


class TagCreate(BaseModel):
    tag_ref: str
    tag_type: str = Field(description=f"One of: {', '.join(TAG_TYPES)}")
    location_km: float
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

    @field_validator("location_km")
    @classmethod
    def _km(cls, v):
        return _check_km(v, "location_km")

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

    # Output must never fail on legacy rows that predate the km guard (e.g. values
    # stored in metres) -- override the input validator with a pass-through so they
    # can still be listed, fixed, and flagged by the DATA-UNITS verification check.
    @field_validator("location_km")
    @classmethod
    def _km(cls, v, info=None):
        return v

    class Config:
        from_attributes = True


class TINCreate(BaseModel):
    tin_no: int
    section_type: str  # Station | Block
    color: str | None = None
    start_km: float
    end_km: float
    direction: str | None = None
    is_non_kavach_territory: bool = False
    remarks: str | None = None
    source_document_id: int | None = None

    @field_validator("start_km", "end_km")
    @classmethod
    def _km(cls, v, info):
        return _check_km(v, info.field_name)


class TINOut(TINCreate):
    id: int

    # Output must never fail on legacy rows that predate the km guard (e.g. values
    # stored in metres) -- override the input validator with a pass-through so they
    # can still be listed, fixed, and flagged by the DATA-UNITS verification check.
    @field_validator("start_km", "end_km")
    @classmethod
    def _km(cls, v, info=None):
        return v

    class Config:
        from_attributes = True


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
    suggested_location_km: float | None = None


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
    location_km: float | None = None
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
