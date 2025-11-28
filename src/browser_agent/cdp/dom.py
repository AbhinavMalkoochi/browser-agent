"""
DOM Data Collection - Gathers DOM, Snapshot, Accessibility, and Metrics data from Chrome.
"""
import asyncio
import logging
from typing import TYPE_CHECKING, Any, Dict

if TYPE_CHECKING:
    from browser_agent.cdp.client import CDPClient

logger = logging.getLogger("browser_agent")

# Default computed styles to capture (P2-28: Extract as constant)
DEFAULT_COMPUTED_STYLES = [
    "display", "visibility", "opacity", "overflow", "overflow-x", 
    "overflow-y", "cursor", "pointer-events", "position"
]

# Default timeout for DOM operations
DEFAULT_DOM_TIMEOUT = 30.0


async def get_dom(client: "CDPClient", timeout: float = DEFAULT_DOM_TIMEOUT) -> Dict[str, Any]:
    """
    Collect all required DOM data from Chrome DevTools Protocol.
    
    Args:
        client: CDPClient instance.
        timeout: Maximum time to wait for all operations (seconds).
        
    Returns:
        Dictionary with keys: dom, snapshot, ax, metrics
    """
    try:
        # Use return_exceptions=True to handle partial failures gracefully (P0-6)
        # Wrap in wait_for to prevent indefinite hanging (P1-15)
        results = await asyncio.wait_for(
            asyncio.gather(
                client.send("DOM.getDocument", {"depth": -1}),
                client.send("DOMSnapshot.captureSnapshot", {
                    "computedStyles": DEFAULT_COMPUTED_STYLES
                }),
                client.send("Accessibility.getFullAXTree", {}),
                client.send("Page.getLayoutMetrics", {}),
                return_exceptions=True,
            ),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        logger.error(f"DOM data collection timed out after {timeout}s")
        raise
    
    # Process results, handling any exceptions
    dom_result = results[0]
    snapshot_result = results[1]
    ax_result = results[2]
    metrics_result = results[3]
    
    # Log warnings for failed operations but continue with partial data
    if isinstance(dom_result, Exception):
        logger.warning(f"DOM.getDocument failed: {dom_result}")
        dom_result = {"root": {}}
    
    if isinstance(snapshot_result, Exception):
        logger.warning(f"DOMSnapshot.captureSnapshot failed: {snapshot_result}")
        snapshot_result = {"documents": [], "strings": []}
    
    if isinstance(ax_result, Exception):
        logger.warning(f"Accessibility.getFullAXTree failed: {ax_result}")
        ax_result = {"nodes": []}
    
    if isinstance(metrics_result, Exception):
        logger.warning(f"Page.getLayoutMetrics failed: {metrics_result}")
        metrics_result = {}
    
    return {
        "dom": dom_result,
        "snapshot": snapshot_result, 
        "ax": ax_result,
        "metrics": metrics_result
    }

