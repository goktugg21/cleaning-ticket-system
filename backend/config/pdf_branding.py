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
from io import BytesIO
from pathlib import Path

from django.conf import settings
from fpdf import FPDF
from PIL import Image

logger = logging.getLogger(__name__)

# fpdf2 subsets the embedded TTF on every render via fontTools, which
# logs pages of INFO noise under Django's logging config. Keep it quiet.
logging.getLogger("fontTools").setLevel(logging.WARNING)

ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets"
LOGO_PATH = ASSETS_DIR / "branding" / "osius_logo.png"
FONT_REGULAR_PATH = ASSETS_DIR / "fonts" / "DejaVuSans.ttf"
FONT_BOLD_PATH = ASSETS_DIR / "fonts" / "DejaVuSans-Bold.ttf"

# --- OSIUS platform brand (used ONLY for the platform company) ---
# Sampled dominant opaque color of osius_logo.png (#A82870).
ACCENT_RGB: tuple[int, int, int] = (168, 40, 112)
# Very light tint of the accent for table-header fills.
ACCENT_TINT_RGB: tuple[int, int, int] = (247, 238, 243)

# --- Neutral brand (any non-platform single-company PDF + cross-company
# reports): a plain grey accent + a light-grey tint, so a non-OSIUS document
# never prints the OSIUS pink. ---
NEUTRAL_ACCENT_RGB: tuple[int, int, int] = (90, 90, 96)
NEUTRAL_TINT_RGB: tuple[int, int, int] = (238, 238, 240)

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


def is_platform_brand(company) -> bool:
    """True iff `company` is the OSIUS platform company (its slug matches
    `settings.PLATFORM_BRAND_SLUG`). The OSIUS designed branding (the
    hardcoded logo + pink accent) is used ONLY for this company."""
    return (
        company is not None
        and getattr(company, "slug", None) == settings.PLATFORM_BRAND_SLUG
    )


def accent_rgb_for(company) -> tuple[int, int, int]:
    """The header accent color for a single-company PDF: OSIUS pink for the
    platform company, the neutral grey for any other company (or None)."""
    return ACCENT_RGB if is_platform_brand(company) else NEUTRAL_ACCENT_RGB


def accent_tint_for(company) -> tuple[int, int, int]:
    """The table-header tint for a single-company PDF: the OSIUS tint for the
    platform company, the neutral light-grey otherwise (or None)."""
    return ACCENT_TINT_RGB if is_platform_brand(company) else NEUTRAL_TINT_RGB


def _draw_name_header(pdf: FPDF, company, y: float) -> float:
    """Name-only fallback header (no image). Draws the company name bold in
    the logo slot; returns the y under it. `company is None` draws nothing
    (cross-company reports have no single name)."""
    if company is None:
        return y
    name = (getattr(company, "name", "") or "").strip()
    if not name:
        return y
    pdf.set_xy(pdf.l_margin, y)
    pdf.set_font(FONT_FAMILY, "B", 16)
    pdf.cell(110, 8, name)
    return y + 8.0


def draw_logo(pdf: FPDF, company, *, y: float = 10.0) -> float:
    """Draw the header brand mark top-left, COMPANY-AWARE. Returns the y just
    under whatever was drawn.

      * platform (OSIUS): the hardcoded osius_logo.png at the tuned aspect
        — UNCHANGED behavior.
      * else a company WITH a set `logo` ImageField: that logo, preserving
        ITS OWN aspect ratio (read via Pillow). Any failure (unreadable /
        unsupported format) falls back to the name-only header.
      * else (no logo, or `company is None`): the name-only header
        (`company is None` -> nothing).
    """
    if is_platform_brand(company):
        pdf.image(str(LOGO_PATH), x=pdf.l_margin, y=y, w=LOGO_WIDTH_MM)
        return y + LOGO_WIDTH_MM * LOGO_ASPECT

    logo_field = getattr(company, "logo", None) if company is not None else None
    if logo_field:
        try:
            logo_field.open("rb")
            try:
                data = logo_field.read()
            finally:
                logo_field.close()
            bio = BytesIO(data)
            with Image.open(bio) as img:
                width_px, height_px = img.size
            aspect = (height_px / width_px) if width_px else LOGO_ASPECT
            bio.seek(0)
            pdf.image(bio, x=pdf.l_margin, y=y, w=LOGO_WIDTH_MM)
            return y + LOGO_WIDTH_MM * aspect
        except Exception:  # noqa: BLE001 — any failure -> name-only fallback
            logger.warning(
                "draw_logo: could not render logo for company %s; "
                "falling back to the name-only header.",
                getattr(company, "slug", None),
                exc_info=True,
            )

    return _draw_name_header(pdf, company, y)


def accent_rule(pdf: FPDF, y: float, rgb: tuple[int, int, int] | None = None) -> None:
    """The subtle accent rule under PDF headers. Pass the resolved brand
    accent (`accent_rgb_for(company)` / a neutral); defaults to the OSIUS
    pink when omitted (legacy callers)."""
    pdf.set_draw_color(*(rgb or ACCENT_RGB))
    pdf.set_line_width(0.6)
    pdf.line(pdf.l_margin, y, pdf.w - pdf.r_margin, y)
    pdf.set_line_width(0.2)
    pdf.set_draw_color(0, 0, 0)
