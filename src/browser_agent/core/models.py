"""
Browser Agent Models - Data classes for browser state and action results.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

if TYPE_CHECKING:
    from browser_agent.core.serialization import SelectorEntry


@dataclass
class BrowserState:
    """
    Complete snapshot of browser state for LLM consumption.
    
    This is the primary interface between the browser and the LLM.
    It contains everything needed to understand the page and take actions.
    """
    
    url: str
    title: str
    dom_text: str
    selector_map: Dict[int, "SelectorEntry"]  # P2-22: Proper type hint
    screenshot_base64: Optional[str] = None
    viewport_width: int = 1280
    viewport_height: int = 720
    # P2-21: Removed element_count field - use property instead
    
    @property
    def element_count(self) -> int:
        """Get the number of actionable elements (P2-21: Now a property)."""
        return len(self.selector_map)
    
    def get_element(self, index: int) -> Optional["SelectorEntry"]:
        """
        Get element metadata by index.
        
        Args:
            index: The element index from the serialized DOM (1-based).
            
        Returns:
            SelectorEntry if found, None otherwise.
        """
        return self.selector_map.get(index)
    
    def to_prompt(self, include_screenshot: bool = False) -> str:
        """
        Format the browser state for inclusion in an LLM prompt.
        
        Args:
            include_screenshot: If True, mention that a screenshot is available.
            
        Returns:
            Formatted string for LLM consumption.
        """
        lines = [
            f"URL: {self.url}",
            f"Title: {self.title}",
            f"Viewport: {self.viewport_width}x{self.viewport_height}",
            f"Elements: {self.element_count}",
            "",
            "=== Actionable Elements ===",
            self.dom_text,
        ]
        
        if include_screenshot and self.screenshot_base64:
            lines.insert(4, "Screenshot: [attached]")
        
        return "\n".join(lines)


@dataclass
class ActionResult:
    """
    Result of a browser action (click, type, scroll, etc.).
    
    Used to communicate action outcomes back to the LLM.
    """
    
    success: bool
    action_type: str
    element_index: Optional[int] = None
    error_message: Optional[str] = None
    extracted_content: Optional[str] = None
    screenshot_after: Optional[str] = None
    url_after: Optional[str] = None
    
    @classmethod
    def ok(
        cls,
        action_type: str,
        element_index: Optional[int] = None,
        extracted_content: Optional[str] = None,
    ) -> ActionResult:
        """Create a successful action result."""
        return cls(
            success=True,
            action_type=action_type,
            element_index=element_index,
            extracted_content=extracted_content,
        )
    
    @classmethod
    def error(
        cls,
        action_type: str,
        message: str,
        element_index: Optional[int] = None,
    ) -> ActionResult:
        """Create a failed action result."""
        return cls(
            success=False,
            action_type=action_type,
            element_index=element_index,
            error_message=message,
        )
    
    def to_message(self) -> str:
        """Format the result as a message for the LLM."""
        if self.success:
            msg = f"✓ {self.action_type}"
            if self.element_index is not None:
                msg += f" on element [{self.element_index}]"
            if self.extracted_content:
                msg += f": {self.extracted_content}"
            return msg
        else:
            msg = f"✗ {self.action_type} failed"
            if self.element_index is not None:
                msg += f" on element [{self.element_index}]"
            if self.error_message:
                msg += f": {self.error_message}"
            return msg


@dataclass
class AgentStep:
    """
    Record of a single agent step for history tracking.
    """
    
    step_number: int
    action_type: str
    action_params: Dict[str, Any] = field(default_factory=dict)
    result: Optional[ActionResult] = None
    url_before: Optional[str] = None
    url_after: Optional[str] = None
    screenshot_before: Optional[str] = None
    screenshot_after: Optional[str] = None
    duration_ms: float = 0.0


@dataclass
class AgentHistory:
    """
    Complete history of agent execution.
    """
    
    task: str
    steps: List[AgentStep] = field(default_factory=list)
    final_result: Optional[str] = None
    is_complete: bool = False
    total_duration_ms: float = 0.0
    
    def add_step(self, step: AgentStep) -> None:
        """Add a step to the history."""
        self.steps.append(step)
        self.total_duration_ms += step.duration_ms
    
    def urls(self) -> List[str]:
        """Get list of all visited URLs (P3-37: O(N) using set for deduplication)."""
        seen: set[str] = set()
        urls: List[str] = []
        for step in self.steps:
            if step.url_before and step.url_before not in seen:
                seen.add(step.url_before)
                urls.append(step.url_before)
            if step.url_after and step.url_after not in seen:
                seen.add(step.url_after)
                urls.append(step.url_after)
        return urls
    
    def action_names(self) -> List[str]:
        """Get list of all action types performed."""
        return [step.action_type for step in self.steps]
    
    def errors(self) -> List[str]:
        """Get list of all error messages."""
        errors = []
        for step in self.steps:
            if step.result and not step.result.success and step.result.error_message:
                errors.append(step.result.error_message)
        return errors
    
    def success_rate(self) -> float:
        """Calculate the success rate of actions."""
        if not self.steps:
            return 1.0
        successes = sum(1 for s in self.steps if s.result and s.result.success)
        return successes / len(self.steps)

