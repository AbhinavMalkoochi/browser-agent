"""
DOM Data Collection - Gathers DOM, Snapshot, Accessibility, and Metrics data from Chrome.
"""
import asyncio


async def get_dom(client):
    """Collect all required DOM data from Chrome DevTools Protocol."""
    results = await asyncio.gather(
        client.send("DOM.getDocument", {"depth": -1}),
        client.send("DOMSnapshot.captureSnapshot", {
            "computedStyles": [
                "display", "visibility", "opacity", "overflow", "overflow-x", 
                "overflow-y", "cursor", "pointer-events", "position"
            ]
        }),
        client.send("Accessibility.getFullAXTree", {}),
        client.send("Page.getLayoutMetrics", {}),
    )
    
    return {
        "dom": results[0],
        "snapshot": results[1], 
        "ax": results[2],
        "metrics": results[3]
    }
