import asyncio


async def get_dom(client):
    results = await asyncio.gather(
        client.send("DOM.getDocument", {"depth": -1}),
        client.send(
            "DOMSnapshot.captureSnapshot",
            {
                "computedStyles": [
                    "display",
                    "visibility",
                    "opacity",
                    "overflow",
                    "overflow-x",
                    "overflow-y",
                    "cursor",
                    "pointer-events",
                    "position",
                ]
            },
        ),
        client.send("Accessibility.getFullAXTree", {}),
        client.send("Page.getLayoutMetrics", {}),
    )
    dom_tree = results[0]
    #gives x,y,width,height in pixel w styles, paint order, whats scrollable
    snapshot = results[1]
    # provides role(if button,link, etc) and their states(pressed,disables,etc) and other proprties
    ax_tree = results[2]
    # gives conversion from css pixels tod evice pixels and viewport
    metrics = results[3]
    return {"dom": dom_tree, "snapshot": snapshot, "ax": ax_tree, "metrics": metrics}


def calculate_dpr(metrics):
    css_width = metrics["cssVisualViewport"]["clientWidth"]
    device_width = metrics["visualViewport"]["clientWidth"]
    dpr = device_width / css_width
    return dpr
