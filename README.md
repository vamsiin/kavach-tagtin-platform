# KAVACH RFID Tag/TIN Layout Design & Verification Platform

Web platform for designing and verifying KAVACH RFID Tag/TIN layouts against
RDSO/SPN/196/2020 Annexure-H (Amdt-5), with cross-validation against a station's
own Table of Control (ToC) — see `backend/app/toc/cross_validate.py` for why that
matters more than static distance-rule checking alone.

This is Phases 0–1 (+ core of 3–4) of the phased roadmap in the accompanying
proposal document: core data model, a codified rules engine, ToC cross-validation,
and a working (if visually basic) web app. The interactive chainage-based canvas
editor (Phase 5) and calibrated AutoCAD import (Phase 2, needs a real sample .dxf)
are the two pieces still ahead — see "Honest limitations" below.

# KAVACH RFID Tag/TIN Layout Design & Verification Platform

Web platform for designing and verifying KAVACH RFID Tag/TIN layouts against
RDSO/SPN/196/2020 Annexure-H (Amdt-5), with cross-validation against a station's
own Table of Control (ToC) — see `backend/app/toc/cross_validate.py` for why that
matters more than static distance-rule checking alone.

This is Phases 0–1 (+ core of 3–4) of the phased roadmap in the accompanying
proposal document: core data model, a codified rules engine, ToC cross-validation,
auth + Producer→Checker→Approver workflow, and a working (if visually basic) web
app. The interactive chainage-based canvas editor (Phase 5) and calibrated AutoCAD
import (Phase 2, needs a real sample .dxf) are the two pieces still ahead — see
"Honest limitations" below.

## Verification status

**This matters more than usual for this project**, because a rules engine for a
safety-adjacent domain that silently has a bug is worse than no rules engine at all.
This platform has now been verified at three separate levels, not just unit tests:

| Level | What was actually run | Result |
|---|---|---|
| Unit tests | `pytest tests/` — 71 tests covering rules engine, ToC parser/cross-validation, DXF import classification, password hashing + JWT, workflow state machine | ✅ **71/71 pass** |
| Backend integration | Real `uvicorn` process, hit over actual HTTP: register → login → create station → add elements → submit for check → run verification → **full forgot-password lifecycle** (request reset, capture console-logged token, reset password, confirm old password rejected, confirm new password works, confirm the token cannot be replayed) | ✅ All flows confirmed working end-to-end, not just at the function level |
| Frontend build | Real `npm install` + `npm run build` (`tsc -b && vite build`) — the actual TypeScript compiler and Vite bundler, not a filtered/simulated check | ✅ **Zero errors**, clean production bundle. Real `npm run dev` server also confirmed serving. CORS confirmed to correctly allow the frontend origin. |

What's genuinely still unverified: nobody has clicked through the UI in a real
browser yet (a headless-browser click-through was attempted but blocked by a
sandboxed environment's network restrictions on the Chromium download — not a code
issue). Everything underneath the UI (the API it calls) has been exercised for real.

Two real bugs were caught and fixed during this verification process, both worth
knowing about even though they're already fixed:
1. A relative-import collision (`app/routers/auth.py` importing `.security` instead
   of `..auth.security`, because a sibling package was also named `auth`) that broke
   `uvicorn app.main:app --reload` on startup — caught when a user actually ran it.
2. An editing accident that orphaned the body of `create_jwt` while adding the
   password-reset feature — caught immediately by re-running the test suite before
   moving on, per the workflow this project follows for every non-trivial change.

Run the tests yourself:
```bash
cd backend
pip install -r requirements.txt
pytest tests/          # 71 tests
```
(A stdlib-only runner also exists at `backend/tests/run_tests.py` for environments
where `pip install` isn't available — same tests, zero dependencies.)

## Setup

### Backend
```bash
cd backend
python3 -m venv venv && source venv/bin/activate    # Windows: venv\Scripts\activate
pip install -r requirements.txt
pytest tests/
uvicorn app.main:app --reload  # http://localhost:8000, docs at /docs

# First run: bootstrap an admin account (register is only open until the first user exists)
python3 scripts/bootstrap_admin.py --username admin --full-name "Platform Admin" --password <choose one>
```
Uses SQLite by default (`kavach.db`, created on first run). Set `DATABASE_URL` to a
Postgres DSN for anything beyond local dev — no code changes needed, SQLAlchemy
abstracts the dialect. Set `JWT_SECRET` to something real before anyone but you uses
this — `auth/deps.py` falls back to an obviously-fake dev secret otherwise.

**Forgot the admin password and there's no other admin to reset it?**
```bash
python3 scripts/reset_password.py --username admin --password <new password>
```
This writes directly to the database file — it's a deliberate last resort that
requires filesystem access to the machine running the platform, not something
reachable over the API (see the script's docstring for why that's the right
trust boundary).

### Frontend
```bash
cd frontend
npm install
npm run dev                    # http://localhost:5173
npm run build                  # production build, outputs to dist/
```
Set `VITE_API_URL` if the backend isn't at `http://localhost:8000`.

## Architecture

```
backend/app/
  domain.py         # plain dataclasses -- the ONLY thing rules/, toc/, and workflow/ depend on
  models.py          # SQLAlchemy ORM, converts to/from domain.py at the boundary
  database.py         # engine/session setup (SQLite dev, Postgres via DATABASE_URL)
  schemas.py           # Pydantic request/response models for the API
  rules/engine.py       # Annexure-H clause checks, each citing its clause number
  toc/parser.py           # parses ToC CSV exports into Route/TagChainEntry objects
  toc/cross_validate.py    # checks drawn tags against ToC-derived expected chains
  dxf_import/importer.py    # AutoCAD DXF import (draft candidates, never auto-commits)
  auth/security.py           # password hashing (PBKDF2) + JWT (HS256) + password-reset tokens, stdlib only
  auth/deps.py                 # FastAPI dependencies: get_current_user, require_role
  workflow/engine.py             # Producer->Checker->Approver state machine
  routers/                        # FastAPI endpoints (stations, verify, auth, workflow)
  main.py                           # FastAPI app assembly

frontend/src/
  types.ts            # TS types mirroring the Pydantic schemas
  api.ts                # typed fetch wrapper, attaches JWT from localStorage
  auth/AuthContext.tsx   # current user, login/logout, session restore on reload
  components/
    LoginScreen.tsx         # login, first-admin bootstrap, and forgot/reset password flows
    StationPanel.tsx          # station selector/creator
    ElementsPanel/TagsPanel/TinsPanel.tsx  # registers, read-only once out of Draft
    VerificationPanel.tsx       # Annexure-H results, clause-cited
    TocPanel.tsx                  # ToC CSV upload + cross-validation
    WorkflowPanel.tsx               # status, role-gated action buttons, history
    UsersPanel.tsx                    # admin-only user management
  App.tsx                                # auth gate + tab shell
```

The domain/persistence split in the backend is deliberate: `rules/`, `toc/`, and
`workflow/` never import SQLAlchemy. That's what let all of the core logic be fully
unit-tested here even though the database and web framework layers couldn't be
installed and run.

## The workflow, concretely

```
DRAFT --submit(designer)--> SUBMITTED --check(checker)--> CHECKED --approve(approver)--> APPROVED
  ^                              |                             |
  |______request_changes_________|_____request_changes_________|
```

Two rules are enforced in code, not just process: a Checker cannot mark a layout
"checked" while the server's own fresh Annexure-H verification still has failures
(the fail count is never trusted from the client — `routers/workflow.py`'s
`check_station` re-runs `run_all_checks` itself), and nobody can check their own
submission or approve their own check (segregation of duties; `admin` is an
intentional exemption for small-team bootstrapping — see `workflow/engine.py`'s
docstring). Registers (Elements/Tags/TINs) are locked from editing once a station
leaves `draft`, so a Checker is reviewing something stable, not a moving target.

## Password reset, concretely

`POST /auth/forgot-password {username}` generates a 15-minute, single-use reset
token. There's no email/SMTP integration in this deployment, so the token is
**printed to the backend server's console**, not emailed or returned in the HTTP
response — returning it to the client would let anyone reset any account (the
endpoint gives an identical response whether or not the username exists, so it
can't be used to enumerate accounts either). An admin with server access reads the
token from the console and relays it to the user out-of-band.

`POST /auth/reset-password {token, new_password}` consumes it. The single-use
guarantee doesn't need a server-side revocation table: the token embeds a fragment
of the password hash at issuance time, so the instant the password actually
changes, a replayed copy of the same token stops validating — proven in
`tests/test_password_reset.py` and again live over real HTTP during this build
(request reset → capture token → reset → confirm old password rejected → confirm
new password works → replay the same token → confirmed blocked).

Two other paths exist for when self-service isn't available: an admin can reset
anyone else's password directly via `POST /auth/users/{username}/reset-password`
(no token needed, since the admin is already authenticated), and
`scripts/reset_password.py` is a last-resort CLI for the "the only admin forgot
their password and nobody can log in at all" case — it writes straight to the
database file, deliberately requiring filesystem access rather than being reachable
over the API.

## Editing, deleting, and station deletion

Every register row (Element/Tag/TIN) has inline edit and delete, gated by the same
draft-only rule as creation — the API enforces this at every one of create/update/
delete, not just create, and the UI hides the controls entirely once a station
leaves Draft rather than showing a button that would just 409.

Deleting an Element that a Tag is linked to doesn't leave a dangling foreign key —
the Tag's `linked_element_id` is set to `null` rather than either cascading the
delete (which would silently remove a Tag the designer didn't ask to delete) or
leaving it pointing at nothing (which would silently break the H2.6/H2.7/H2.9 checks
that join on that link). Confirmed in `tests/test_register_crud.py`.

Station deletion (`DELETE /stations/{id}`) is irreversible and cascades to every
Element, Tag, TIN, and the full workflow audit history for that station (ORM
relationship configuration), with no soft-delete. Who can do it:
- An **admin** can delete any station, in any status.
- The station's **creator** can delete it themselves, but only while it's still
  `draft` — once submitted, that right passes to admins only (mirrors the same
  draft-only philosophy as register edits).
- Everyone else gets a 403, including other designers who didn't create it.

Every `Station` now records `created_by` (the username at creation time) to make
this possible. Databases from before this field existed are upgraded automatically
and safely on startup — see `database.py`'s `ensure_schema_up_to_date()`, a
deliberately minimal SQLite-only "add missing columns" migration (not a substitute
for Alembic if this grows past a single-developer/pilot deployment, but proven here
to correctly add the column, preserve existing data, and set `created_by = NULL` on
stations that predate the field — which correctly falls back to admin-only deletion
for those, since there's no creator on record to defer to). Verified against a
properly-simulated pre-upgrade database with real seeded data, not just an empty one.

Direction dropdown values differ intentionally between Tags and Elements: **Tags**
use "Reverse"/"Nominal" (matching the REVERSE/NOMINAL legend pair from the ALER
drawing); **Elements** use "Reverse"/"Down" (a mix of both legend conventions, per
explicit instruction — Elements section only). Neither is validated by the backend
(direction is a free-text field), so this is purely a UI/data convention, not a
constraint enforced anywhere in the rules engine.

## Element type taxonomy — needs your review

`ELEMENT_TYPES` (`backend/app/domain.py`, mirrored exactly in `frontend/src/types.ts`
— the frontend list is generated from the Python source to guarantee they can't
silently drift apart) now uses the full 41-entry real IR/KAVACH signal taxonomy
instead of the earlier 13-item placeholder list. One consequence worth flagging
explicitly: the old list included non-signal physical elements — **LC Gate,
Turnout/Facing Point, Marker Board, Fouling Mark, LSS** — that have no equivalent
in the new signal-focused list. Nothing in the current rules engine strictly
requires them to exist as a type (H2.9's gate-tag check works off `linked_element_id`
generically, not an element-type match), but if you need to record these on a
layout again, they should probably be added back alongside the new list rather than
staying dropped.

The bigger thing that needed rework: H2.6 ("which elements require a Signal Foot
Tag") and H2.7's Advance/Intermediate Starter distance exception used to key off an
exact set of old type strings (`"Main Signal"`, `"Advance Starter"`, etc.) — none of
which exist in the new taxonomy. Left alone, that would have silently stopped
matching anything, quietly disabling both checks. Both are now keyword-based
classifiers (`requires_signal_foot_tag()` and
`is_starter_signal_eligible_for_h2_7_exception()` in `domain.py`) rather than an
exact-match set, since the new taxonomy has many combination types (e.g.
"Advanced Starter-cum-Gate Signal") that a fixed set can't cover cleanly.

**This classification is a best-effort first draft, not verified ground truth** —
Annexure-H's own text only names broad categories ("Main signal, Subsidiary signal,
Stop board...BSLB"), not each of these 41 specific sub-types, so the mapping below
is domain reasoning, not a literal reading of the clause. Please review it:

| Classified as requiring a Signal Foot Tag | Classified as NOT requiring one |
|---|---|
| All Home signal variants, all Starter signal variants (including every `...-cum-Starter...` combination, since the Starter function is itself a stop signal even combined with a Distant role), Stop signals (IB/Gate/Auto-territory), Calling-on Signal, Auto Signal, Semi-Automatic Signal (both variants), BSLB Board, Stop Board/Buffer Stop, Berthing Track End | Pure Distant signal types (Distant, Inner Distant, IB Distant, IB Inner Distant, Gate Distant, Gate Inner Distant, and their Gate/IB combinations that do NOT also carry a Starter/Home/Stop role) |

Three ambiguous cases deliberately excluded from the "requires" list, worth your
specific attention: `IB Signal-cum-Gate Distant Signal`, `IB Signal-cum-Gate Inner
Distant Signal`, and `IB Signal-cum-Distant Signal` — the bare "IB Signal" portion
of these names could plausibly mean "IB Stop Signal" (which would require a tag) or
just be a generic prefix; the keyword classifier currently treats them as not
requiring one, but this is the single lowest-confidence part of the whole mapping.
`Other Misc Signals` is also deliberately excluded (too generic to classify safely).

## Checker assignment, approver review, and email notifications

Submitting a station for check now requires explicitly assigning a specific
Checker (`POST /stations/{id}/submit` takes `assigned_checker_username`) — the
Designer picks from a live list of active checker accounts (`GET
/auth/users/by-role/{role}`, deliberately available to any authenticated user, not
just admins, since a Designer needs it to populate this dropdown). Once assigned,
only that Checker (or an admin) can act on the submission — any other checker
account gets a 409, not silent access. This is enforced in
`workflow/engine.py`, tested against every role/assignment combination in
`tests/test_workflow.py`, and proven again at the HTTP layer in
`tests/test_workflow_assignment.py`.

The Checker→Approver handoff, by contrast, has no equivalent assignment step —
any active approver may act on a `checked` station — per the original request that
only the Designer→Checker handoff be an explicit assignment. Registers
(Elements/Tags/TINs) are read-only for everyone, including the Designer who
submitted them, from the moment a station leaves `draft` — this was already true
before this change (see "Editing, deleting..." above); assignment doesn't add
anything new here, just confirms it still holds.

**Email notifications** fire at every decision point: checker assignment, the
Checker's approve/reject decision (notifies the Designer only), and the Approver's
approve/reject decision (notifies both the Designer and the Checker). All four are
built on `notifications/email.py` (stdlib `smtplib`, real SMTP when configured via
`SMTP_HOST`/`SMTP_PORT`/`SMTP_USERNAME`/`SMTP_PASSWORD`/`SMTP_FROM_ADDRESS`, console
log otherwise — same honest fallback pattern as the password-reset flow). A failed
send never breaks the workflow action that triggered it (approving a station
shouldn't fail just because the mail server is down) — confirmed with a real
mocked-SMTP-failure test, not just asserted in a docstring. The actual SMTP
send path is also proven with a genuinely mocked `smtplib.SMTP` call (asserting
the right host/port/credentials/message were used), not just the console-fallback
path. Recipient-selection logic (who gets emailed for which decision) is proven at
the HTTP layer in `tests/test_workflow_assignment.py` by mocking the notification
functions and asserting on their actual call arguments after a real workflow
transition — not just testing the email module in isolation.

## User management (Users tab, admin-only)

Every user now has an `email` field (used for the notifications above), and admins
can edit (`PUT /auth/users/{username}`: name/email/role/active status — password
changes still go through the dedicated reset flows, never this endpoint) or delete
(`DELETE /auth/users/{username}`) any account. Two self-lockout guards, both
tested: an admin cannot demote or deactivate their *own* account (must have another
admin do it), and the last remaining admin account cannot be deleted by anyone.
Deleting a user does **not** touch historical `WorkflowEvent` records or
`Station.created_by` — those store the username as plain text, not a foreign key,
specifically so deleting an account never erases audit history (proven in
`test_deleting_user_preserves_audit_history`).

## Multi-format Table of Control uploads

`POST /stations/{id}/verify-toc` now accepts `.csv`, `.xlsx`, `.xls`, and `.docx` in
addition to the original CSV support — see `toc/parser.py`'s module docstring for
the format-by-format honesty breakdown, but the short version:
- **`.csv`** — proven against the real ALER_ToC.csv export (unchanged from before).
- **`.xlsx`** (openpyxl) and **`.docx`** (python-docx) — real, tested by generating
  actual files in each format and parsing them back, including edge cases (numeric
  Excel cells that could get mangled into "1.0" instead of "1"; a Word document that
  splits routes across multiple tables). **Not yet tested against a genuine
  Railway/vendor-exported file in either format** — only synthetic ones built for
  this test suite. The column-index mapping is assumed identical to the CSV layout;
  a real export with a different layout would need `COLUMNS` in `parser.py` adjusted.
- **`.xls`** (xlrd, which only supports the legacy binary format — `.xlsx` supp
  ort was intentionally dropped from xlrd 2.x, which is why openpyxl handles
  `.xlsx` instead) — same caveat as above. Round-trip tested using `xlwt` to
  generate the test file (a write-only, unmaintained library — used here purely
  as a **test dependency** to construct a real `.xls` file to parse, not something
  the running application needs).
- **`.doc`** (legacy Word 97-2003 binary format) — **deliberately not supported.**
  Reliably parsing this format in pure Python without a system tool (LibreOffice,
  antiword) installed on the server isn't something this platform can honestly
  claim to do. Uploading one returns a clear `422` asking for a `.docx`/`.xlsx`/
  `.csv` conversion instead of silently producing wrong or empty data — for a
  compliance cross-validation tool, a clear refusal is better than a wrong answer.

Row identification (which spreadsheet/table row is a real route vs. a header) uses
a content-based rule — the S.No column must be a plain digit string — rather than
"skip exactly N header rows," specifically because non-CSV containers (especially
Word tables) don't reliably put headers at a fixed row count. This also fixed a
latent robustness bug the multi-format testing surfaced: rows shorter than the last
column the parser reads (which happens when a writer trims trailing empty cells,
as `xlwt` does) used to raise `IndexError` instead of being handled gracefully —
now padded rather than crashing, caught by `test_parse_xls` before it could ever
reach a real upload.

## Full audit trail

Every workflow transition (submit — including who it was assigned to — check,
approve, request-changes, reopen) is recorded in `WorkflowEvent` with actor,
role, timestamp (ISO 8601), from/to status, and comment, visible via `GET
/stations/{id}/workflow`'s `history` array and rendered in the Workflow tab. This
already existed before this round of changes; what's new is the `target_username`
field capturing who a submission was assigned to, so the assignment itself is part
of the permanent record, not just implied by which checker happened to act on it.

## Annexure-H alignment (Sep 2026)

**Step 1 — clause numbers.** Checks now carry the Amdt-5 clause numbers: H2.12 duplicate
spacing, H2.13 tag-set spacing (split out of H2.12), H2.15 legend shape, H2.23 numbering
ranges, manual items H2.14 (25 km) and H2.16 (border). Existing checklist rows are renamed in
place on startup (`rules/store.py: migrate_rules`), keeping edits, responses and history.

**Step 2 — lines, new element types, centre line and borders.**
- *Lines* (`tracks` table): named lines (DN MAIN, COMMON LOOP, sidings, block lines) with
  type, extent, direction and KAVACH / non-KAVACH. Elements, tags and TINs carry `track_id`.
- *New element types*: LC Gate (class, manning), Points / Turnout (`to_track_id`: the line it
  leads to), Fouling Mark, Marker Board, Axle Counter, Whistle Board (W/L).
- *Station centre line* (`stations.centre_line_m`) — rule **H2.28** (FAIL if missing, or if it
  lies outside every line).
- *Adjacent stations* (`adjacent_stations`): name, KAVACH ID, side, border line location,
  distance, single/double line, and the border location **per line** with its border tag (e.g. DN line 265.278 S7D,
  UP line 266.417 S30D) — rule **H2.16** (FAIL if none recorded or a border location is
  missing). Can also be sent with `POST /stations` as `adjacent_stations`.
- **DATA-TOPOLOGY** (WARN by default): everything placed on a line and within its extent;
  points join two different lines.
- Baselines/snapshots include lines and neighbours; the layout report has a
  "Lines and neighbouring stations" section.
- API: `/stations/{id}/tracks`, `/stations/{id}/adjacent-stations`, `PUT /stations/{id}/centre-line`.

**Step 3 — RFID Tag / TIN allotment charts (BR-001, FR-004).**
- *Allotment tab*: load a division's chart (import .xlsx / .csv, or `POST /allotment-charts`), attach the
  issued letter (PDF), view rows. Charts are never edited; a revised chart supersedes the current one for its
  division (`make-current` rolls back). Loading needs the Configuration Manager or admin.
- Import checks: every range parses (1-1023 tags, 1-255 TINs, wrap-around like `977-1023, 1-70`), station IDs
  unique; *warnings* for a printed Total that doesn't match the ranges and for overlapping numbers between rows
  close together on the chart (numbers are deliberately reused across a division, so far-apart rows aren't flagged).
- Stations and adjacent stations are matched to rows by KAVACH station ID (`00103` = `103`), else by exact name.
- Rule **BR-001** (FAIL): each tag / TIN number is in the station's own row or an adjacent section's row (the
  layout shows block-section tags up to its borders). WARN only while no chart is loaded at all.
- Registers tab: the station's allotment, used / free counts, free ranges, out-of-allotment numbers; the tag
  form offers the next free odd / even number.

**Step 4 — checks the line model enables, and the New-TAN rules** (`rules/layout_rules.py`).
| Rule | Checks | Default |
|---|---|---|
| H2.8 | a T/N/S/G tag within 50 m of each boundary between TINs on a line | WARN ("as per feasibility") |
| H2.17 | every TIN has a colour, one colour per TIN; neighbouring TINs (consecutive on a line, or joined by points) differ | FAIL |
| H2.20 | every siding / non-KAVACH line has an exit tag on it or within 300 m of the points leading to it | FAIL |
| H2.22 | block TIN's station-side end within 20 m of the BSLB (double line) / Advance Starter (single line), side from the adjacent station's "Lower/Higher km" | FAIL (NA when data is missing) |
| H2.26 | layout not drawn to scale carries the note | FAIL |
| H2.7 | approach distance an exact multiple of 1 m (added to the existing rule) | FAIL |
| H2.9 | a W/L board on the approach side is accepted instead of the gate-tag distance | on |
| TAN-1 | dead stop tag 25–35 m from the facing points | FAIL |
| TAN-2 | adjacent line tag 90–110 m from the last stop signal it is linked to | FAIL |
| TAN-3 | 2 Normal tags within 0.5 × max speed + 10 m (130 km/h → 75 m) of each adjustment tag | FAIL |

Not yet automated: H2.14 / TIN repeat distance (needs station geography across the division), H2.19 TINs per
ToC route, the border-tag RSSI criterion (BR-005).

## BRD (RTLDVMS v1.0) gap analysis — what's covered, what isn't, and two open decisions

A formal Business Requirements Document was checked against this codebase directly
(not from memory) after the fact. Summary — full FR-by-FR detail lives in the
project's change history, not repeated here:

**Newly covered as a direct result of that audit:**
- FR-004 tag reference / tag number **uniqueness** within a station (was entirely
  unchecked before — `rules/engine.py`'s `check_brd_fr004_tag_uniqueness`)
- FR-004 **odd/even tag numbering by direction** (existed in the original Excel
  tool, was never ported to this Python engine — see the open decision below)
- BR-005 / H2.16 **border tag** support — `Tag.is_border_tag` didn't exist at all
  before; now tracked and checked for presence of an absolute location. The full
  BR-005 criterion (RSSI ≥ -70dBm from a Tower RSSI Survey) still needs a dataset
  this platform doesn't ingest, so that part stays in `MANUAL_CLAUSES`.
- The Tag entry form was **missing a `tag_number` field entirely** — discovered
  while wiring up the parity check, since there was no way to trigger it from the
  UI at all before this. Added, along with the border-tag checkbox.

**Two open decisions — nothing below was changed without your confirmation:**

1. **BR-008 says G-tags must be 550–850m from the LC gate.** An earlier round of
   this project deliberately changed that rule to a **≥600m minimum only**, because
   that's what the literal RDSO Annexure-H text says (the 550–850m figure traced to
   a secondary slide deck). The BRD now restates 550–850m as an official rule. This
   might be a genuine QFTL-specific policy stricter than the base standard, or it
   might have inherited the same secondary-source figure. **Not changed** —
   `check_h2_9_gate_tag_distance` in `rules/engine.py` still enforces ≥600m only.
   Confirm which is correct before this matters for a real submission.
2. **FR-004's odd/even rule assumes `Tag.direction`'s "Reverse" == "UP" and
   "Nominal" == "DN"** (`DIRECTION_PARITY_MAP` in `rules/engine.py`), based on the
   ALER drawing legend pairing those terms as the same physical directions. If
   that mapping is backwards, every tag will get a false FAIL or false PASS on
   this specific check — confirm it, and the fix is a one-line change to that map.

**Phase 1 — done (inputs, DXF import, traceability):**
- **FR-001 design inputs** as first-class, versioned entities (`input_documents`
  table, `app/documents/service.py`, `app/routers/documents.py`). Types: SIP,
  SITE_SURVEY, RFID_ALLOCATION_CHART, ADJACENT_LAYOUT, TOC, OTHER — each with its
  own allowed extensions. Every upload is an **immutable revision** (re-upload =
  rev N+1; old revisions kept), with SHA-256, uploader and timestamp. Files live
  under `UPLOAD_DIR` (default `./uploads`, max `MAX_UPLOAD_MB`, default 50).
  Designer/admin only, draft only. Delete is refused if any tag/element/TIN
  traces to the document or it was part of a recorded workflow snapshot.
  UI: **Inputs** tab.
- **FR-002 DXF import is now reachable**: `POST /stations/{id}/import-dxf` stores
  the .dxf as a SIP/Adjacent-Layout revision and returns review candidates;
  `GET …/documents/{doc}/dxf-candidates` re-parses with an optional chainage
  calibration (`ref_x`, `ref_m`, `units_per_m`); `POST …/dxf-commit` writes the
  reviewed rows **all-or-nothing**, stamped with `source_document_id`. Still no
  auto-commit, and the layer heuristics still need real Quadrant DXFs.
- **FR-011 traceability**: `source_document_id` on Tags/Elements/TINs (editable in
  the API; a PUT that omits it keeps the existing link); every workflow event now
  stores an `input_snapshot` of the current input revisions (id, rev, SHA-256).
  `GET /stations/{id}/traceability` returns the matrix plus gaps (missing required
  inputs, untraced tags, rows on superseded revisions). UI: **Traceability** tab.

**Phase 2 — done (FR-009 lifecycle):**
Draft → **Self-checked** → Submitted → Checked → Approved → **Submitted to Railway**.
- `POST /stations/{id}/self-check` runs the full Annexure-H verification on the server;
  only a zero-failure result moves the station to `self_checked` (on failure: 409 with the
  failing clauses, nothing recorded). Registers and inputs are locked there (draft-only).
  `POST …/revise` goes back to draft and discards the self-check.
- **Submit is now only possible from `self_checked`**, and only by the person who
  self-checked (admin exempt). A designer can no longer submit a layout that fails
  automated checks. Request-changes (Rework) and admin reopen both require a fresh
  self-check.
- `POST …/railway-submit` (approver/admin, from `approved` only): reference no., date sent
  (YYYY-MM-DD), addressed to, remarks. Writes a `railway_submissions` record atomically with
  the status change, freezing the registers and input-document revisions as sent. Refused
  if the layout version is INCOMPLETE or verification now fails. `railway_submitted` is
  terminal; only an admin reopen leaves it, and the frozen record is kept.
  `GET …/railway-submissions` lists them.
- Upgrading: stations already `submitted`/`checked`/`approved` carry on unchanged; stations in
  `draft` just need a self-check before their next submit.

**Phase 3 — done (FR-008 observations):**
- `observations` + `observation_comments` tables; lifecycle in `app/observations/rules.py`,
  API in `app/routers/observations.py`. Each observation is numbered per station
  (OBS-001…), has severity (major / minor / info), optional category and clause, and a
  subject (whole layout, a tag, element or TIN; stored without a foreign key so it
  survives the tag being deleted as the fix). Records the layout version and station
  status at the time it was raised.
- Lifecycle: open/reopened → **resolve** (designer/admin, note required) → resolved →
  **close** (checker/approver/admin, not the resolver) → closed; **reopen** from
  resolved/closed (reviewer, reason required); **withdraw** (raiser/admin); comments by
  anyone. Every action is appended to the observation's thread (its audit trail).
- Workflow gates (info severity never blocks): self-check and submit are blocked while
  any observation is open/reopened; check, approve and Railway submission are also
  blocked while any is resolved but not yet closed. Nothing can be raised or changed
  after Railway submission until an admin reopens the station.
- UI: **Observations** tab (with a count badge), and a "Raise observation" link on every
  FAIL/WARN row of the verification results for reviewers, prefilled with clause,
  message and the tag/element concerned.

**Units — chainage in METRES (team decision, Phase 3):** every location is stored and
entered as chainage in metres (e.g. `262910` = km 262.910). Fields are `location_m`
(elements, tags) and `start_m` / `end_m` (TINs); the rules engine and ToC cross-validator
compare them directly with no ×1000 conversion. On startup the database migration renames
the old `location_km` / `start_km` / `end_km` columns in place, keeping the values (they
were already metres). Verification includes a `DATA-UNITS` check that WARNs (never blocks)
when a station's values look like km — all within 50 units of each other and carrying
decimals.

**Phase 4 — done (FR-007 / Section 11 reports):**
- All eight report types, each in **PDF and Word**: Layout, Verification, Compliance,
  Observation, Approval Status, Audit Trail, Traceability Matrix, Revision History.
  `GET /report-types`; `GET /stations/{id}/reports/{type}?format=pdf|docx`.
- Each report is built once as a format-neutral model (`app/reports/model.py`,
  `builders.py`) and rendered by `render_pdf.py` (reportlab) or `render_docx.py`
  (python-docx), so PDF and Word never drift apart. Every page carries the station,
  layout version, a unique report ID (`KVR-<station>-<type>-<timestamp>`), who generated
  it, when, and "Uncontrolled when printed".
- Every generation is logged (`generated_reports`: who, when, format, SHA-256).
  `GET /stations/{id}/report-log`.
- **Verification reports are archived automatically** at each self-check, check,
  approval and Railway submission, linked to that workflow event, and kept on disk as
  the frozen evidence for that step (`…/report-log/{id}/download`). Archiving never
  blocks the workflow — a failure is logged and skipped.
- The drawing revision table (`RevisionORM`, previously unused) is now wired:
  `GET/POST/DELETE /stations/{id}/revisions` (designer/admin, draft only), feeding the
  Revision History report. Workflow events now also record the layout version.
- UI: **Reports** tab. **Requires `pip install -r requirements.txt`** (adds `reportlab`);
  without it Word output still works and PDF returns a clear 503.

**Phase 5 — done (FR-006 configurable checklist):**
- The verification checklist is now data, not code (`checklist_rules`, managed in the
  **Checklist** tab; engine in `app/rules/checklist.py`, storage in `app/rules/store.py`,
  API in `app/routers/checklist.py`). Every built-in Annexure-H / BRD check is a rule
  whose thresholds are editable parameters, e.g. H2.9 gate distance min/max (settles
  BR-008 550–850 m vs ≥600 m as configuration) and the FR-004 direction→parity map.
- Per rule: enable/disable, severity FAIL or WARN (WARN is reported, never blocks),
  order. Built-ins can be reset to defaults but not deleted.
- Admins can add rules without code: tag↔element distance, tag spacing,
  required field, and manual checklist items.
- **Manual checklist items** (the former fixed "manual clauses" list) are confirmed per
  station by a checker/approver/admin while it is Submitted/Checked (PASS / FAIL / NA,
  note required for FAIL/NA). Responses belong to the current review cycle; rework,
  revise or reopen starts a fresh cycle, keeping old responses. "Mark checked" is refused
  while a *blocking* item is unconfirmed or any FAIL-severity item is confirmed as FAIL.
- Every configuration change needs a reason and is written to an append-only change
  log (before/after). The configuration version is shown on verification results and
  in the Verification and Compliance reports; disabled automated rules are listed too.
- With no edits, results are identical to the previous hard-coded engine.

**Phase 6 — done (BRD Section 7 roles):**
- One permission matrix, `app/auth/permissions.py`, now decides who may do what (routers
  call `require(user, "capability")`; the UI reads the same list from `/auth/me` →
  `permissions`). Roles: Designer, Checker, Approver, **Project Manager**,
  **Configuration Manager**, Administrator.
- **Tightened:** before Phase 6 *any* logged-in role could create stations and edit
  registers in Draft. Now only designers (and admins) can.
- **Project Manager** — monitor & assign, no edit rights: portfolio **dashboard**
  (`GET /dashboard`: status, assignee, days in status, failing checks, open
  observations, missing inputs, Railway reference; shown when no station is open);
  **assign the designer** (`PUT /stations/{id}/assign-designer`; while assigned, only
  that designer or an admin can edit registers/inputs, self-check or submit);
  **reassign the checker** of a submitted layout (`POST …/reassign-checker`, recorded
  as a workflow event, the new checker is emailed, the old one loses access).
- **Configuration Manager** — versions & baselines, no layout editing: edit the
  KAVACH/SIP/Guideline version numbers and SIP drawing number (draft only, reason
  required, audited — previously these could only be set at creation);
  **baselines** of approved layouts (`POST …/baselines`) and **compare** any baseline
  with the current layout (`GET …/baselines/{id}/diff`); edit the checklist; reopen an
  approved / Railway-submitted layout for a new revision.
- Assignments, version changes and baselines appear in the Audit Trail, Revision
  History and Approval Status reports. UI: dashboard, Assignment panel (Workflow tab),
  **Configuration** tab.

**Not yet built:** FR-001 does not *parse* the RFID Allocation Chart yet (BR-001
still enforces range/uniqueness, not "matches the chart"); no submit gate on missing
inputs (reported as gaps only); Alembic migrations (schema upgrades still go through
`ensure_schema_up_to_date`: add-column on SQLite, plus the `*_km` -> `*_m` column renames).

## Honest limitations (read before demoing this to anyone)



- **DXF import is uncalibrated.** It's correct `ezdxf` usage (handles both bare
  TEXT/MTEXT and INSERT-block-with-ATTRIB patterns) but the layer-name heuristics in
  `TAG_LAYER_HINTS`/`ELEMENT_LAYER_HINTS` are placeholders. Get 2–3 real Quadrant
  `.dxf` exports and tune these before trusting it beyond a reviewable draft.
- **Rules engine covers a subset of Annexure-H clauses that are genuinely
  formula-expressible.** `MANUAL_CLAUSES` in `rules/engine.py` explicitly lists what's
  deliberately NOT automated and why (e.g. H2.19's "TIN layout permits all ToC
  movements" is what the ToC cross-validator addresses instead of a static rule).
  Don't let a clean AutoChecks screen substitute for reading that list.
- **No multi-tenancy across Railway zones/organizations yet** — every station is
  visible to every authenticated user regardless of role. Fine for a single-team
  pilot, not for a multi-customer commercial deployment.
- **JWT has no revocation.** Logging a user out client-side doesn't invalidate their
  existing token before it expires — acceptable for a pilot, not for production
  (see `auth/security.py` docstring for what a hardening pass should add).
- **Frontend has no canvas/schematic editor.** It's functional CRUD tables + a
  verification results view + login/workflow/admin screens — Phase 5 (the
  chainage-based drawing surface matching the house drawing style) is still ahead
  and is, per the proposal, the single largest remaining cost item.
- **The G-tag distance rule (H2.9) was corrected during this build** from the
  550–850m range used in the earlier Excel tool (sourced from a secondary deck) to
  the ≥600m minimum actually stated in the Annexure-H text. If the 550–850m figure
  came from a Railway-specific circular rather than an error, flag it — the code
  currently follows the primary RDSO document.
- **`.xlsx`/`.xls`/`.docx` ToC parsing has not been tested against a real
  Railway/vendor-exported file in either format** — only synthetic files built for
  this test suite. If a real export has a different column layout than the CSV,
  parsing will silently produce wrong or empty routes rather than an error, since
  the column-index mapping (`COLUMNS` in `parser.py`) doesn't validate itself
  against a header row. Get a real sample of each format before trusting this
  beyond CSV.
- **No rate limiting on `/auth/login` or `/auth/forgot-password`.** Both are
  guessable-credential-attempt surfaces with no lockout/backoff yet — acceptable
  for a pilot behind a private network, not for a public-facing deployment.
