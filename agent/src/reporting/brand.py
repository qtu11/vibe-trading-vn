"""Single source of truth for Vibe-Trading design tokens and brand assets.

The palette mirrors the mastheads of Vietnamese broker research desks: a deep
navy field, one signal accent, and a rating colour that means the same thing
everywhere it appears. Every token here is consumed by :mod:`src.reporting.renderer`;
no renderer module should carry a colour or face of its own.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Brand:
    # ---- identity -------------------------------------------------------
    name: str = "VIBE-TRADING"
    legal: str = "VIBE-TRADING SECURITIES"
    desk: str = "RESEARCH"
    tagline: str = "AI  /  QUANT  /  MARKET RESEARCH"

    # ---- surfaces -------------------------------------------------------
    navy: str = "1A0F0F"
    deep: str = "3A1010"
    ink: str = "2B1717"
    muted: str = "7A6262"
    line: str = "EBDDDD"
    wash: str = "FCF6F5"
    white: str = "FFFFFF"

    # ---- signals (red-dominant) -----------------------------------------
    #: Primary accent: the "red shrimp" signal used for mastheads, rules,
    #: section numbers and featured highlights.
    crimson: str = "C81E1E"
    red: str = "DC2626"
    rose: str = "FEE2E2"
    blush: str = "FFF1F2"
    gold: str = "B45309"
    green: str = "15803D"
    amber: str = "C9821B"
    #: Kept for compatibility with chart helpers that still reference teal/cyan.
    teal: str = "C81E1E"
    cyan: str = "FECACA"
    mint: str = "FFF1F2"

    # ---- typography -----------------------------------------------------
    #: Arial is present on every Windows and macOS host and is mapped to the
    #: metric-compatible Liberation Sans on Linux; all three cover Vietnamese
    #: precomposed characters (U+1EA0–U+1EF9). A brand face that is not
    #: installed silently becomes an OS substitution, so the default stays a
    #: face we can actually promise.
    font: str = "Arial"
    font_cjk: str = "Microsoft YaHei"
    font_mono: str = "Consolas"
    locale: str = "vi-VN"

    #: Rating label -> colour. Keyed by the schema's own Vietnamese labels.
    rating_colors: dict[str, str] = field(
        default_factory=lambda: {
            "MUA": "15803D",
            "THEO DÕI": "B45309",
            "BÁN": "DC2626",
            "CHƯA XẾP HẠNG": "7A6262",
        }
    )

    def rating_tint(self, label: str) -> str:
        """A wash of the rating colour for panel backgrounds."""
        return {
            "MUA": "F0FDF4",
            "THEO DÕI": "FFFBEB",
            "BÁN": "FEF2F2",
        }.get(str(label).strip().upper(), self.wash)

    def rating_color(self, label: str) -> str:
        """The signal colour for a recommendation label, muted when unknown."""
        return self.rating_colors.get(str(label).strip().upper(), self.muted)


BRAND = Brand()


def resolve_brand_logo(*, prefer: str = "red") -> Path | None:
    """Find the highest-resolution official Vibe-Trading brand mark.

    ``prefer='red'`` selects the red-dominant mark used by the research desk.
    Falls back to the default mark so older assets still render.
    """
    current_file = Path(__file__).resolve()
    repo_root = current_file.parents[3]  # D:\Vibe-Trading

    red_candidates = [
        current_file.parent / "assets" / "shrimp_vest_logo.png",
        current_file.parents[2] / "vibe_report_engine" / "assets" / "shrimp_vest_logo.png",
        current_file.parent / "assets" / "vibe_logo_red.png",
        current_file.parents[2] / "vibe_report_engine" / "assets" / "vibe_logo_red.png",
        current_file.parent / "assets" / "vibe_shrimp_logo.png",
        current_file.parents[2] / "vibe_report_engine" / "assets" / "vibe_shrimp_logo.png",
    ]
    default_candidates = [
        current_file.parents[2] / "vibe_report_engine" / "assets" / "vibe_logo.png",
        repo_root / "frontend" / "public" / "logo-256.png",
        repo_root / "frontend" / "public" / "logo.png",
        repo_root / "assets" / "icon.png",
    ]
    ordered = red_candidates + default_candidates if prefer == "red" else default_candidates
    for candidate in ordered:
        if candidate.is_file():
            return candidate
    return None
