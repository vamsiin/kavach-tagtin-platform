"""Format-neutral drawing primitives, in millimetres on the sheet, origin bottom-left
(the PDF and DXF convention; the SVG renderer flips y). Every primitive carries a
layer name, which becomes a DXF layer so the drawing stays editable in AutoCAD."""
from __future__ import annotations

from dataclasses import dataclass, field

# Named TIN colours as written on layouts -> RGB. Unknown names fall back to grey and
# are listed on the sheet, so a typo never silently becomes a wrong colour.
COLOURS = {
    "black": (0, 0, 0), "white": (255, 255, 255), "red": (220, 30, 30), "green": (0, 150, 60),
    "light green": (140, 220, 140), "dark green": (0, 100, 40), "blue": (30, 80, 220),
    "light blue": (120, 190, 240), "sky blue": (110, 190, 245), "dark blue": (10, 40, 140), "yellow": (240, 200, 0),
    "orange": (245, 140, 20), "pink": (240, 120, 180), "light pink": (250, 185, 210),
    "magenta": (210, 0, 170), "violet": (140, 70, 200), "purple": (120, 40, 150),
    "brown": (140, 80, 30), "grey": (140, 140, 140), "gray": (140, 140, 140),
    "cyan": (0, 190, 210), "maroon": (120, 20, 30), "olive": (120, 120, 20),
}
INK = (0, 0, 0)
FAINT = (120, 120, 120)


def colour(name: str | None) -> tuple[int, int, int] | None:
    return COLOURS.get((name or "").strip().lower())


@dataclass
class Line:
    x1: float
    y1: float
    x2: float
    y2: float
    layer: str = "0"
    rgb: tuple = INK
    width: float = 0.25
    dash: bool = False


@dataclass
class Rect:
    x: float
    y: float
    w: float
    h: float
    layer: str = "0"
    stroke: tuple | None = INK
    fill: tuple | None = None
    width: float = 0.25


@dataclass
class Poly:
    points: list
    layer: str = "0"
    stroke: tuple | None = INK
    fill: tuple | None = None
    width: float = 0.25
    closed: bool = True


@dataclass
class Text:
    x: float
    y: float
    text: str
    size: float = 2.5                 # cap height, mm
    layer: str = "TEXT"
    rgb: tuple = INK
    angle: float = 0                  # degrees, counter-clockwise
    anchor: str = "start"             # start | middle | end
    bold: bool = False
    halo: bool = False                # white outline so lines passing behind don't cut the text


# Average Helvetica glyph width as a fraction of the cap height (font size = cap * 1.38);
# conservative, so estimated label lengths never come out shorter than drawn.
CHAR_W = 0.80


def text_len(text: str, size: float, bold: bool = False) -> float:
    return len(text) * size * (CHAR_W + (0.06 if bold else 0))


@dataclass
class Scene:
    width: float
    height: float
    title: str = ""
    items: list = field(default_factory=list)

    def add(self, *items):
        self.items.extend(items)
        return self
