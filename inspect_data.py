#!/usr/bin/env python3
"""
Script to inspect raw CDP data and trace elements
"""
import asyncio
import json
from cdp import CDPClient, get_page_ws_url

async def inspect_raw_data():
    """Connect to Chrome and inspect the raw data structures"""
    
    print("🔍 Connecting to Chrome...")
    try:
        ws_url = await get_page_ws_url()
        cdp = CDPClient(ws_url)
        await cdp.connect()
        
        # Enable required domains
        await cdp.send("Page.enable", {})
        await cdp.send("Runtime.enable", {})
        await cdp.send("DOM.enable", {})
        
        print("✅ Connected! Navigating to a simple test page...")
        
        # Navigate to a simple page for testing
        await cdp.send("Page.navigate", {"url": "https://example.com"})
        await asyncio.sleep(3)  # Wait for page to load
        
        print("📊 Collecting data from Chrome...")
        
        # Collect all the data
        results = await asyncio.gather(
            cdp.send("DOM.getDocument", {"depth": -1}),
            cdp.send("DOMSnapshot.captureSnapshot", {
                "computedStyles": [
                    "display", "visibility", "opacity", "overflow", 
                    "cursor", "pointer-events", "position"
                ]
            }),
            cdp.send("Accessibility.getFullAXTree", {}),
            cdp.send("Page.getLayoutMetrics", {})
        )
        
        dom_tree = results[0]
        snapshot = results[1]
        ax_tree = results[2]
        metrics = results[3]
        
        print("\n" + "="*80)
        print("🌳 DOM TREE STRUCTURE")
        print("="*80)
        print_dom_tree(dom_tree["root"], level=0, max_level=3)
        
        print("\n" + "="*80)
        print("📸 SNAPSHOT DATA OVERVIEW")
        print("="*80)
        print_snapshot_overview(snapshot)
        
        print("\n" + "="*80)
        print("♿ ACCESSIBILITY TREE OVERVIEW") 
        print("="*80)
        print_ax_overview(ax_tree)
        
        print("\n" + "="*80)
        print("📏 LAYOUT METRICS")
        print("="*80)
        print_metrics(metrics)
        
        print("\n" + "="*80)
        print("🔍 ELEMENT TRACING EXAMPLE")
        print("="*80)
        await trace_specific_elements(dom_tree, snapshot, ax_tree, metrics)
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()

def print_dom_tree(node, level=0, max_level=5):
    """Print DOM tree structure in a readable format"""
    if level > max_level:
        return
        
    indent = "  " * level
    node_type = node.get("nodeType", 0)
    
    if node_type == 1:  # Element node
        tag = node.get("nodeName", "").lower()
        attrs = node.get("attributes", [])
        
        # Convert attributes list to dict
        attr_dict = {}
        for i in range(0, len(attrs), 2):
            if i + 1 < len(attrs):
                attr_dict[attrs[i]] = attrs[i + 1]
        
        # Show key attributes
        attr_str = ""
        for key in ["id", "class", "type", "name"]:
            if key in attr_dict:
                attr_str += f' {key}="{attr_dict[key][:30]}"'
        
        print(f"{indent}<{tag}{attr_str}> [nodeId: {node.get('nodeId')}, backendNodeId: {node.get('backendNodeId')}]")
        
    elif node_type == 3:  # Text node
        text = node.get("nodeValue", "").strip()
        if text and len(text) > 0:
            text_preview = text[:50].replace('\n', '\\n')
            print(f"{indent}TEXT: \"{text_preview}\"")
    
    # Process children
    for child in node.get("children", []):
        print_dom_tree(child, level + 1, max_level)

def print_snapshot_overview(snapshot):
    """Print overview of snapshot data"""
    print(f"📊 Snapshot contains:")
    print(f"   - {len(snapshot.get('backendNodeIds', []))} backend node IDs")
    print(f"   - {len(snapshot.get('bounds', []))} bounding rectangles")
    print(f"   - {len(snapshot.get('clientRects', []))} client rectangles")
    print(f"   - {len(snapshot.get('computedStyles', []))} computed style sets")
    print(f"   - {len(snapshot.get('paintOrders', []))} paint order values")
    
    # Show first few backend node IDs and their bounds
    backend_ids = snapshot.get('backendNodeIds', [])
    bounds = snapshot.get('bounds', [])
    
    print(f"\n📍 First 5 elements with positions:")
    for i in range(min(5, len(backend_ids))):
        if i < len(bounds):
            bound = bounds[i]
            print(f"   backendNodeId {backend_ids[i]}: x={bound[0]:.1f}, y={bound[1]:.1f}, w={bound[2]:.1f}, h={bound[3]:.1f}")

def print_ax_overview(ax_tree):
    """Print overview of accessibility tree"""
    nodes = ax_tree.get("nodes", [])
    print(f"♿ Accessibility tree contains {len(nodes)} nodes")
    
    # Count roles
    roles = {}
    interactive_count = 0
    
    for node in nodes[:20]:  # Look at first 20 nodes
        role = node.get("role", {}).get("value", "unknown")
        roles[role] = roles.get(role, 0) + 1
        
        # Check if interactive
        properties = node.get("properties", [])
        for prop in properties:
            if prop.get("name") == "focusable" and prop.get("value", {}).get("value"):
                interactive_count += 1
                break
    
    print(f"🎭 Common roles found: {dict(list(roles.items())[:10])}")
    print(f"🖱️  Interactive elements found: {interactive_count}")

def print_metrics(metrics):
    """Print layout metrics"""
    css_viewport = metrics.get("cssVisualViewport", {})
    device_viewport = metrics.get("visualViewport", {})
    
    css_width = css_viewport.get("clientWidth", 0)
    device_width = device_viewport.get("clientWidth", 0)
    
    dpr = device_width / css_width if css_width > 0 else 1
    
    print(f"📱 CSS Viewport: {css_width} x {css_viewport.get('clientHeight', 0)}")
    print(f"📱 Device Viewport: {device_width} x {device_viewport.get('clientHeight', 0)}")
    print(f"🔍 Device Pixel Ratio: {dpr:.2f}")
    print(f"📏 Page Scale Factor: {css_viewport.get('scale', 1)}")

async def trace_specific_elements(dom_tree, snapshot, ax_tree, metrics):
    """Trace specific elements through all three data sources"""
    print("🔍 Let's trace some elements through all data sources...\n")
    
    # Find interesting elements in DOM tree
    interesting_elements = []
    find_interesting_elements(dom_tree["root"], interesting_elements)
    
    print(f"Found {len(interesting_elements)} interesting elements:")
    
    for i, element in enumerate(interesting_elements[:3]):  # Show first 3
        print(f"\n--- ELEMENT {i+1}: {element['tag']} ---")
        trace_single_element(element, snapshot, ax_tree, metrics)

def find_interesting_elements(node, results, max_results=10):
    """Find interesting elements (buttons, links, inputs) in DOM tree"""
    if len(results) >= max_results:
        return
        
    node_type = node.get("nodeType", 0)
    if node_type == 1:  # Element node
        tag = node.get("nodeName", "").lower()
        
        # Look for interactive elements
        if tag in ["button", "a", "input", "select", "textarea"]:
            attrs = node.get("attributes", [])
            attr_dict = {}
            for i in range(0, len(attrs), 2):
                if i + 1 < len(attrs):
                    attr_dict[attrs[i]] = attrs[i + 1]
            
            results.append({
                "tag": tag,
                "nodeId": node.get("nodeId"),
                "backendNodeId": node.get("backendNodeId"),
                "attributes": attr_dict
            })
    
    # Recurse into children
    for child in node.get("children", []):
        find_interesting_elements(child, results, max_results)

def trace_single_element(element, snapshot, ax_tree, metrics):
    """Trace a single element through all data sources"""
    backend_id = element["backendNodeId"]
    
    print(f"🏷️  DOM: {element['tag']} (backendNodeId: {backend_id})")
    if element["attributes"]:
        print(f"   Attributes: {element['attributes']}")
    
    # Find in snapshot data
    backend_ids = snapshot.get("backendNodeIds", [])
    try:
        snapshot_index = backend_ids.index(backend_id)
        
        # Get bounds (in device pixels)
        bounds = snapshot.get("bounds", [])[snapshot_index]
        device_x, device_y, device_w, device_h = bounds
        
        # Convert to CSS pixels
        dpr = calculate_dpr(metrics)
        css_x = device_x / dpr
        css_y = device_y / dpr
        css_w = device_w / dpr
        css_h = device_h / dpr
        
        print(f"📸 Snapshot: Found at index {snapshot_index}")
        print(f"   Device pixels: x={device_x:.1f}, y={device_y:.1f}, w={device_w:.1f}, h={device_h:.1f}")
        print(f"   CSS pixels: x={css_x:.1f}, y={css_y:.1f}, w={css_w:.1f}, h={css_h:.1f}")
        
        # Get computed styles
        computed_styles = snapshot.get("computedStyles", [])
        if snapshot_index < len(computed_styles):
            styles = computed_styles[snapshot_index]
            print(f"   Styles: {styles}")
        
        # Get paint order
        paint_orders = snapshot.get("paintOrders", [])
        if snapshot_index < len(paint_orders):
            paint_order = paint_orders[snapshot_index]
            print(f"   Paint order: {paint_order}")
            
    except ValueError:
        print(f"📸 Snapshot: ❌ Not found (backendNodeId {backend_id} not in snapshot)")
    
    # Find in accessibility tree
    ax_nodes = ax_tree.get("nodes", [])
    found_ax = False
    for ax_node in ax_nodes:
        if ax_node.get("backendDOMNodeId") == backend_id:
            role = ax_node.get("role", {}).get("value", "unknown")
            print(f"♿ Accessibility: role='{role}'")
            
            # Show properties
            properties = ax_node.get("properties", [])
            prop_dict = {}
            for prop in properties:
                name = prop.get("name")
                value = prop.get("value", {})
                if "value" in value:
                    prop_dict[name] = value["value"]
            
            if prop_dict:
                print(f"   Properties: {prop_dict}")
            found_ax = True
            break
    
    if not found_ax:
        print(f"♿ Accessibility: ❌ Not found")

def calculate_dpr(metrics):
    """Calculate device pixel ratio from metrics"""
    css_width = metrics.get("cssVisualViewport", {}).get("clientWidth", 1)
    device_width = metrics.get("visualViewport", {}).get("clientWidth", 1)
    return device_width / css_width if css_width > 0 else 1

if __name__ == "__main__":
    print("🔍 CDP Data Inspector")
    print("Make sure Chrome is running with: python launch_chrome.py")
    print()
    
    asyncio.run(inspect_raw_data())
