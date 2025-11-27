"""
Core types for LLM interaction.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class ToolCall:
    """A single tool call from the LLM."""
    id: str
    name: str
    arguments: Dict[str, Any]


@dataclass
class LLMResponse:
    """Response from an LLM backend."""
    content: Optional[str] = None
    tool_calls: List[ToolCall] = field(default_factory=list)
    finish_reason: str = "stop"
    
    @property
    def has_tool_calls(self) -> bool:
        return len(self.tool_calls) > 0

