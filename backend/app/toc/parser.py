"""
Parser for Table of Control (ToC) exports, as produced for KAVACH interlocking
verification (see sample_data/ALER_ToC.csv). Supports CSV, Excel (.xlsx/.xls), and
Word (.docx) containers -- all four funnel into the same _rows_to_routes() core, so
adding a format means adding a "get me rows of strings" loader, not re-implementing
route parsing.

Each route row encodes the RFID tag chain the interlocking expects a train to read
for that route, as a string like:
    (0#R-775#0)#(819#R-777#0)#(200#R-779#0)
where each parenthesised group is (delta_distance_from_previous_tag # tag_id # flag),
and cumulative distance must equal the route's stated
"DistanceBetweenEntry&ExitSignal(Meter)" column.

This is the authoritative source for tag order and inter-tag distance per route --
independent of whatever the RFID Tag/TIN layout drawing happens to show. Cross-checking
the drawn layout's tag chain against this file is the platform's core differentiator
over static distance-rule checking alone.

FORMAT SUPPORT -- please read before trusting a non-CSV upload:
  .csv   -- fully proven, tested against the real ALER_ToC.csv export.
  .xlsx  -- real, tested (openpyxl), but only ever exercised against a
            synthetically-constructed workbook here, not a genuine Railway/vendor
            .xlsx export -- the COLUMNS index mapping is assumed identical to the
            CSV layout, since no real sample existed to verify a different layout
            against.
  .xls   -- same caveat as .xlsx, via xlrd (which only supports the legacy binary
            format, not .xlsx -- that split is intentional, not an oversight).
  .docx  -- real, tested (python-docx), reads every table in the document and
            concatenates their rows. Same COLUMNS-mapping caveat as above, PLUS an
            additional one: if a real ToC-in-Word document splits the table
            differently (e.g. one route per table, or a transposed layout with
            routes as columns instead of rows), this will not produce useful
            output -- it assumes one wide table (or several with identical column
            order) shaped like the CSV.
  .doc   -- NOT supported. Legacy binary Word format has no reliable pure-Python
            parser without a system tool (LibreOffice, antiword) installed on the
            server, which this platform does not assume. Raises
            UnsupportedFormatError with a message asking for a .docx/.xlsx/.csv
            conversion, rather than silently failing or producing wrong data --
            wrong data from a compliance-cross-validation tool is worse than a
            clear refusal.

Row identification across all formats uses a content-based rule (the S.No column
must be a plain digit string) rather than a fixed "skip N header rows" position,
specifically because non-CSV containers (especially Word tables) don't reliably put
headers at the same row count as the CSV export does.
"""
from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field


TAG_CHAIN_RE = re.compile(r"\(([-\d]+)#([^#()]+)#([-\d]+)\)")

# Column indices as observed in the ALER_ToC.csv export. If a different Railway/vendor
# exports a different column order, adjust COLUMNS below -- the rest of the parser is
# index-based off this mapping, not fragile string matching per row. This mapping is
# assumed to hold for .xlsx/.xls/.docx exports too -- see module docstring.
COLUMNS = {
    "s_no": 0,
    "entry_signal": 1,
    "exit_signal": 2,
    "section_type": 3,
    "line": 4,
    "tsrms_route_id": 5,
    "signal_type": 6,
    "entry_aspect": 7,
    "exit_aspect": 8,
    "points_normal": 9,
    "points_reverse": 10,
    "track_circuit_up": 11,
    "tins_required_free": 12,
    "tins_required_free_overlap": 13,
    "entry_signal_foot_tag": 14,
    "rfid_chain_raw": 15,
    "distance_entry_exit_m": 16,
    "movement_authority_sections": 17,
    "authorized_speed": 18,
    "adjustment_info": 19,
    "adjacent_line_info": 20,
}


class UnsupportedFormatError(Exception):
    """Raised for file types this parser deliberately does not attempt to handle
    (currently: legacy .doc) -- see module docstring for why."""


@dataclass
class TagChainEntry:
    tag_id: str
    delta_m: int          # distance from the previous tag in the chain
    cumulative_m: int      # distance from the entry signal foot tag
    flag: int = 0


@dataclass
class Route:
    s_no: str
    entry_signal: str
    exit_signal: str
    section_type: str
    line: str
    signal_type: str
    entry_signal_foot_tag: str
    tag_chain: list[TagChainEntry] = field(default_factory=list)
    stated_distance_m: int | None = None
    movement_authority_sections: int | None = None
    tins_required_free: str = ""
    tins_required_free_overlap: str = ""
    adjustment_info: str = ""
    adjacent_line_info: str = ""

    @property
    def computed_distance_m(self) -> int:
        return self.tag_chain[-1].cumulative_m if self.tag_chain else 0

    @property
    def tag_ids_in_order(self) -> list[str]:
        return [t.tag_id for t in self.tag_chain]


def _clean(v) -> str:
    v = "" if v is None else str(v)
    v = v.strip()
    return "" if v == "-" else v


def _to_int(v) -> int | None:
    v = _clean(v)
    if v == "":
        return None
    try:
        return int(float(v))
    except ValueError:
        return None


def _cell_to_str(v) -> str:
    """Normalizes a cell value from openpyxl/xlrd (which may hand back int, float,
    datetime, or None depending on how the source file typed the cell) into a plain
    string matching what csv.reader would have given us -- in particular avoiding
    "1.0" for what should read as "1" when a spreadsheet stored a route number as a
    numeric cell rather than text."""
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v)


def parse_tag_chain(raw: str) -> list[TagChainEntry]:
    """Parse '(0#R-775#0)#(819#R-777#0)#(200#R-779#0)' into ordered TagChainEntry list
    with running cumulative distance from the entry signal foot tag."""
    raw = _clean(raw)
    if not raw:
        return []
    entries: list[TagChainEntry] = []
    cumulative = 0
    for m in TAG_CHAIN_RE.finditer(raw):
        delta_str, tag_id, flag_str = m.groups()
        delta = int(delta_str)
        cumulative += delta
        entries.append(TagChainEntry(tag_id=tag_id.strip(), delta_m=delta,
                                      cumulative_m=cumulative, flag=int(flag_str)))
    return entries


def _rows_to_routes(rows: list[list]) -> list[Route]:
    """Format-agnostic core: given rows of cell values (however they were extracted
    -- csv.reader, openpyxl, xlrd, or docx table cells), builds Route objects. A row
    is treated as route data if its S.No column is a plain digit string; anything
    else (header rows, sub-header rows, blank continuation rows for alternate
    signal-aspect combinations) is skipped. This is content-based rather than
    "skip the first N rows" specifically so it works across containers that don't
    all put headers at the same row count."""
    routes: list[Route] = []
    max_col = max(COLUMNS.values())
    for row in rows:
        if len(row) <= COLUMNS["rfid_chain_raw"]:
            continue
        # Pad short rows rather than indexing past the end -- several real-world
        # sources trim trailing empty cells (xlwt-written .xls files do this; a
        # hand-edited CSV/Word table might too), and a row that has real data
        # through the RFID chain column but happens to have nothing in the last
        # few columns is still a legitimate route, not something to crash on.
        if len(row) <= max_col:
            row = list(row) + [""] * (max_col + 1 - len(row))
        s_no = _clean(row[COLUMNS["s_no"]])
        if not s_no or not s_no.isdigit():
            continue

        chain_raw = row[COLUMNS["rfid_chain_raw"]]
        chain = parse_tag_chain(chain_raw)

        route = Route(
            s_no=s_no,
            entry_signal=_clean(row[COLUMNS["entry_signal"]]),
            exit_signal=_clean(row[COLUMNS["exit_signal"]]),
            section_type=_clean(row[COLUMNS["section_type"]]),
            line=_clean(row[COLUMNS["line"]]),
            signal_type=_clean(row[COLUMNS["signal_type"]]),
            entry_signal_foot_tag=_clean(row[COLUMNS["entry_signal_foot_tag"]]),
            tag_chain=chain,
            stated_distance_m=_to_int(row[COLUMNS["distance_entry_exit_m"]]),
            movement_authority_sections=_to_int(row[COLUMNS["movement_authority_sections"]]),
            tins_required_free=_clean(row[COLUMNS["tins_required_free"]]),
            tins_required_free_overlap=_clean(row[COLUMNS["tins_required_free_overlap"]]),
            adjustment_info=_clean(row[COLUMNS["adjustment_info"]]),
            adjacent_line_info=_clean(row[COLUMNS["adjacent_line_info"]]),
        )
        routes.append(route)

    return routes


def parse_toc_csv(path: str) -> list[Route]:
    """Parse a ToC export CSV into a list of Route objects, one per route (S.No filled)."""
    with open(path, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.reader(f))
    return _rows_to_routes(rows)


def parse_toc_xlsx(path: str) -> list[Route]:
    """Parse a ToC export from an Excel .xlsx workbook -- reads the first (active)
    worksheet. See module docstring for the "same column layout as CSV" assumption."""
    import openpyxl

    wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    ws = wb.worksheets[0]
    rows = [[_cell_to_str(c) for c in row] for row in ws.iter_rows(values_only=True)]
    return _rows_to_routes(rows)


def parse_toc_xls(path: str) -> list[Route]:
    """Parse a ToC export from a legacy Excel .xls workbook (xlrd only supports this
    older binary format, not .xlsx -- see parse_toc_xlsx for that)."""
    import xlrd

    wb = xlrd.open_workbook(path)
    sheet = wb.sheet_by_index(0)
    rows = [[_cell_to_str(sheet.cell_value(r, c)) for c in range(sheet.ncols)]
            for r in range(sheet.nrows)]
    return _rows_to_routes(rows)


def parse_toc_docx(path: str) -> list[Route]:
    """Parse a ToC export from a Word .docx document -- reads every table in the
    document and concatenates their rows before extracting routes. See module
    docstring for the layout assumptions and their limits."""
    import docx

    doc = docx.Document(path)
    rows: list[list[str]] = []
    for table in doc.tables:
        for row in table.rows:
            rows.append([cell.text for cell in row.cells])
    return _rows_to_routes(rows)


_EXTENSION_PARSERS = {
    ".csv": parse_toc_csv,
    ".xlsx": parse_toc_xlsx,
    ".xls": parse_toc_xls,
    ".docx": parse_toc_docx,
}


def parse_toc_file(path: str, filename: str) -> list[Route]:
    """Dispatches to the right parser based on the uploaded file's extension.
    Raises UnsupportedFormatError for .doc (see module docstring) and any other
    unrecognized extension, with an actionable message rather than guessing."""
    ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

    if ext == ".doc":
        raise UnsupportedFormatError(
            "Legacy .doc (Word 97-2003) files cannot be reliably parsed without a "
            "system conversion tool this platform doesn't assume is installed. "
            "Please save/export as .docx, .xlsx, or .csv and re-upload."
        )

    parser = _EXTENSION_PARSERS.get(ext)
    if parser is None:
        raise UnsupportedFormatError(
            f"Unsupported file type '{ext or '(no extension)'}'. Supported: "
            f"{', '.join(sorted(_EXTENSION_PARSERS.keys()))}."
        )
    return parser(path)


def distance_mismatches(routes: list[Route]) -> list[dict]:
    """Sanity-check the ToC file itself: does the parsed tag chain's cumulative
    distance match the file's own stated entry-to-exit distance? A mismatch usually
    means the chain regex missed a segment or the export has a data-entry error --
    worth flagging before trusting the file for cross-validation."""
    issues = []
    for r in routes:
        if r.stated_distance_m is None or not r.tag_chain:
            continue
        if r.computed_distance_m != r.stated_distance_m:
            issues.append({
                "route": r.s_no,
                "entry_signal": r.entry_signal,
                "exit_signal": r.exit_signal,
                "stated_m": r.stated_distance_m,
                "computed_from_chain_m": r.computed_distance_m,
            })
    return issues
