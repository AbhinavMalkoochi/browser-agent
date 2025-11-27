"""
DOM serialization utilities for turning EnhancedNode collections into
LLM-friendly text plus a selector map for resolving follow-up actions.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from enhanced_merger import EnhancedNode


@dataclass(frozen=True)
class SelectorEntry:
    """Lightweight metadata describing an actionable node."""

    backend_node_id: int
    frame_id: Optional[str]
    action_type: str
    click_point: Tuple[float, float]
    bounds_css: Tuple[float, float, float, float]
    attributes: Dict[str, str]
    confidence_score: float


@dataclass(frozen=True)
class SerializedOutput:
    """Result container for serialized DOM state."""

    lines: List[str]
    selector_map: Dict[int, SelectorEntry]

    @property
    def text(self) -> str:
        """Convenience accessor returning the joined text representation."""
        return "\n".join(self.lines)


DEFAULT_ATTR_ALLOWLIST: Tuple[str, ...] = (
    "id",
    "name",
    "class",
    "type",
    "role",
    "aria-label",
    "title",
    "placeholder",
)


def serialize_dom(
    nodes: Iterable[EnhancedNode],
    *,
    max_lines: int = 400,
    attr_allowlist: Sequence[str] = DEFAULT_ATTR_ALLOWLIST,
    max_text_length: int = 80,
) -> SerializedOutput:
    """
    Serialize actionable nodes to a compact, LLM-friendly text representation.

    Args:
        nodes: Iterable of EnhancedNode instances (already filtered for actionability).
        max_lines: Maximum number of lines to emit before truncating.
        attr_allowlist: Attributes to expose in the serialized text.
        max_text_length: Truncation threshold for text and attribute values.

    Returns:
        SerializedOutput containing both the text lines and selector map.
    """
    lines: List[str] = []
    selector_map: Dict[int, SelectorEntry] = {}

    def _truncate(value: str) -> str:
        value = value.strip()
        if len(value) <= max_text_length:
            return value
        return value[: max_text_length - 3] + "..."

    actionable_nodes = list(nodes)
    total_nodes = len(actionable_nodes)

    for index, node in enumerate(actionable_nodes, start=1):
        selector_map[index] = SelectorEntry(
            backend_node_id=node.backend_node_id,
            frame_id=node.frame_id,
            action_type=node.action_type,
            click_point=node.click_point,
            bounds_css=node.bounds_css,
            attributes=dict(node.attributes),
            confidence_score=node.confidence_score,
        )

        attr_parts = []
        for attr in attr_allowlist:
            value = node.attributes.get(attr)
            if value:
                attr_parts.append(f'{attr}="{_truncate(value)}"')

        tag_repr = f"<{node.tag_name}>"
        if attr_parts:
            tag_repr = f"<{node.tag_name} {' '.join(attr_parts)}>"

        info_parts = [f"[{index}] {tag_repr}", f"action={node.action_type}", f"conf={node.confidence_score:.2f}"]

        if node.ax_name:
            info_parts.append(f'name="{_truncate(node.ax_name)}"')

        text_content = node.text_content.strip()
        if text_content and text_content != node.ax_name:
            info_parts.append(f'text="{_truncate(text_content)}"')

        if node.is_focusable:
            info_parts.append("focusable")

        if not node.is_clickable and node.action_type == "click":
            info_parts.append("not-clickable")

        lines.append(" | ".join(info_parts))

        if len(lines) >= max_lines:
            remaining = total_nodes - index
            if remaining > 0:
                lines.append(f"... truncated {remaining} additional elements")
            break

    return SerializedOutput(lines=lines, selector_map=selector_map)

