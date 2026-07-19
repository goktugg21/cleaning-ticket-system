"""
RF-15 — shared PDF branding for both PDF families (extra_work proposal
PDFs + reports exports).

Single source of truth for the vendored brand assets and the embedded
Unicode font, so the two fpdf2 modules cannot drift:

  * `LOGO_PATH` — the Osius "facilities" logo committed under
    `backend/assets/branding/` (500x246 PNG with transparency).
  * `ACCENT_RGB` — the logo's sampled dominant color (#A82870), used
    for the subtle accent rule + header treatments.
  * `register_fonts(pdf)` — registers DejaVu Sans (regular + bold,
    vendored under `backend/assets/fonts/` with its license) on an
    FPDF instance under the family name `FONT_FAMILY`. This replaces
    the old Latin-1 core-Helvetica constraint: the embedded font
    renders the real euro sign and the full charset (Turkish names
    included). The PDF privacy tests extract TEXT via pypdf instead of
    grepping raw bytes, so glyph-ID encoding is no longer a problem.

The oblique style is not vendored; style "I" is registered against the
regular face so legacy italic call sites keep working (they render
upright — acceptable for the formal document pass).
"""
from __future__ import annotations

import logging
from pathlib import Path

from fpdf import FPDF

# fpdf2 subsets the embedded TTF on every render via fontTools, which
# logs pages of INFO noise under Django's logging config. Keep it quiet.
logging.getLogger("fontTools").setLevel(logging.WARNING)

ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets"
LOGO_PATH = ASSETS_DIR / "branding" / "osius_logo.png"
FONT_REGULAR_PATH = ASSETS_DIR / "fonts" / "DejaVuSans.ttf"
FONT_BOLD_PATH = ASSETS_DIR / "fonts" / "DejaVuSans-Bold.ttf"

# Sampled dominant opaque color of osius_logo.png (#A82870).
ACCENT_RGB: tuple[int, int, int] = (168, 40, 112)
# Very light tint of the accent for table-header fills.
ACCENT_TINT_RGB: tuple[int, int, int] = (247, 238, 243)

FONT_FAMILY = "DejaVu"

# Logo geometry: 500x246 source; rendered ~30mm wide in headers.
LOGO_WIDTH_MM = 30.0
LOGO_ASPECT = 246.0 / 500.0


def register_fonts(pdf: FPDF) -> None:
    """Register the vendored DejaVu Sans faces on `pdf`."""
    pdf.add_font(FONT_FAMILY, "", str(FONT_REGULAR_PATH))
    pdf.add_font(FONT_FAMILY, "B", str(FONT_BOLD_PATH))
    # No oblique face vendored — map italic onto the regular face so
    # style="I" call sites don't crash.
    pdf.add_font(FONT_FAMILY, "I", str(FONT_REGULAR_PATH))


def draw_logo(pdf: FPDF, *, y: float = 10.0) -> float:
    """Draw the brand logo top-left. Returns the y just under it."""
    pdf.image(str(LOGO_PATH), x=pdf.l_margin, y=y, w=LOGO_WIDTH_MM)
    return y + LOGO_WIDTH_MM * LOGO_ASPECT


def accent_rule(pdf: FPDF, y: float) -> None:
    """The subtle brand-magenta rule used under PDF headers."""
    pdf.set_draw_color(*ACCENT_RGB)
    pdf.set_line_width(0.6)
    pdf.line(pdf.l_margin, y, pdf.w - pdf.r_margin, y)
    pdf.set_line_width(0.2)
    pdf.set_draw_color(0, 0, 0)
