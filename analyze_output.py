#!/usr/bin/env python3
"""
Script to analyze the output.txt file and show you how to navigate the data
"""
import json
import re

def load_sections(filename):
    """Load and parse the four sections from output.txt"""
    print("📖 Loading data sections...")
    
    with open(filename, 'r') as f:
        content = f.read()
    
    # Split into sections by finding the headers
    sections = {}
    
    try:
        # Find section start positions
        dom_start = content.find('DOM: {')
        snapshot_start = content.find('SNAPSHOT: {')
        ax_start = content.find('AX: {')
        metrics_start = content.find('METRICS: {')
        
        if dom_start == -1 or snapshot_start == -1 or ax_start == -1 or metrics_start == -1:
            print("❌ Could not find all section headers")
            return None
        
        # Extract JSON content for each section
        dom_json = content[dom_start + 5:snapshot_start].strip()
        snapshot_json = content[snapshot_start + 10:ax_start].strip()
        ax_json = content[ax_start + 4:metrics_start].strip()
        
        # For metrics, find the end of the JSON (look for closing brace)
        metrics_content = content[metrics_start + 9:]
        
        # Find the end of the JSON by counting braces
        brace_count = 0
        json_end = -1
        for i, char in enumerate(metrics_content):
            if char == '{':
                brace_count += 1
            elif char == '}':
                brace_count -= 1
                if brace_count == 0:
                    json_end = i + 1
                    break
        
        if json_end == -1:
            print("❌ Could not find end of METRICS JSON")
            return None
            
        metrics_json = metrics_content[:json_end].strip()
        
        print("🔍 Parsing DOM section...")
        sections['dom'] = json.loads(dom_json)
        
        print("🔍 Parsing Snapshot section...")
        sections['snapshot'] = json.loads(snapshot_json)
        
        print("🔍 Parsing Accessibility section...")
        sections['ax'] = json.loads(ax_json)
        
        print("🔍 Parsing Metrics section...")
        sections['metrics'] = json.loads(metrics_json)
        
        print("✅ All sections loaded successfully!")
        return sections
        
    except json.JSONDecodeError as e:
        print(f"❌ JSON parsing error: {e}")
        print("💡 Tip: Make sure your output.txt file has valid JSON in each section")
        return None
    except Exception as e:
        print(f"❌ Error loading sections: {e}")
        return None

def analyze_dom_structure(dom_data):
    """Analyze the DOM tree structure"""
    print("\n" + "="*60)
    print("🌳 DOM TREE ANALYSIS")
    print("="*60)
    
    interactive_elements = []
    
    def traverse_dom(node, level=0):
        if level > 10:  # Prevent infinite recursion
            return
            
        node_type = node.get('nodeType', 0)
        if node_type == 1:  # Element node
            tag = node.get('nodeName', '').lower()
            backend_id = node.get('backendNodeId')
            
            # Get attributes
            attrs = node.get('attributes', [])
            attr_dict = {}
            for i in range(0, len(attrs), 2):
                if i + 1 < len(attrs):
                    attr_dict[attrs[i]] = attrs[i + 1]
            
            # Check if interactive
            is_interactive = (
                tag in ['button', 'a', 'input', 'select', 'textarea'] or
                'onclick' in attr_dict or
                attr_dict.get('role') in ['button', 'link', 'textbox']
            )
            
            if is_interactive:
                interactive_elements.append({
                    'tag': tag,
                    'backend_id': backend_id,
                    'attributes': attr_dict,
                    'level': level
                })
        
        # Recurse into children
        for child in node.get('children', []):
            traverse_dom(child, level + 1)
    
    traverse_dom(dom_data['root'])
    
    print(f"📊 Found {len(interactive_elements)} potentially interactive elements:")
    for i, elem in enumerate(interactive_elements[:10]):  # Show first 10
        indent = "  " * elem['level']
        attrs_str = ""
        for key in ['id', 'class', 'type', 'href']:
            if key in elem['attributes']:
                attrs_str += f" {key}='{elem['attributes'][key][:30]}'"
        
        print(f"  {i+1}. {indent}<{elem['tag']}{attrs_str}> [backendId: {elem['backend_id']}]")
    
    return interactive_elements

def analyze_snapshot_data(snapshot_data, interactive_elements):
    """Analyze the snapshot positioning data"""
    print("\n" + "="*60)
    print("📸 SNAPSHOT DATA ANALYSIS")
    print("="*60)
    
    # Get the first document (main page)
    doc = snapshot_data['documents'][0]
    nodes = doc['nodes']
    layout = doc.get('layout', {})
    
    # Extract arrays
    backend_ids = nodes.get('backendNodeId', [])
    bounds = layout.get('bounds', [])
    
    print(f"📊 Snapshot contains:")
    print(f"   - {len(backend_ids)} backend node IDs")
    print(f"   - {len(bounds)} bounding rectangles")
    
    # Correlate with interactive elements
    print(f"\n🔍 Correlating interactive elements with positions:")
    
    positioned_elements = []
    
    for elem in interactive_elements[:5]:  # Check first 5
        backend_id = elem['backend_id']
        
        try:
            # Find index in snapshot
            index = backend_ids.index(backend_id)
            
            if index < len(bounds):
                bound = bounds[index]
                x, y, w, h = bound
                
                positioned_elements.append({
                    **elem,
                    'bounds': bound,
                    'snapshot_index': index
                })
                
                print(f"   ✅ {elem['tag']} (backendId: {backend_id})")
                print(f"      Position: x={x}, y={y}, width={w}, height={h}")
                print(f"      Snapshot index: {index}")
                
        except ValueError:
            print(f"   ❌ {elem['tag']} (backendId: {backend_id}) - Not found in snapshot")
    
    return positioned_elements

def analyze_accessibility_data(ax_data, positioned_elements):
    """Analyze accessibility tree data"""
    print("\n" + "="*60)
    print("♿ ACCESSIBILITY ANALYSIS")
    print("="*60)
    
    ax_nodes = ax_data.get('nodes', [])
    print(f"📊 Accessibility tree contains {len(ax_nodes)} nodes")
    
    # Find interactive elements in AX tree
    print(f"\n🔍 Finding accessibility info for positioned elements:")
    
    enhanced_elements = []
    
    for elem in positioned_elements:
        backend_id = elem['backend_id']
        
        # Find in AX tree
        ax_info = None
        for ax_node in ax_nodes:
            if ax_node.get('backendDOMNodeId') == backend_id:
                ax_info = ax_node
                break
        
        if ax_info:
            role = ax_info.get('role', {}).get('value', 'unknown')
            name = ax_info.get('name', {}).get('value', '')
            
            # Extract properties
            properties = {}
            for prop in ax_info.get('properties', []):
                prop_name = prop.get('name')
                prop_value = prop.get('value', {}).get('value')
                if prop_name and prop_value is not None:
                    properties[prop_name] = prop_value
            
            enhanced_elem = {
                **elem,
                'ax_role': role,
                'ax_name': name,
                'ax_properties': properties
            }
            enhanced_elements.append(enhanced_elem)
            
            print(f"   ✅ {elem['tag']} (backendId: {backend_id})")
            print(f"      Role: {role}")
            print(f"      Name: '{name}'")
            print(f"      Properties: {properties}")
        else:
            print(f"   ❌ {elem['tag']} (backendId: {backend_id}) - No AX info")
    
    return enhanced_elements

def analyze_metrics(metrics_data):
    """Analyze viewport and scaling metrics"""
    print("\n" + "="*60)
    print("📏 METRICS ANALYSIS")
    print("="*60)
    
    visual_viewport = metrics_data.get('visualViewport', {})
    css_viewport = metrics_data.get('cssVisualViewport', {})
    
    visual_width = visual_viewport.get('clientWidth', 0)
    css_width = css_viewport.get('clientWidth', 0)
    
    dpr = visual_width / css_width if css_width > 0 else 1
    
    print(f"📱 Visual Viewport: {visual_width} x {visual_viewport.get('clientHeight', 0)}")
    print(f"📱 CSS Viewport: {css_width} x {css_viewport.get('clientHeight', 0)}")
    print(f"🔍 Device Pixel Ratio: {dpr:.2f}")
    print(f"📏 Zoom Level: {visual_viewport.get('scale', 1)}")
    
    return dpr

def demonstrate_coordinate_conversion(enhanced_elements, dpr):
    """Show how to convert device pixels to CSS pixels"""
    print("\n" + "="*60)
    print("🎯 COORDINATE CONVERSION DEMO")
    print("="*60)
    
    print(f"Device Pixel Ratio: {dpr}")
    print("Converting bounds from device pixels to CSS pixels:\n")
    
    for elem in enhanced_elements[:3]:
        device_bounds = elem['bounds']
        device_x, device_y, device_w, device_h = device_bounds
        
        # Convert to CSS pixels
        css_x = device_x / dpr
        css_y = device_y / dpr
        css_w = device_w / dpr
        css_h = device_h / dpr
        
        # Calculate click point (center)
        click_x = css_x + css_w / 2
        click_y = css_y + css_h / 2
        
        print(f"🎯 {elem['tag']} '{elem.get('ax_name', '')}':")
        print(f"   Device pixels: [{device_x}, {device_y}, {device_w}, {device_h}]")
        print(f"   CSS pixels:    [{css_x:.1f}, {css_y:.1f}, {css_w:.1f}, {css_h:.1f}]")
        print(f"   Click point:   ({click_x:.1f}, {click_y:.1f})")
        print()

def main():
    """Main analysis function"""
    print("🔍 Browser Data Analyzer")
    print("This script will help you understand your output.txt file")
    print()
    
    # Load data
    sections = load_sections('output.txt')
    if not sections:
        return
    
    # Analyze each section
    interactive_elements = analyze_dom_structure(sections['dom'])
    positioned_elements = analyze_snapshot_data(sections['snapshot'], interactive_elements)
    enhanced_elements = analyze_accessibility_data(sections['ax'], positioned_elements)
    dpr = analyze_metrics(sections['metrics'])
    
    # Demonstrate coordinate conversion
    demonstrate_coordinate_conversion(enhanced_elements, dpr)
    
    print("\n" + "="*60)
    print("✅ ANALYSIS COMPLETE")
    print("="*60)
    print("Key takeaways:")
    print("1. Use backendNodeId as the primary key to correlate data")
    print("2. Snapshot bounds are in device pixels - divide by DPR for CSS pixels")
    print("3. Accessibility tree tells you what's actually interactive")
    print("4. Click at the center of CSS pixel bounds for reliable targeting")
    print()
    print("Next step: Build a data merger that creates enhanced nodes!")

if __name__ == "__main__":
    main()
