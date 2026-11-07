"""Server-owned evidence available only while an agent invokes a tool."""

from contextvars import ContextVar
from typing import Any


current_grounding: ContextVar[Any | None] = ContextVar("tool_grounding", default=None)
