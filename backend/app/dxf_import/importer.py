"""
AutoCAD DXF import for existing SIP / RFID layout drawings, using ezdxf.

Honest scope note: DXF layer/block naming conventions are not standardized across
designers, years, or CAD templates -- the ALER drawing you shared as a reference was
a rendered image/PDF, not a .dxf, so this module has NOT been calibrated against a
real Quadrant DXF export yet. It handles both bare TEXT/MTEXT entities and the more
common AutoCAD pattern of INSERT blocks with ATTRIB text (e.g. a repeated "tag" symbol
block with an attribute holding that instance's ID), but the TAG_LAYER_HINTS /
ELEMENT_LAYER_HINTS layer-name heuristics below are still placeholders that MUST be
tuned against 2-3 real sample DXF files before this is trusted for anything beyond a
reviewable draft import. It should never auto-commit an imported layout -- see
import_dxf()'s return shape: everything comes back as an ImportCandidate for a human
to confirm or correct, per Annexure-H H2.3's own requirement that site survey/actual
conditions be considered, not just the SIP as drawn.
"""
from __future__ import annotations

from dataclasses import dataclass, field

try:
    import ezdxf
except ImportError:  # pragma: no cover - exercised only when ezdxf isn't installed
    ezdxf = None

# Layer-name substrings that suggest a text entity is a tag label vs. an element
# label. Tune these against real Quadrant DXF exports -- this is a starting point,
# not a finished heuristic.
TAG_LAYER_HINTS = ["rfid", "tag", "r-tag"]
ELEMENT_LAYER_HINTS = ["signal", "sig", "gate", "lc", "turnout", "point", "marker", "fouling", "bslb"]


@dataclass
class ImportCandidate:
    text: str
    layer: str
    x: float
    y: float
    kind: str  # "tag" | "element" | "unclassified"


@dataclass
class ImportResult:
    candidates: list[ImportCandidate] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _classify_layer(layer_name: str) -> str:
    lname = layer_name.lower()
    if any(h in lname for h in TAG_LAYER_HINTS):
        return "tag"
    if any(h in lname for h in ELEMENT_LAYER_HINTS):
        return "element"
    return "unclassified"


def import_dxf(path: str) -> ImportResult:
    """Extract TEXT/MTEXT entities from a DXF as import candidates. Returns candidates
    for a human to review and confirm as Elements or Tags -- never auto-commits."""
    result = ImportResult()
    if ezdxf is None:
        result.warnings.append(
            "ezdxf is not installed in this environment. Run `pip install ezdxf` and "
            "retry -- this function cannot run without it."
        )
        return result

    try:
        doc = ezdxf.readfile(path)
    except Exception as e:  # ezdxf raises several distinct error types
        result.warnings.append(f"Could not open DXF: {e}")
        return result

    msp = doc.modelspace()

    # Pass 1: bare TEXT/MTEXT entities
    for entity in msp.query("TEXT MTEXT"):
        try:
            text = entity.dxf.text if entity.dxftype() == "TEXT" else entity.text
            layer = entity.dxf.layer
            x, y = entity.dxf.insert.x, entity.dxf.insert.y
        except Exception:
            continue
        text = (text or "").strip()
        if not text:
            continue
        result.candidates.append(ImportCandidate(
            text=text, layer=layer, x=x, y=y, kind=_classify_layer(layer),
        ))

    # Pass 2: INSERT blocks with ATTRIB entities -- the common AutoCAD pattern for
    # repeated symbols (a "tag" block placed many times, each with an attribute
    # holding that instance's ID, e.g. "R-775"). Bare TEXT alone often misses these
    # entirely, since the visible label lives inside the block reference, not as a
    # standalone entity in modelspace.
    for insert in msp.query("INSERT"):
        try:
            block_name = insert.dxf.name
            layer = insert.dxf.layer
            x, y = insert.dxf.insert.x, insert.dxf.insert.y
        except Exception:
            continue
        attribs = list(insert.attribs) if insert.attribs else []
        if not attribs:
            # A block with no attributes carries no identifying text -- still worth
            # surfacing as a candidate keyed by block name, in case the block name
            # itself encodes the tag/element type (e.g. block "TAG_N" vs "SIG_MAIN").
            kind = _classify_layer(layer) if _classify_layer(layer) != "unclassified" \
                else _classify_layer(block_name)
            result.candidates.append(ImportCandidate(
                text=f"[block:{block_name}]", layer=layer, x=x, y=y, kind=kind,
            ))
            continue
        for attrib in attribs:
            text = (attrib.dxf.text or "").strip()
            if not text:
                continue
            attrib_layer = getattr(attrib.dxf, "layer", layer)
            kind = _classify_layer(attrib_layer)
            if kind == "unclassified":
                kind = _classify_layer(block_name)
            result.candidates.append(ImportCandidate(
                text=text, layer=attrib_layer, x=x, y=y, kind=kind,
            ))

    if not result.candidates:
        result.warnings.append(
            "No TEXT/MTEXT entities or INSERT/ATTRIB blocks with text found in this "
            "DXF's modelspace. Labels may live on a layout/paperspace tab instead, or "
            "use a symbol convention this importer doesn't recognize yet."
        )
    unclassified = sum(1 for c in result.candidates if c.kind == "unclassified")
    if unclassified:
        result.warnings.append(
            f"{unclassified} text entities could not be classified as tag or element "
            f"by layer name -- review TAG_LAYER_HINTS/ELEMENT_LAYER_HINTS against this "
            f"drawing's actual layer list ({sorted({c.layer for c in result.candidates})})."
        )

    return result
