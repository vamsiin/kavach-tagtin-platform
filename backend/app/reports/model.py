"""
Format-neutral report model (BRD FR-007 / Section 11).

Every report is built ONCE as a `Report` made of simple blocks; `render_pdf` and
`render_docx` turn the same object into a PDF or a Word file. This keeps the eight
report types from each needing two hand-written layouts that drift apart, and makes
report CONTENT testable without parsing PDFs.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Union

Tone = Literal["ok", "fail", "warn", "info"]


@dataclass
class Heading:
    text: str
    level: int = 1  # 1 = section, 2 = sub-section


@dataclass
class Para:
    text: str
    style: Literal["normal", "muted", "small"] = "normal"


@dataclass
class Banner:
    text: str
    tone: Tone = "info"


@dataclass
class KeyValues:
    rows: list[tuple[str, str]]


@dataclass
class Table:
    columns: list[str]
    rows: list[list[str]]
    # Relative column widths (any positive numbers; normalised by the renderer).
    widths: list[float] | None = None
    # Index of a column holding PASS/FAIL/WARN/NA-like values to colour, if any.
    status_col: int | None = None
    empty_text: str = "None."


@dataclass
class Bullets:
    items: list[str]


@dataclass
class SignOff:
    """Signature block: (role, name, date) rows with blank signature cells."""
    rows: list[tuple[str, str, str]]


@dataclass
class PageBreak:
    pass


Block = Union[Heading, Para, Banner, KeyValues, Table, Bullets, SignOff, PageBreak]


@dataclass
class Report:
    code: str                 # e.g. "VERIFICATION"
    title: str                # e.g. "Verification Report"
    station_name: str
    station_code: str
    layout_version: str
    station_status: str
    generated_by: str
    generated_at: str         # ISO-8601 UTC
    report_id: str            # e.g. "KVR-103-VER-20260925-0412"
    blocks: list[Block] = field(default_factory=list)

    def add(self, *blocks: Block) -> "Report":
        self.blocks.extend(blocks)
        return self

    def plain_text(self) -> str:
        """Flattened text -- used by tests and for a content hash."""
        out: list[str] = [self.title, self.station_name, self.layout_version]
        for b in self.blocks:
            if isinstance(b, (Heading, Para, Banner)):
                out.append(b.text)
            elif isinstance(b, KeyValues):
                out.extend(f"{k}: {v}" for k, v in b.rows)
            elif isinstance(b, Table):
                out.append(" | ".join(b.columns))
                out.extend(" | ".join(r) for r in b.rows)
            elif isinstance(b, Bullets):
                out.extend(b.items)
            elif isinstance(b, SignOff):
                out.extend(" | ".join(r) for r in b.rows)
        return "\n".join(out)


STATUS_TONES = {
    "PASS": "ok", "CLOSED": "ok", "APPROVED": "ok", "YES": "ok",
    "FAIL": "fail", "OPEN": "fail", "REOPENED": "fail", "MISSING": "fail", "NO": "fail",
    "WARN": "warn", "RESOLVED": "warn", "SUPERSEDED": "warn", "MANUAL": "warn", "PENDING": "warn", "DEVIATION": "warn",
    "NA": "info", "WITHDRAWN": "info",
}


def tone_for(value: str) -> Tone | None:
    return STATUS_TONES.get((value or "").strip().upper().split(" ")[0])  # type: ignore[return-value]
