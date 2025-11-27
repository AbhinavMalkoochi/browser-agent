"""
DOM Data Collection - Gathers DOM, Snapshot, Accessibility, and Metrics data from Chrome.
"""
import asyncio
from typing import Optional

from cdp import CDPClient


async def get_dom(client: CDPClient, session_id: Optional[str] = None):
    """
    Collect all required DOM data from Chrome DevTools Protocol.
    
    This function ensures all required domains are enabled before collecting data.
    
    Args:
        client: CDPClient instance.
        session_id: Optional explicit session override.
    
    Returns:
        Dictionary with keys: 'dom', 'snapshot', 'ax', 'metrics'
    """
    session_id = await client._ensure_session_active(session_id)
    
    # Ensure all required domains are enabled
    required_domains = ["DOM", "DOMSnapshot", "Accessibility", "Page"]
    await client.enable_domains(required_domains, session_id)
    
    # Collect all data in parallel
    results = await asyncio.gather(
        client.send("DOM.getDocument", {"depth": -1}, session_id=session_id),
        client.send("DOMSnapshot.captureSnapshot", {
            "computedStyles": [
                "display", "visibility", "opacity", "overflow", "overflow-x", 
                "overflow-y", "cursor", "pointer-events", "position"
            ]
        }, session_id=session_id),
        client.send("Accessibility.getFullAXTree", {}, session_id=session_id),
        client.send("Page.getLayoutMetrics", {}, session_id=session_id),
    )
    
    return {
        "dom": results[0],
        "snapshot": results[1], 
        "ax": results[2],
        "metrics": results[3]
    }
