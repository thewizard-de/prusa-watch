"""Printer models: how the machine moves, so the vision prompt describes the right printer.

`printer_model: auto` detects the model from the PrusaLink hostname (default `prusa-core-one-l`,
`prusa-mk4`, ...) and, failing that, from the printer suffix PrusaSlicer puts in the G-code file name
(`..._PLA_COREONEL_25m.bgcode`).
"""
import re
from dataclasses import dataclass
from typing import Optional

BEDSLINGER = "bedslinger"
COREXY = "corexy"


@dataclass(frozen=True)
class PrinterModel:
    key: str
    name: str
    kinematics: str      # BEDSLINGER | COREXY
    enclosed: bool
    bed_x: int = 250     # print area in mm (X left-right, Y front-back)
    bed_y: int = 210


MODELS = {
    "core_one_l": PrinterModel("core_one_l", "Prusa CORE One L", COREXY, True, 300, 300),
    "core_one": PrinterModel("core_one", "Prusa CORE One", COREXY, True, 250, 220),
    "xl": PrinterModel("xl", "Prusa XL", COREXY, False, 360, 360),
    "mk4s": PrinterModel("mk4s", "Prusa MK4S", BEDSLINGER, False, 250, 210),
    "mk4": PrinterModel("mk4", "Prusa MK4", BEDSLINGER, False, 250, 210),
    "mk3.5s": PrinterModel("mk3.5s", "Prusa MK3.5S", BEDSLINGER, False, 250, 210),
    "mk3.5": PrinterModel("mk3.5", "Prusa MK3.5", BEDSLINGER, False, 250, 210),
    "mini": PrinterModel("mini", "Prusa MINI+", BEDSLINGER, False, 180, 180),
}
CHOICES = ("auto", *MODELS)
DEFAULT = "mk3.5s"          # what the prompt described before 0.10.0, used when auto-detection finds nothing

# Most specific first: "coreonel" must win over "coreone", "mk4s" over "mk4", "mk3.5s" over "mk3.5".
_PATTERNS = (
    ("core_one_l", r"core[-_ ]?one[-_ ]?l(?![a-z])"),
    ("core_one", r"core[-_ ]?one(?![a-z])"),
    ("xl", r"(?<![a-z])xl(?![a-z])"),
    ("mk4s", r"mk4s"),
    ("mk4", r"mk4(?![a-z0-9])"),
    ("mk3.5s", r"mk3[._-]?5s"),
    ("mk3.5", r"mk3[._-]?5(?![a-z0-9])"),
    ("mini", r"mini"),
)


def detect(*hints: Optional[str]) -> Optional[str]:
    """Model key from free-text hints (hostname, G-code file name), first hint that matches wins."""
    for hint in hints:
        text = (hint or "").lower()
        if not text:
            continue
        for key, pattern in _PATTERNS:
            if re.search(pattern, text):
                return key
    return None


def head_text(model: PrinterModel, x, y) -> str:
    """Context line on where the print head is, so the model knows which part of the sheet it covers."""
    if x is None or y is None:
        return ""
    outside = x < 0 or y < 0 or x > model.bed_x or y > model.bed_y
    where = []
    where.append("left" if x < model.bed_x / 3 else "right" if x > 2 * model.bed_x / 3 else "centre")
    where.append("front" if y < model.bed_y / 3 else "back" if y > 2 * model.bed_y / 3 else "middle")
    line = (f"Print head at X={x:.0f} mm, Y={y:.0f} mm of a {model.bed_x} x {model.bed_y} mm bed "
            f"(printer coordinates: X left to right, Y front to back seen from the front of the printer; "
            f"roughly {where[1]}-{where[0]}).")
    if outside:
        line += " The head is parked outside the print area and covers none of the parts."
    return line


def motion_text(model: PrinterModel) -> str:
    """The 'How this printer moves' part of the system prompt."""
    if model.kinematics == COREXY:
        return (
            f"How this printer moves:\n"
            f"- The {model.name} is a CoreXY printer{' with a closed chamber' if model.enclosed else ''}. "
            "The bed with the print sheet never moves sideways or front/back: it only moves vertically (Z) and "
            "lowers by one layer height per layer. Printed parts are stuck to the sheet, so from one frame to the "
            "next they stay in practically the same place in the IMAGE and sink very slowly as they grow.\n"
            "- The print head (with its fan shroud) moves left/right and front/back above the parts on the "
            "gantry and often covers part or most of the objects, more so on large or tall parts.\n"
            "- Before the print starts (homing, bed levelling, purge line) and after it ends, the bed can sit far "
            "down and the head can be parked at an edge. A bed that looks far away, small or empty at Z of tens "
            "or hundreds of millimetres is therefore normal at those moments.\n"
            "- Lattice, mesh and organic shapes look different as the head passes in front of them.\n"
            "So a part being partly hidden behind the head or gantry is NORMAL and never, on its own, evidence "
            "of a problem. Because the parts barely move in the image on this printer, a part that has clearly "
            "shifted in the image between frames while the bed was not lowered much IS suspicious."
        )
    return (
        f"How this printer moves:\n"
        f"- The {model.name} is a bed-slinger. The bed (print sheet) slides front/back all the time. Printed "
        "parts are stuck to the sheet and move WITH it, so from one frame to the next they appear in a "
        "different place in the IMAGE, larger or smaller, and seen from a different angle.\n"
        "- The print head (extruder with fan shroud) and the X gantry move left/right and climb with Z. They "
        "often cover part or most of the objects, more so as they get taller.\n"
        "- Lattice, mesh and organic shapes look very different from different angles and distances.\n"
        "So a part's position in the IMAGE, its apparent size, or it being partly hidden behind the head or "
        "gantry is NORMAL and never, on its own, evidence of a problem."
    )
