// Generated to match backend/app/domain.py's ELEMENT_TYPES exactly -- keep these
// in sync; the backend independently validates against its own list regardless of
// what this dropdown offers, so a mismatch here would show an option that then
// fails on submit with a 422, not silently accept something invalid.
export const ELEMENT_TYPES = [
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
  "Other Misc Signals",
] as const;

export const TAG_TYPES = ["N", "S", "T", "X", "D", "G", "L", "A"] as const;

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
}

export interface Element {
  id: number;
  element_ref: string;
  element_type: string;
  location_km: number;
  direction: string | null;
  remarks: string | null;
  source_document_id?: number | null;
}

export interface Tag {
  id: number;
  tag_ref: string;
  tag_type: string;
  location_km: number;
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
}

export interface TIN {
  id: number;
  tin_no: number;
  section_type: string;
  color: string | null;
  start_km: number;
  end_km: number;
  direction: string | null;
  is_non_kavach_territory: boolean;
  remarks: string | null;
  source_document_id?: number | null;
}

export interface CheckResult {
  clause: string;
  title: string;
  status: "PASS" | "FAIL" | "WARN" | "NA";
  message: string;
  subject_ref: string | null;
}

export interface VerificationReport {
  results: CheckResult[];
  summary: {
    total_checks: number;
    fail_count: number;
    warn_count: number;
    clauses_checked: string[];
    clauses_failing: string[];
  };
  manual_clauses: Record<string, string>;
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

export const ROLES = ["designer", "checker", "approver", "admin"] as const;
export type Role = (typeof ROLES)[number];

export interface User {
  id: number;
  username: string;
  full_name: string;
  email: string;
  role: Role;
  is_active: boolean;
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
  allowed_actions: string[];
  history: WorkflowEvent[];
}

export const STATUS_LABELS: Record<string, string> = {
  draft: "Draft",
  submitted: "Submitted for check",
  checked: "Checked",
  approved: "Approved",
};

export const ACTION_LABELS: Record<string, string> = {
  submit: "Submit for check",
  check: "Mark checked",
  approve: "Approve",
  request_changes: "Request changes",
  reopen: "Reopen",
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
  suggested_location_km: number | null;
}

export interface DxfImportResult {
  document: InputDocument;
  candidates: DxfCandidate[];
  warnings: string[];
  layers: string[];
}

export interface DxfCalibration {
  ref_x?: number;
  ref_km?: number;
  units_per_km?: number;
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
  location_km: number | null;
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
