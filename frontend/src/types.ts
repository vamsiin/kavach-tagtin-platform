// Generated to match backend/app/domain.py's ELEMENT_TYPES exactly -- keep these
// in sync; the backend independently validates against its own list regardless of
// what this dropdown offers, so a mismatch here would show an option that then
// fails on submit with a 422, not silently accept something invalid.
export const SIGNAL_ELEMENT_TYPES = [
  "Distant Signal",
  "Inner Distant Signal",
  "IB Distant Signal",
  "IB Inner Distant Signal",
  "Mainline Starter",
  "Loopline Starter",
  "Intermediate Starter",
  "Advanced Starter Signal",
  "IB Stop Signal",
  "Gate Stop Signal",
  "Calling-on Signal",
  "Gate Distant Signal",
  "Gate Inner Distant Signal",
  "Main Home without Junction Route Indicator",
  "Main Home with Junction Route Indicator",
  "Routing Home without Junction Type Route Indicator",
  "Routing Home with Junction Type Route Indicator",
  "Advanced Starter-cum-Gate Signal",
  "BSLB Board",
  "Stop Board/Buffer Stop",
  "Berthing Track End",
  "Gate-cum-Distant Signal",
  "Auto Signal (Excludes Gate Stop Signal in Auto Territory)",
  "Semi-Automatic Signal with A-marker lit",
  "Semi Automatic Signal without A marker lit",
  "Various Home Signals",
  "Gate Cum IB Distant Signal",
  "Gate Cum IB Inner Distant Signal",
  "Advanced Starter-cum-Distant Signal",
  "Gate Stop Signal in Auto Territory",
  "Advance Starter-cum-Gate Inner Distant Signal",
  "Gate-cum-Inner Distant Signal",
  "Gate Inner Distant-cum-Distant Signal",
  "IB Signal-cum-Gate Distant Signal",
  "IB Signal-cum-Gate Inner Distant Signal",
  "IB Signal-cum-Distant Signal",
  "Advanced Starter-cum-IB Distant",
  "Starter-cum-IB Distant Signal",
  "Various types of Starter Signals",
  "Advance Starter-cum-Gate Distant Signal",
  "Shunt Signal",
  "Other Misc Signals",
] as const;

// Physical, non-signal elements (Annexure-H H2.9, H2.10, H2.22, H2.27).
export const LC_GATE = "LC Gate";
export const POINTS = "Points / Turnout";
export const NON_SIGNAL_ELEMENT_TYPES = [
  LC_GATE, POINTS, "Fouling Mark", "Marker Board", "Axle Counter", "Whistle Board (W/L)",
] as const;
export const ELEMENT_TYPES: readonly string[] = [...SIGNAL_ELEMENT_TYPES, ...NON_SIGNAL_ELEMENT_TYPES];
export const POINTS_TYPE = "Points / Turnout";

/** Mirrors backend domain.requires_signal_foot_tag / suitable_link / LINK_HINTS. */
const FOOT_TAG_KEYWORDS = ["Home", "Starter", "Stop Signal", "Stop Board", "Buffer Stop", "Berthing Track End", "BSLB",
  "Calling-on", "Calling on", "Auto Signal", "Semi-Automatic", "Semi Automatic", "Shunt"];
export const LINK_HINTS: Record<string, string> = {
  S: "the signal, stop board, BSLB or shunt signal this foot tag is at",
  T: "the points / turnout this TIN-discrimination tag is for",
  G: "the LC gate this gate tag protects",
  L: "the last stop signal (Advanced Starter) the adjacent-line tag follows",
  D: "the points or dead end this dead-stop tag protects",
  X: "the points leading to the siding / non-KAVACH line",
  N: "the signal this approach tag announces (optional)",
};
export function isSuitableLink(tagType: string, elementType: string): boolean {
  switch (tagType) {
    case "S": return FOOT_TAG_KEYWORDS.some((k) => elementType.includes(k));
    case "T": case "X": return elementType === POINTS_TYPE;
    case "G": return elementType === "LC Gate";
    case "L": return elementType.includes("Starter") || elementType.includes("Stop Signal");
    case "D": return [POINTS_TYPE, "Stop Board/Buffer Stop", "Berthing Track End"].includes(elementType);
    case "N": return (SIGNAL_ELEMENT_TYPES as readonly string[]).includes(elementType);
    default: return true;
  }
}

export const TAG_TYPES = ["N", "S", "T", "X", "D", "G", "L", "A"] as const;

export const LC_CLASSES = ["Special", "A", "B", "C", "D"];
export const LC_MANNING = ["Manned interlocked", "Manned non-interlocked", "Unmanned"];
export const TRACK_TYPES = ["Main", "Loop", "Siding", "Block", "Other"];
/** Line-type classification: the five running lines; everything else (sidings, misc lines) is OTHER. */
export const LINE_TYPES = ["UP MAIN", "DN MAIN", "UP LOOP", "DN LOOP", "COMMON LOOP", "OTHER"];

/** Line type from a name as written on the layout ("DN.MAIN", "Up Loop 2") -- mirrors the backend. */
export function guessLineType(name: string): string {
  let n = name.toUpperCase().replace(/[\s._-]+/g, " ").trim().replace(/^DOWN /, "DN ").replace(/ LINE$/, "");
  for (const lt of LINE_TYPES.slice(0, -1)) {
    if (n === lt || new RegExp(`^${lt}( ?(NO\\.? ?)?\\d+)?$`).test(n)) return lt;
  }
  return "OTHER";
}

/** Direction a line of this type normally runs under the zone's convention. */
export function expectedLineDirection(lineType: string, dnDirection: "Nominal" | "Reverse" = "Nominal"): string {
  const other = dnDirection === "Nominal" ? "Reverse" : "Nominal";
  if (lineType === "DN MAIN" || lineType === "DN LOOP") return dnDirection;
  if (lineType === "UP MAIN" || lineType === "UP LOOP") return other;
  if (lineType === "COMMON LOOP") return "Both";
  return "";
}

export const KIND_FOR_LINE_TYPE: Record<string, string> = {
  "UP MAIN": "Main", "DN MAIN": "Main", "UP LOOP": "Loop", "DN LOOP": "Loop", "COMMON LOOP": "Loop",
};
export const LINE_CONFIGS = ["Single", "Double", "Multiple"];

export interface Track {
  id: number;
  name: string;
  track_type: string;
  start_m: number;
  end_m: number;
  direction: string | null;
  line_type?: string | null;
  is_kavach: boolean;
  sort_order: number;
  remarks: string | null;
  source_document_id?: number | null;
}

export interface StationBorder {
  id?: number;
  line_label: string;
  border_m: number;
  border_tag_ref: string | null;
  track_id: number | null;
  neighbour_line?: string | null;   // the line it continues as at the neighbour
}

export interface AdjacentStation {
  id: number;
  borders: StationBorder[];
  name: string;
  side: string;
  kavach_station_id: string | null;
  border_m: number | null;
  distance_m: number | null;
  line_config: string | null;
  remarks: string | null;
}

export const TAG_TYPE_LABELS: Record<string, string> = {
  N: "Normal / Inline section tag",
  S: "Signal Foot Tag",
  T: "TIN Discrimination / Turnout Tag",
  X: "Exit Tag",
  D: "Dead Stop Tag",
  G: "LC Gate Tag",
  L: "Adjacent Line Info Tag",
  A: "Adjustment / Junction Tag",
};

export interface Station {
  id: number;
  name: string;
  kavach_station_id: string;
  sip_drawing_number: string | null;
  kavach_version: string | null;
  sip_version: string | null;
  guideline_version: string | null;
  drawn_to_scale: boolean;
  not_to_scale_note_present: boolean;
  status: string;
  layout_version: string;
  created_by: string | null;
  assigned_checker: string | null;
  assigned_designer?: string | null;
  centre_line_m?: number | null;
  workspace_id?: number | null;
  workspace_code?: string | null;
}

export interface Element {
  id: number;
  element_ref: string;
  element_type: string;
  location_m: number;
  direction: string | null;
  remarks: string | null;
  source_document_id?: number | null;
  track_id?: number | null;
  to_track_id?: number | null;
  lc_class?: string | null;
  lc_manning?: string | null;
}

export interface Tag {
  id: number;
  tag_ref: string;
  tag_type: string;
  location_m: number;
  tag_number: number | null;
  direction: string | null;
  tin_no: number | null;
  linked_element_id: number | null;
  is_duplicate: boolean;
  pair_group_id: string | null;
  legend_shape: string | null;
  exit_set: string | null;
  is_border_tag: boolean;
  remarks: string | null;
  source_document_id?: number | null;
  track_id?: number | null;
}

export interface TIN {
  id: number;
  tin_no: number;
  section_type: string;
  color: string | null;
  start_m: number;
  end_m: number;
  direction: string | null;
  is_non_kavach_territory: boolean;
  remarks: string | null;
  source_document_id?: number | null;
  track_id?: number | null;
}

export interface CheckResult {
  clause: string;
  title: string;
  status: "PASS" | "FAIL" | "WARN" | "NA" | "DEVIATION";
  message: string;
  subject_ref: string | null;
}

/** A failing automated check accepted as fitting this station's SIP / LC arrangement. */
export interface CheckDeviation {
  id: number;
  clause: string;
  subject_ref: string | null;
  reason: string;
  reference: string | null;
  created_by: string;
  created_by_role: string;
  created_at: string;
  in_use: boolean;
}

export interface VerificationReport {
  results: CheckResult[];
  summary: {
    total_checks: number;
    fail_count: number;
    warn_count: number;
    deviation_count?: number;
    clauses_checked: string[];
    clauses_failing: string[];
  };
  manual_clauses: Record<string, string>;
  checklist_version?: number | null;
  rules_disabled?: string[];
  deviations_unused?: string[];
}

export interface ChainCheckResult {
  route_s_no: string;
  entry_signal: string;
  exit_signal: string;
  status: "PASS" | "FAIL" | "WARN";
  message: string;
  tag_ref: string | null;
}

export interface ToCCrossValidation {
  results: ChainCheckResult[];
  summary: {
    total_checks: number;
    fail_count: number;
    routes_with_failures: string[];
    missing_tags: string[];
  };
}

export const ROLES = ["designer", "checker", "approver", "project_manager", "config_manager", "admin"] as const;
export const ROLE_LABELS: Record<string, string> = {
  designer: "Designer", checker: "Checker (Verifier)", approver: "Approver",
  project_manager: "Project Manager", config_manager: "Configuration Manager", admin: "Administrator",
};
export type Role = (typeof ROLES)[number];

export interface User {
  id: number;
  username: string;
  full_name: string;
  email: string;
  role: Role;
  is_active: boolean;
  role_label?: string;
  permissions?: string[];
}

export interface TokenResponse {
  access_token: string;
  token_type: string;
  user: User;
}

export interface WorkflowEvent {
  id: number;
  station_id: number;
  from_status: string;
  to_status: string;
  action: string;
  actor_username: string;
  actor_role: string;
  comment: string;
  timestamp: string;
  verification_fail_count: number | null;
  target_username: string | null;
  input_snapshot?: InputSnapshotItem[] | null;
}

export interface WorkflowStatus {
  status: string;
  submitted_by: string | null;
  checked_by: string | null;
  assigned_checker: string | null;
  self_checked_by?: string | null;
  assigned_designer?: string | null;
  allowed_actions: string[];
  history: WorkflowEvent[];
}

export const STATUS_LABELS: Record<string, string> = {
  draft: "Draft",
  self_checked: "Self-checked",
  submitted: "Submitted for check",
  checked: "Checked",
  approved: "Approved",
  railway_submitted: "Submitted to Railway",
};

export const ACTION_LABELS: Record<string, string> = {
  self_check: "Run self-check",
  revise: "Revise (back to draft)",
  railway_submit: "Record Railway submission",
  submit: "Submit for check",
  check: "Mark checked",
  approve: "Approve",
  request_changes: "Request changes",
  reopen: "Reopen",
  reassign: "Reassign checker",
};


// ---- Phase 1: design inputs, DXF import, traceability ----
export interface DocType {
  code: string;
  label: string;
  extensions: string[];
  required: boolean;
}

export interface InputDocument {
  id: number;
  station_id: number;
  doc_type: string;
  revision: number;
  version_label: string | null;
  original_filename: string;
  content_type: string | null;
  size_bytes: number;
  sha256: string;
  uploaded_by: string;
  uploaded_at: string;
  notes: string | null;
  is_current: boolean;
}

export interface InputSnapshotItem {
  id: number;
  doc_type: string;
  revision: number;
  version_label: string | null;
  sha256: string;
  original_filename: string;
}

export interface DxfCandidate {
  index: number;
  text: string;
  layer: string;
  x: number;
  y: number;
  kind: "tag" | "element" | "unclassified";
  suggested_location_m: number | null;
}

export interface DxfImportResult {
  document: InputDocument;
  candidates: DxfCandidate[];
  warnings: string[];
  layers: string[];
}

export interface DxfCalibration {
  ref_x?: number;
  ref_m?: number;
  units_per_m?: number;
}

export interface DxfCommitPayload {
  elements: Partial<Element>[];
  tags: (Partial<Tag> & { linked_element_ref?: string | null })[];
}

export interface TraceDocRef {
  id: number;
  doc_type: string;
  revision: number;
  version_label: string | null;
  original_filename: string;
  is_current: boolean;
}

export interface TraceRow {
  kind: "tag" | "element" | "tin";
  id: number;
  ref: string;
  type: string | null;
  location_m: number | null;
  source: TraceDocRef | null;
  source_outdated: boolean;
  linked_element_ref: string | null;
}

export interface Traceability {
  station_id: number;
  station_name: string;
  layout_version: string;
  status: string;
  inputs: InputDocument[];
  rows: TraceRow[];
  workflow: WorkflowEvent[];
  gaps: string[];
  summary: Record<string, number>;
}

// ---- Phase 2: railway submission ----
export interface RailwaySubmitPayload {
  reference_no: string;
  submitted_on: string;
  addressed_to?: string;
  remarks?: string;
}

export interface RailwaySubmission {
  id: number;
  station_id: number;
  workflow_event_id: number | null;
  layout_version: string;
  reference_no: string;
  submitted_on: string;
  addressed_to: string | null;
  remarks: string | null;
  recorded_by: string;
  recorded_at: string;
  verification_fail_count: number | null;
  layout_snapshot: { elements: unknown[]; tags: unknown[]; tins: unknown[]; station: Record<string, unknown> };
  input_snapshot: InputSnapshotItem[] | null;
}

// ---- Phase 3: observations (FR-008) ----
export const OBS_SEVERITIES = ["major", "minor", "info"] as const;
export const OBS_CATEGORIES = ["annexure-h", "toc", "drafting", "data", "inputs", "other"] as const;
export const OBS_STATUS_LABELS: Record<string, string> = {
  open: "Open", resolved: "Resolved – awaiting verification", closed: "Closed",
  reopened: "Reopened", withdrawn: "Withdrawn",
};

export interface ObservationComment {
  id: number;
  action: string;
  from_status: string | null;
  to_status: string | null;
  author: string;
  author_role: string;
  text: string | null;
  created_at: string;
}

export interface Observation {
  id: number;
  station_id: number;
  obs_no: number;
  label: string;
  description: string;
  severity: string;
  category: string | null;
  clause: string | null;
  subject_kind: string;
  subject_id: number | null;
  subject_ref: string | null;
  subject_exists: boolean;
  status: string;
  raised_by: string;
  raised_by_role: string;
  raised_at: string;
  raised_at_status: string | null;
  layout_version: string | null;
  resolved_by: string | null;
  resolved_at: string | null;
  closed_by: string | null;
  closed_at: string | null;
  comments: ObservationComment[];
  allowed_actions: string[];
}

export interface ObservationSummary {
  total: number;
  by_status: Record<string, number>;
  unresolved: number;
  unverified: number;
}

export interface ObservationDraft {
  description?: string;
  severity?: string;
  category?: string;
  clause?: string;
  subject_kind?: string;
  subject_id?: number | null;
  subject_ref?: string | null;
}

// ---- Phase 4: reports & revisions ----
export interface ReportType {
  code: string;
  title: string;
  description: string;
  formats: string[];
}

export interface GeneratedReport {
  id: number;
  report_type: string;
  report_id: string;
  fmt: string;
  generated_by: string;
  generated_at: string;
  layout_version: string | null;
  station_status: string | null;
  sha256: string;
  size_bytes: number;
  archived: boolean;
  workflow_event_id: number | null;
  trigger: string | null;
}

export interface Revision {
  id: number;
  rev_no: string;
  date: string | null;
  description: string;
  layout_version: string | null;
  created_by: string | null;
  created_at: string | null;
}

// ---- Phase 5: configurable checklist (FR-006) ----
export interface ParamSchema {
  name: string;
  type: "number" | "int" | "bool" | "str" | "tag_types" | "element_types" | "choice" | "parity_map";
  label: string;
  required: boolean;
  min: number | null;
  options: string[] | null;
  nullable: boolean;
}

export interface ChecklistRule {
  id: number;
  key: string;
  kind: string;
  builtin: string | null;
  clause: string;
  title: string;
  description: string | null;
  params: Record<string, unknown>;
  severity: "FAIL" | "WARN";
  enabled: boolean;
  blocking: boolean;
  sort_order: number;
  is_builtin: boolean;
  updated_by: string | null;
  updated_at: string | null;
  param_schema: ParamSchema[];
  override?: { params: Record<string, unknown> | null; severity: string | null; enabled: boolean | null;
    reason: string | null; updated_by: string | null; updated_at: string | null } | null;
  effective?: { params: Record<string, unknown>; severity: "FAIL" | "WARN"; enabled: boolean } | null;
}

export interface Checklist {
  config_version: number;
  rules: ChecklistRule[];
  kinds: Record<string, ParamSchema[]>;
  can_edit: boolean;
}

export interface ChecklistChange {
  id: number;
  rule_key: string | null;
  action: string;
  before: unknown;
  after: unknown;
  reason: string | null;
  changed_by: string;
  changed_at: string;
  workspace_id?: number | null;
}

export interface ManualItem {
  rule_id: number;
  clause: string;
  title: string;
  description: string | null;
  blocking: boolean;
  severity: string;
  status: "PASS" | "FAIL" | "NA" | null;
  note: string | null;
  responded_by: string | null;
  responded_at: string | null;
}

export interface ManualChecklist {
  items: ManualItem[];
  summary: { total: number; answered: number; pending_blocking: string[]; failed: string[] };
  can_respond: boolean;
}

// ---- Phase 6: roles, dashboard, configuration management ----
export interface DashboardRow {
  id: number;
  name: string;
  workspace_code?: string | null;
  kavach_station_id: string;
  status: string;
  layout_version: string;
  assigned_designer: string | null;
  assigned_checker: string | null;
  created_by: string | null;
  days_in_status: number | null;
  last_action: string | null;
  last_actor: string | null;
  last_at: string | null;
  fail_count: number;
  warn_count: number;
  open_observations: number;
  unverified_observations: number;
  missing_inputs: number;
  tags: number;
  railway_reference: string | null;
  baselines: number;
}

export interface Dashboard {
  stations: DashboardRow[];
  by_status: Record<string, number>;
  total: number;
}

export interface StationChange {
  id: number;
  field: string;
  before: string | null;
  after: string | null;
  reason: string | null;
  changed_by: string;
  changed_by_role: string;
  changed_at: string;
}

export interface Baseline {
  id: number;
  label: string;
  layout_version: string;
  station_status: string;
  notes: string | null;
  checklist_version: number | null;
  verification_summary: { fail_count: number; warn_count: number; total_checks: number } | null;
  input_snapshot: InputSnapshotItem[] | null;
  counts: { elements?: number; tags?: number; tins?: number };
  created_by: string;
  created_at: string;
}

export interface BaselineDiff {
  baseline: Baseline;
  current_layout_version: string;
  current_status: string;
  rows: { item: string; change: "added" | "removed" | "changed"; details: string[] }[];
  inputs_changed: string[];
  identical: boolean;
}

// ---- RFID Tag / TIN allotment charts (BR-001, FR-004) ----
export interface AllotmentRow {
  id?: number | null;
  s_no: string | null;
  name: string;
  division_code: string | null;
  station_code: string | null;
  station_id: string | null;
  tin_ranges: string | null;
  tin_allotted: string | null;
  tag_ranges: string | null;
  tag_total: number | null;
  remarks: string | null;
  tag_count?: number;
  tin_count?: number;
  problems?: string[];
}

export interface AllotmentChart {
  id: number;
  title: string;
  division: string;
  reference_no: string | null;
  issued_on: string | null;
  issued_by: string | null;
  remarks: string | null;
  is_current: boolean;
  source_filename: string | null;
  source_sha256: string | null;
  created_by: string;
  created_at: string;
  superseded_by_id: number | null;
  row_count: number;
  workspace_id?: number | null;
  workspace_code?: string | null;
}

export interface AllotmentChartDetail extends AllotmentChart {
  rows: AllotmentRow[];
  warnings: string[];
}

export interface AllotmentParse {
  rows: AllotmentRow[];
  warnings: string[];
  errors: string[];
}

export interface NumberUse { number: number; ref: string; owner: string | null }

export interface AllotmentUsage {
  allotted: number;
  used_in_own: number;
  free: number;
  free_ranges: string;
  next_free_odd: number | null;
  next_free_even: number | null;
  used: NumberUse[];
  outside: NumberUse[];
}

export interface StationAllotment {
  chart: AllotmentChart | null;
  own: AllotmentRow | null;
  adjacent: { adjacent_name: string; row: AllotmentRow | null }[];
  tags: AllotmentUsage | null;
  tins: AllotmentUsage | null;
}

// ---- Workspaces (railway zones) ----
export interface Workspace {
  id: number;
  code: string;
  name: string;
  dn_direction: "Nominal" | "Reverse";   // KAVACH direction of the SIP's Down movements
  open_to_all: boolean;
  remarks: string | null;
  created_by: string | null;
  created_at: string | null;
  members: string[];
  station_count: number;
  override_count: number;
}

/** "Nominal (DN)" / "Reverse (UP)" in SCR; "Nominal (UP)" / "Reverse (DN)" in ECR. */
export function directionLabel(dir: string, dnDirection: string | undefined | null): string {
  if (dir !== "Nominal" && dir !== "Reverse") return dir;
  const dn = (dnDirection ?? "Nominal") === dir;
  return `${dir} (${dn ? "DN" : "UP"})`;
}
