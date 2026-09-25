"""
Configurable checklist engine (BRD FR-006) -- pure Python, no DB, no HTTP.

A checklist is an ordered list of `RuleConfig`s. Each rule is one of:

  builtin               one of the coded Annexure-H / BRD checks in engine.py, with
                        its thresholds exposed as editable parameters (e.g. H2.9 gate
                        distance min/max, FR-004 direction parity map). Topology-aware
                        logic stays in code; only its numbers and switches are config.
  tag_element_distance  declarative: tags of given types must be within [min, max] m
                        of the element they are linked to (optionally only for some
                        element types).
  tag_spacing           declarative: consecutive tags of given types (per direction)
                        must be within [min, max] m of each other.
  required_field        declarative: a field on tags / elements / TINs / the station
                        must not be blank (optionally only for some tag types).
  manual                a checklist item a reviewer confirms by hand per station
                        (PASS / FAIL / NA). Optionally blocking for "Mark checked".

Every rule has a severity (FAIL, or WARN = reported but never blocks) and can be
disabled. With no configuration, `default_rules()` reproduces the pre-Phase-5
hard-coded behaviour exactly.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field

from ..domain import ELEMENT_TYPES, TAG_TYPES

KINDS = ["builtin", "tag_element_distance", "tag_spacing", "required_field", "manual"]
SEVERITIES = ["FAIL", "WARN"]
MANUAL_RESPONSES = ["PASS", "FAIL", "NA"]


@dataclass
class RuleConfig:
    key: str
    kind: str
    clause: str
    title: str
    description: str = ""
    params: dict = field(default_factory=dict)
    severity: str = "FAIL"
    enabled: bool = True
    sort_order: int = 0
    blocking: bool = False    # manual items only: must be confirmed before "Mark checked"
    builtin: str | None = None  # builtin registry id for kind == "builtin"
    id: int | None = None


# ---------------------------------------------------------------------------
# Parameter schemas (drive validation AND the admin UI form)
# ---------------------------------------------------------------------------
def P(name, type_, label, required=True, min=None, options=None, nullable=False):
    return {"name": name, "type": type_, "label": label, "required": required,
            "min": min, "options": options, "nullable": nullable}


TAG_TYPE_OPTS = list(TAG_TYPES)

BUILTINS: dict[str, dict] = {}


def _b(bid, clause, title, description, defaults, schema, fn, severity="FAIL"):
    BUILTINS[bid] = {"clause": clause, "title": title, "description": description,
                     "defaults": defaults, "schema": schema, "fn": fn, "severity": severity}


def _register_builtins():
    from . import engine as E
    _b("data_units", "DATA-UNITS", "Chainage entered in metres",
       "Warns when a station's locations look like km instead of metres.",
       {"span_threshold_m": 50}, [P("span_threshold_m", "number", "Flag if all locations span less than (m)", min=0)],
       lambda st, el, tg, tn, p: E.check_data_units(el, tg, tn, p))
    _b("h2_1", "H2.1", "Version control X.Y.Z complete", "KAVACH, SIP and guideline versions all set.",
       {}, [], lambda st, el, tg, tn, p: E.check_h2_1_version_control(st))
    _b("h2_2", "H2.2", "Station identifiers present", "Stationary KAVACH ID and SIP drawing number present.",
       {}, [], lambda st, el, tg, tn, p: E.check_h2_2_identifiers(st))
    _b("h2_5", "H2.5", "Normal tag spacing", "Maximum gap between consecutive Normal tags, per direction.",
       {"max_gap_m": 1000, "tag_types": ["N"]},
       [P("max_gap_m", "number", "Maximum gap (m)", min=0),
        P("tag_types", "tag_types", "Tag types", options=TAG_TYPE_OPTS)],
       lambda st, el, tg, tn, p: E.check_h2_5_normal_tag_spacing(tg, p))
    _b("h2_6", "H2.6", "Signal Foot Tag present", "Signals, stop boards, BSLB etc. must have a linked S tag.",
       {}, [], lambda st, el, tg, tn, p: E.check_h2_6_signal_foot_tags(el, tg))
    _b("h2_7", "H2.7", "Approach tag distance", "Normal (approach) tag distance before the Signal Foot Tag.",
       {"min_m": 150, "max_m": 250, "starter_exception": True, "whole_metres": True},
       [P("min_m", "number", "Minimum (m)", min=0), P("max_m", "number", "Maximum (m)", min=0),
        P("starter_exception", "bool", "Allow < minimum for Advance/Intermediate Starter"),
        P("whole_metres", "bool", "Distance must be an exact multiple of 1 m", required=False)],
       lambda st, el, tg, tn, p: E.check_h2_7_approach_tag_distance(tg, el, p))
    _b("h2_9", "H2.9", "Gate tag distance from LC gate",
       "G tag distance from its LC gate. Annexure-H text: minimum 600 m; BRD BR-008: 550-850 m.",
       {"min_m": 600, "max_m": None, "wl_board_alternative": True, "wl_reach_m": 1000},
       [P("min_m", "number", "Minimum (m)", min=0),
        P("max_m", "number", "Maximum (m) - blank for no upper limit", required=False, min=0, nullable=True),
        P("wl_board_alternative", "bool", "Accept a W/L board on the approach instead", required=False),
        P("wl_reach_m", "number", "W/L board within (m) of the gate", required=False, min=0)],
       lambda st, el, tg, tn, p: E.check_h2_9_gate_tag_distance(tg, el, p))
    _b("h2_11", "H2.11", "Exit tag sets", "Minimum number of exit tag sets and their spacing.",
       {"min_sets": 2, "min_set_gap_m": 10},
       [P("min_sets", "int", "Minimum sets", min=1), P("min_set_gap_m", "number", "Minimum gap between sets (m)", min=0)],
       lambda st, el, tg, tn, p: E.check_h2_11_exit_tags(tg, p))
    _b("h2_12", "H2.12", "Duplicate tag pair spacing",
       "Main and duplicate tag spacing. T and A tag pairs must be co-located.",
       {"dup_min_m": 3, "dup_max_m": 5},
       [P("dup_min_m", "number", "Duplicate pair min (m)", min=0), P("dup_max_m", "number", "Duplicate pair max (m)", min=0)],
       lambda st, el, tg, tn, p: E.check_h2_12_duplicate_spacing(tg, p))
    _b("h2_13", "H2.13", "Tag-set to tag-set spacing", "Minimum distance from one tag set to the next.",
       {"tagset_min_m": 10}, [P("tagset_min_m", "number", "Tag-set to tag-set min (m)", min=0)],
       lambda st, el, tg, tn, p: E.check_h2_13_tagset_spacing(tg, p))
    _b("h2_15", "H2.15", "Legend shape matches co-location", "Rectangle if co-located, Triangle if not.",
       {}, [], lambda st, el, tg, tn, p: E.check_h2_15_legend_shape(tg))
    _b("h2_18", "H2.18", "Non-KAVACH territory colour", "Non-KAVACH TINs must be shown in this colour.",
       {"colour": "White"}, [P("colour", "str", "Colour")],
       lambda st, el, tg, tn, p: E.check_h2_18_non_kavach_white(tn, p))
    _b("h2_23", "H2.23", "Numbering ranges", "Tag and TIN numbers within the allowed ranges.",
       {"tag_min": 1, "tag_max": 1023, "tin_min": 1, "tin_max": 255},
       [P("tag_min", "int", "Tag number min", min=0), P("tag_max", "int", "Tag number max", min=0),
        P("tin_min", "int", "TIN min", min=0), P("tin_max", "int", "TIN max", min=0)],
       lambda st, el, tg, tn, p: E.check_h2_23_numbering_ranges(tg, tn, p))
    _b("h2_21", "H2.21", "Tag notation valid", "Tag type is one of the defined notations.",
       {}, [], lambda st, el, tg, tn, p: E.check_h2_21_tag_notation(tg))
    _b("h2_16", "H2.16", "Station border location recorded",
       "Each adjacent station is recorded with the absolute location of the border line.",
       {}, [], lambda st, el, tg, tn, p: E.check_h2_16_border_locations(st))
    _b("h2_28", "H2.28", "Station centre line location recorded",
       "The station centre line absolute location is recorded (and lies on a line of the station).",
       {}, [], lambda st, el, tg, tn, p: E.check_h2_28_centre_line(st))
    _b("topology", "DATA-TOPOLOGY", "Placed on a line of the station",
       "Elements, tags and TINs are placed on a line and within its extent; points join two lines.",
       {"tolerance_m": 0}, [P("tolerance_m", "number", "Tolerance beyond the line ends (m)", min=0)],
       lambda st, el, tg, tn, p: E.check_topology(st, el, tg, tn, p), severity="WARN")
    from . import layout_rules as L
    _b("h2_8", "H2.8", "TIN boundary marked by a tag",
       "At each boundary between two TINs on a line, a demarcation tag (T / N / S / G) close to it.",
       {"tag_types": ["T", "N", "S", "G"], "max_distance_m": 50},
       [P("tag_types", "tag_types", "Demarcation tag types", options=TAG_TYPE_OPTS),
        P("max_distance_m", "number", "Tag within (m) of the boundary", min=0)],
       lambda st, el, tg, tn, p: L.check_h2_8_tin_demarcation(st, tg, tn, p), severity="WARN")
    _b("h2_17", "H2.17", "TIN colours",
       "Each TIN one colour, recorded; neighbouring TINs (consecutive on a line, or joined by points) differ.",
       {"touch_gap_m": 5}, [P("touch_gap_m", "number", "TINs this close (m) count as neighbours", min=0)],
       lambda st, el, tg, tn, p: L.check_h2_17_tin_colours(st, el, tn, p))
    _b("h2_20", "H2.20", "Exit tags at sidings / non-KAVACH lines",
       "Every siding and non-KAVACH line has an exit tag on it or near the points leading to it.",
       {"max_distance_m": 300}, [P("max_distance_m", "number", "Exit tag within (m) of the points", min=0)],
       lambda st, el, tg, tn, p: L.check_h2_20_exit_at_sidings(st, el, tg, p))
    _b("h2_22", "H2.22", "Block TIN extent",
       "Block TIN extends to the BSLB (double line) or the Advance Starter (single line).",
       {"tolerance_m": 20}, [P("tolerance_m", "number", "TIN end within (m) of the board / signal", min=0)],
       lambda st, el, tg, tn, p: L.check_h2_22_block_tin_extent(st, el, tn, p))
    _b("h2_26", "H2.26", "'Not drawn to scale' note",
       "A layout not drawn to scale carries the note.", {}, [],
       lambda st, el, tg, tn, p: L.check_h2_26_not_to_scale(st))
    _b("tan_dead_stop", "TAN-1", "Dead stop tag from facing points",
       "New-TAN rule: dead stop (D) tag distance from the facing points.",
       {"min_m": 25, "max_m": 35},
       [P("min_m", "number", "Minimum (m)", min=0), P("max_m", "number", "Maximum (m)", min=0)],
       lambda st, el, tg, tn, p: L.check_tan_dead_stop(tg, el, p))
    _b("tan_l_tag", "TAN-2", "Adjacent line tag after the last stop signal",
       "New-TAN rule: adjacent line (L) tag about 100 m after the last stop signal it is linked to.",
       {"min_m": 90, "max_m": 110},
       [P("min_m", "number", "Minimum (m)", min=0), P("max_m", "number", "Maximum (m)", min=0)],
       lambda st, el, tg, tn, p: L.check_tan_adjacent_line_tag(tg, el, p))
    _b("tan_after_a", "TAN-3", "Normal tags after an adjustment tag",
       "New-TAN rule: Normal tags within (0.5 x max section speed + 10) m of each adjustment (A) tag.",
       {"max_speed_kmph": 130, "normal_tags": 2},
       [P("max_speed_kmph", "number", "Max section speed (km/h)", min=1),
        P("normal_tags", "int", "Normal tags required", min=1)],
       lambda st, el, tg, tn, p: L.check_tan_after_adjustment(tg, p))
    _b("fr004_unique", "FR-004", "Tag ref / number unique", "Tag references and numbers unique within the station.",
       {}, [], lambda st, el, tg, tn, p: E.check_brd_fr004_tag_uniqueness(tg))
    _b("fr004_parity", "FR-004", "Tag number parity by direction",
       "Odd/even tag numbering per direction (BRD FR-004): even for DN (Nominal), odd for UP (Reverse). "
       "Confirmed by QFTL (Sep 2026) to follow the BRD over the older Aler drawing, which used odd on DN MAIN.",
       {"parity_map": dict(E.DIRECTION_PARITY_MAP)},
       [P("parity_map", "parity_map", "Direction -> parity", options=["odd", "even"])],
       lambda st, el, tg, tn, p: E.check_brd_fr004_direction_parity(tg, p))
    _b("br001", "BR-001", "Numbers within the allotment chart",
       "Tag and TIN numbers are in the station's allotment, or its adjacent sections', on the current chart.",
       {}, [], lambda st, el, tg, tn, p: E.check_br001_allotment(st, tg, tn))
    _b("br005", "BR-005", "Border tag location recorded", "Border tags have an absolute location.",
       {}, [], lambda st, el, tg, tn, p: E.check_brd_br005_border_tag_present(tg))


FIELD_WHITELIST = {
    "tag": ["tag_number", "direction", "tin_no", "linked_element_id", "legend_shape", "pair_group_id",
            "exit_set", "remarks", "source_document_id"],
    "element": ["direction", "remarks", "source_document_id"],
    "tin": ["color", "direction", "remarks", "source_document_id"],
    "station": ["sip_drawing_number", "kavach_version", "sip_version", "guideline_version"],
}

KIND_SCHEMAS = {
    "tag_element_distance": [
        P("tag_types", "tag_types", "Tag types", options=TAG_TYPE_OPTS),
        P("element_types", "element_types", "Only for element types (blank = all)", required=False,
          options=list(ELEMENT_TYPES)),
        P("min_m", "number", "Minimum (m)", required=False, min=0, nullable=True),
        P("max_m", "number", "Maximum (m)", required=False, min=0, nullable=True),
    ],
    "tag_spacing": [
        P("tag_types", "tag_types", "Tag types", options=TAG_TYPE_OPTS),
        P("min_gap_m", "number", "Minimum gap (m)", required=False, min=0, nullable=True),
        P("max_gap_m", "number", "Maximum gap (m)", required=False, min=0, nullable=True),
        P("per_direction", "bool", "Check each direction separately", required=False),
    ],
    "required_field": [
        P("entity", "choice", "Applies to", options=list(FIELD_WHITELIST)),
        P("field", "choice", "Field", options=sorted({f for fs in FIELD_WHITELIST.values() for f in fs})),
        P("tag_types", "tag_types", "Only tag types (tags only; blank = all)", required=False, options=TAG_TYPE_OPTS),
    ],
    "manual": [],
}


class RuleError(ValueError):
    pass


def schema_for(kind: str, builtin: str | None) -> list[dict]:
    _ensure()
    if kind == "builtin":
        if builtin not in BUILTINS:
            raise RuleError(f"Unknown built-in rule '{builtin}'")
        return BUILTINS[builtin]["schema"]
    if kind not in KIND_SCHEMAS:
        raise RuleError(f"kind must be one of {KINDS}")
    return KIND_SCHEMAS[kind]


def validate_params(kind: str, builtin: str | None, params: dict) -> dict:
    """Coerce + validate params against the schema; returns a clean dict. Unknown keys
    are rejected (a typo'd key silently doing nothing is exactly the failure mode a
    safety checklist can't afford)."""
    schema = {s["name"]: s for s in schema_for(kind, builtin)}
    params = dict(params or {})
    unknown = set(params) - set(schema)
    if unknown:
        raise RuleError(f"Unknown parameter(s): {', '.join(sorted(unknown))}")
    base = copy.deepcopy(BUILTINS[builtin]["defaults"]) if kind == "builtin" else {}
    out = {**base}
    for name, s in schema.items():
        if name not in params:
            if s["required"] and name not in out:
                raise RuleError(f"'{s['label']}' is required")
            continue
        v = params[name]
        if v in (None, "") and s["nullable"]:
            out[name] = None
            continue
        t = s["type"]
        try:
            if t == "number":
                v = float(v)
            elif t == "int":
                v = int(v)
            elif t == "bool":
                v = bool(v)
            elif t == "str":
                v = str(v).strip()
                if not v:
                    raise RuleError(f"'{s['label']}' cannot be blank")
            elif t in ("tag_types", "element_types"):
                v = [x for x in (v or []) if x]
                bad = [x for x in v if x not in s["options"]]
                if bad:
                    raise RuleError(f"'{s['label']}': unknown value(s) {bad}")
                if s["required"] and not v:
                    raise RuleError(f"'{s['label']}' needs at least one value")
            elif t == "choice":
                if v not in s["options"]:
                    raise RuleError(f"'{s['label']}' must be one of {s['options']}")
            elif t == "parity_map":
                if not isinstance(v, dict) or not v:
                    raise RuleError("Parity map must map direction names to 'odd' or 'even'")
                v = {str(k).strip(): str(x).strip().lower() for k, x in v.items() if str(k).strip()}
                if any(x not in ("odd", "even") for x in v.values()):
                    raise RuleError("Parity values must be 'odd' or 'even'")
        except (TypeError, ValueError) as e:
            if isinstance(e, RuleError):
                raise
            raise RuleError(f"'{s['label']}' must be a {t}")
        if s["min"] is not None and isinstance(v, (int, float)) and v < s["min"]:
            raise RuleError(f"'{s['label']}' must be >= {s['min']}")
        out[name] = v

    # cross-field checks
    lo_hi = [("min_m", "max_m"), ("min_gap_m", "max_gap_m"), ("dup_min_m", "dup_max_m"),
             ("tag_min", "tag_max"), ("tin_min", "tin_max")]
    for lo, hi in lo_hi:
        if out.get(lo) is not None and out.get(hi) is not None and out[lo] > out[hi]:
            raise RuleError(f"{lo} ({out[lo]:g}) cannot exceed {hi} ({out[hi]:g})")
    if kind in ("tag_element_distance", "tag_spacing"):
        keys = ("min_m", "max_m") if kind == "tag_element_distance" else ("min_gap_m", "max_gap_m")
        if all(out.get(k) is None for k in keys):
            raise RuleError("Give a minimum, a maximum, or both")
    if kind == "required_field" and out["field"] not in FIELD_WHITELIST[out["entity"]]:
        raise RuleError(f"'{out['field']}' is not a field of {out['entity']}; "
                        f"choose from {FIELD_WHITELIST[out['entity']]}")
    return out


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
_ORDER = ["data_units", "h2_1", "h2_2", "h2_5", "h2_6", "h2_7", "h2_9", "h2_11", "h2_12", "h2_13",
          "h2_15", "h2_16", "h2_18", "h2_21", "h2_23", "h2_28", "fr004_unique", "fr004_parity", "br001", "br005",
          "topology", "h2_8", "h2_17", "h2_20", "h2_22", "h2_26", "tan_dead_stop", "tan_l_tag", "tan_after_a"]


def _ensure():
    if not BUILTINS:
        _register_builtins()


def default_rules() -> list[RuleConfig]:
    _ensure()
    from .engine import MANUAL_CLAUSES
    rules = [RuleConfig(key=f"builtin.{bid}", kind="builtin", builtin=bid,
                        clause=BUILTINS[bid]["clause"], title=BUILTINS[bid]["title"],
                        description=BUILTINS[bid]["description"],
                        params=copy.deepcopy(BUILTINS[bid]["defaults"]),
                        severity=BUILTINS[bid]["severity"], sort_order=(i + 1) * 10) for i, bid in enumerate(_ORDER)]
    for j, (clause, text) in enumerate(MANUAL_CLAUSES.items()):
        slug = "".join(c if c.isalnum() else "_" for c in clause.lower()).strip("_")
        rules.append(RuleConfig(key=f"manual.{slug}", kind="manual", clause=clause,
                                title=text.split(" -- ")[0][:120], description=text,
                                sort_order=1000 + (j + 1) * 10, blocking=False))
    return rules


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------
def execute_rule(rule: RuleConfig, station, elements, tags, tins) -> list:
    from .engine import CheckResult
    _ensure()
    if rule.kind == "builtin" and rule.builtin not in BUILTINS:
        # a stored rule this version no longer knows: report it, never crash verification
        return [CheckResult(rule.clause, rule.title, "WARN",
                            f"Built-in rule '{rule.builtin}' is not recognised by this version; "
                            f"ask an administrator to review the checklist.")]
    if rule.kind == "builtin":
        results = BUILTINS[rule.builtin]["fn"](station, elements, tags, tins, rule.params)
    elif rule.kind == "tag_element_distance":
        results = _tag_element_distance(rule, elements, tags, CheckResult)
    elif rule.kind == "tag_spacing":
        results = _tag_spacing(rule, tags, CheckResult)
    elif rule.kind == "required_field":
        results = _required_field(rule, station, elements, tags, tins, CheckResult)
    else:
        results = []
    if rule.severity == "WARN":
        for r in results:
            if r.status == "FAIL":
                r.status = "WARN"
    return results


def _range_txt(lo, hi):
    if lo is not None and hi is not None:
        return f"{lo:g}-{hi:g}m"
    return f">= {lo:g}m" if lo is not None else f"<= {hi:g}m"


def _tag_element_distance(rule, elements, tags, CR):
    p = rule.params
    lo, hi = p.get("min_m"), p.get("max_m")
    els = {e.id: e for e in elements}
    out = []
    for t in tags:
        if t.tag_type not in p["tag_types"] or not t.linked_element_id:
            continue
        el = els.get(t.linked_element_id)
        if not el or (p.get("element_types") and el.element_type not in p["element_types"]):
            continue
        gap = abs(el.location_m - t.location_m)
        ok = (lo is None or gap >= lo) and (hi is None or gap <= hi)
        out.append(CR(rule.clause, rule.title, "PASS" if ok else "FAIL",
                      f"{t.tag_ref} is {gap:.0f}m from {el.element_ref} (required {_range_txt(lo, hi)})",
                      subject_ref=t.tag_ref))
    return out


def _tag_spacing(rule, tags, CR):
    p = rule.params
    lo, hi = p.get("min_gap_m"), p.get("max_gap_m")
    per_dir = p.get("per_direction", True)
    groups: dict[str, list] = {}
    for t in tags:
        if t.tag_type in p["tag_types"]:
            groups.setdefault((t.direction or "?") if per_dir else "*", []).append(t)
    out = []
    for g in groups.values():
        g.sort(key=lambda t: t.location_m)
        for a, b in zip(g, g[1:]):
            gap = abs(b.location_m - a.location_m)
            ok = (lo is None or gap >= lo) and (hi is None or gap <= hi)
            out.append(CR(rule.clause, rule.title, "PASS" if ok else "FAIL",
                          f"{a.tag_ref} -> {b.tag_ref}: {gap:.0f}m (required {_range_txt(lo, hi)})",
                          subject_ref=b.tag_ref))
    return out


def _required_field(rule, station, elements, tags, tins, CR):
    p = rule.params
    entity, fld = p["entity"], p["field"]
    rows = {"tag": [(t.tag_ref, t) for t in tags if not p.get("tag_types") or t.tag_type in p["tag_types"]],
            "element": [(e.element_ref, e) for e in elements],
            "tin": [(f"TIN {n.tin_no}", n) for n in tins],
            "station": [(station.name, station)]}[entity]
    out = []
    for ref, obj in rows:
        v = getattr(obj, fld, None)
        ok = v not in (None, "")
        out.append(CR(rule.clause, rule.title, "PASS" if ok else "FAIL",
                      f"{ref}: {fld} " + ("recorded" if ok else "is blank"), subject_ref=ref))
    return out
