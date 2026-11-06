"""Single source of truth for Vibe-Trading design tokens."""
from dataclasses import dataclass

@dataclass(frozen=True)
class Brand:
    name: str = "VIBE-TRADING"
    subbrand: str = "VIBE RESEARCH  /  AI  ·  QUANT  ·  TRADING"
    navy: str = "071827"
    deep: str = "0B2235"
    teal: str = "13C6B0"
    green: str = "17B978"
    mint: str = "E7F8F3"
    cyan: str = "C8F5EF"
    ink: str = "173146"
    muted: str = "6B7C89"
    line: str = "DCE7EB"
    white: str = "FFFFFF"
    orange: str = "F16B46"
    font: str = "Inter"

BRAND = Brand()
