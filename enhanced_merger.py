#!/usr/bin/env python3
"""
Enhanced Node Merger - The core intelligence that transforms raw CDP data 
into actionable, filtered browser elements for LLM interaction.
"""

import sys
sys.path.append('.')
from analyze_output import load_sections
from dataclasses import dataclass
from typing import List, Dict, Optional, Tuple, Any

@dataclass
class EnhancedNode:
    """
    A unified representation of a browser element combining DOM, Snapshot, and AX data
    """
    # Core identifiers
    backend_node_id: int
    tag_name: str
    
    # Position & geometry (CSS pixels)
    bounds_css: Tuple[float, float, float, float]  # (x, y, width, height)
    click_point: Tuple[float, float]  # (x, y) center point for clicking
    
    # DOM attributes
    attributes: Dict[str, str]
    text_content: str
    
    # Accessibility data
    ax_role: Optional[str]
    ax_name: str
    ax_properties: Dict[str, Any]
    
    # Computed properties
    is_visible: bool
    is_interactive: bool
    is_clickable: bool
    is_focusable: bool
    
    # Styling information
    computed_styles: Dict[str, str]
    paint_order: int
    
    # Action metadata
    action_type: str  # 'click', 'input', 'select', etc.
    confidence_score: float  # 0-1, how confident we are this is actionable

class BrowserDataMerger:
    """
    Merges DOM, DOMSnapshot, and Accessibility data into enhanced nodes
    """
    
    def __init__(self, viewport_width: int = 1280, viewport_height: int = 720):
        self.viewport_width = viewport_width
        self.viewport_height = viewport_height
        
    def merge_browser_data(self, dom_data: dict, snapshot_data: dict, 
                          ax_data: dict, metrics_data: dict) -> List[EnhancedNode]:
        """
        Main entry point: merge all CDP data sources into enhanced nodes
        """
        print("🔄 Starting browser data merge...")
        
        # Calculate device pixel ratio
        dpr = self._calculate_dpr(metrics_data)
        print(f"📏 Device Pixel Ratio: {dpr:.2f}")
        
        # Update viewport from metrics
        self._update_viewport_from_metrics(metrics_data)
        
        # Build lookup tables
        snapshot_lookup = self._build_snapshot_lookup(snapshot_data, dpr)
        ax_lookup = self._build_ax_lookup(ax_data)
        
        print(f"📊 Built lookups: {len(snapshot_lookup)} snapshot nodes, {len(ax_lookup)} AX nodes")
        
        # Extract DOM elements and merge with other data
        enhanced_nodes = []
        self._traverse_dom_and_merge(
            dom_data['root'], 
            snapshot_lookup, 
            ax_lookup, 
            enhanced_nodes
        )
        
        print(f"🌳 Extracted {len(enhanced_nodes)} total DOM elements")
        
        # Filter for actionable elements
        actionable_nodes = self._filter_actionable_elements(enhanced_nodes)
        print(f"✨ Filtered to {len(actionable_nodes)} actionable elements")
        
        return actionable_nodes
    
    def _calculate_dpr(self, metrics_data: dict) -> float:
        """Calculate device pixel ratio from metrics"""
        visual_viewport = metrics_data.get('visualViewport', {})
        css_viewport = metrics_data.get('cssVisualViewport', {})
        
        visual_width = visual_viewport.get('clientWidth', 1)
        css_width = css_viewport.get('clientWidth', 1)
        
        return visual_width / css_width if css_width > 0 else 1.0
    
    def _update_viewport_from_metrics(self, metrics_data: dict):
        """Update viewport dimensions from actual metrics"""
        css_viewport = metrics_data.get('cssVisualViewport', {})
        self.viewport_width = css_viewport.get('clientWidth', self.viewport_width)
        self.viewport_height = css_viewport.get('clientHeight', self.viewport_height)
    
    def _build_snapshot_lookup(self, snapshot_data: dict, dpr: float) -> Dict[int, dict]:
        """
        Build a lookup table: backend_node_id -> snapshot data (bounds, styles, etc.)
        """
        lookup = {}
        
        # Get the first document (main page)
        if not snapshot_data.get('documents'):
            return lookup
            
        doc = snapshot_data['documents'][0]
        nodes = doc.get('nodes', {})
        layout = doc.get('layout', {})
        
        # Extract parallel arrays
        backend_ids = nodes.get('backendNodeId', [])
        node_types = nodes.get('nodeType', [])
        node_names = nodes.get('nodeName', [])
        
        bounds = layout.get('bounds', [])
        styles = layout.get('styles', [])
        paint_orders = layout.get('paintOrders', [])
        
        # String tables for decoding
        strings = snapshot_data.get('strings', [])
        
        for i, backend_id in enumerate(backend_ids):
            if backend_id and i < len(bounds):
                # Convert device pixels to CSS pixels
                device_bounds = bounds[i]
                css_bounds = [coord / dpr for coord in device_bounds]
                
                # Decode node name
                node_name = ""
                if i < len(node_names) and node_names[i] >= 0 and node_names[i] < len(strings):
                    node_name = strings[node_names[i]]
                
                # Decode styles
                computed_styles = {}
                if i < len(styles):
                    style_indices = styles[i]
                    # Styles come in pairs: [property_index, value_index, ...]
                    for j in range(0, len(style_indices), 2):
                        if j + 1 < len(style_indices):
                            prop_idx = style_indices[j]
                            val_idx = style_indices[j + 1]
                            if (prop_idx >= 0 and prop_idx < len(strings) and 
                                val_idx >= 0 and val_idx < len(strings)):
                                computed_styles[strings[prop_idx]] = strings[val_idx]
                
                lookup[backend_id] = {
                    'bounds_css': css_bounds,
                    'node_type': node_types[i] if i < len(node_types) else 0,
                    'node_name': node_name,
                    'computed_styles': computed_styles,
                    'paint_order': paint_orders[i] if i < len(paint_orders) else 0
                }
        
        return lookup
    
    def _build_ax_lookup(self, ax_data: dict) -> Dict[int, dict]:
        """
        Build a lookup table: backend_node_id -> accessibility data
        """
        lookup = {}
        
        for node in ax_data.get('nodes', []):
            backend_id = node.get('backendDOMNodeId')
            if backend_id:
                role = node.get('role', {}).get('value', '')
                name = node.get('name', {}).get('value', '')
                
                # Extract properties
                properties = {}
                for prop in node.get('properties', []):
                    prop_name = prop.get('name')
                    prop_value = prop.get('value', {}).get('value')
                    if prop_name and prop_value is not None:
                        properties[prop_name] = prop_value
                
                lookup[backend_id] = {
                    'role': role,
                    'name': name,
                    'properties': properties
                }
        
        return lookup
    
    def _traverse_dom_and_merge(self, node: dict, snapshot_lookup: dict, 
                               ax_lookup: dict, enhanced_nodes: list):
        """
        Recursively traverse DOM tree and merge with snapshot/AX data
        """
        node_type = node.get('nodeType', 0)
        
        if node_type == 1:  # Element node
            backend_id = node.get('backendNodeId')
            if backend_id and backend_id in snapshot_lookup:
                enhanced_node = self._create_enhanced_node(
                    node, snapshot_lookup[backend_id], ax_lookup.get(backend_id, {})
                )
                if enhanced_node:
                    enhanced_nodes.append(enhanced_node)
        
        # Recurse into children
        for child in node.get('children', []):
            self._traverse_dom_and_merge(child, snapshot_lookup, ax_lookup, enhanced_nodes)
    
    def _create_enhanced_node(self, dom_node: dict, snapshot_data: dict, ax_data: dict) -> Optional[EnhancedNode]:
        """
        Create an enhanced node from merged data sources
        """
        backend_id = dom_node.get('backendNodeId')
        tag_name = dom_node.get('nodeName', '').lower()
        
        # Get bounds and calculate click point
        bounds_css = snapshot_data.get('bounds_css', [0, 0, 0, 0])
        x, y, width, height = bounds_css
        click_point = (x + width / 2, y + height / 2)
        
        # Extract DOM attributes
        attributes = {}
        attrs_list = dom_node.get('attributes', [])
        for i in range(0, len(attrs_list), 2):
            if i + 1 < len(attrs_list):
                attributes[attrs_list[i]] = attrs_list[i + 1]
        
        # Get text content from child text nodes
        text_content = self._extract_text_content(dom_node)
        
        # Get computed styles
        computed_styles = snapshot_data.get('computed_styles', {})
        
        # Determine visibility
        is_visible = self._is_element_visible(bounds_css, computed_styles)
        
        # Determine interactivity
        is_interactive = self._is_element_interactive(tag_name, attributes, ax_data)
        is_clickable = self._is_element_clickable(tag_name, attributes, ax_data, computed_styles)
        is_focusable = ax_data.get('properties', {}).get('focusable', False)
        
        # Determine action type
        action_type = self._determine_action_type(tag_name, attributes, ax_data)
        
        # Calculate confidence score
        confidence_score = self._calculate_confidence_score(
            is_visible, is_interactive, ax_data, bounds_css
        )
        
        return EnhancedNode(
            backend_node_id=backend_id,
            tag_name=tag_name,
            bounds_css=tuple(bounds_css),
            click_point=click_point,
            attributes=attributes,
            text_content=text_content,
            ax_role=ax_data.get('role', ''),
            ax_name=ax_data.get('name', ''),
            ax_properties=ax_data.get('properties', {}),
            is_visible=is_visible,
            is_interactive=is_interactive,
            is_clickable=is_clickable,
            is_focusable=is_focusable,
            computed_styles=computed_styles,
            paint_order=snapshot_data.get('paint_order', 0),
            action_type=action_type,
            confidence_score=confidence_score
        )
    
    def _extract_text_content(self, dom_node: dict) -> str:
        """Extract text content from DOM node and its children"""
        text_parts = []
        
        def collect_text(node):
            if node.get('nodeType') == 3:  # Text node
                text = node.get('nodeValue', '').strip()
                if text:
                    text_parts.append(text)
            
            for child in node.get('children', []):
                collect_text(child)
        
        collect_text(dom_node)
        return ' '.join(text_parts)
    
    def _is_element_visible(self, bounds_css: list, computed_styles: dict) -> bool:
        """
        Determine if element is visible based on bounds and CSS properties
        """
        x, y, width, height = bounds_css
        
        # Check basic bounds
        if width <= 0 or height <= 0:
            return False
        
        # Check if element is within viewport (with some tolerance for scroll)
        if x > self.viewport_width + 100 or y > self.viewport_height + 100:
            return False
        
        # Check CSS visibility properties
        display = computed_styles.get('display', '')
        visibility = computed_styles.get('visibility', '')
        opacity = computed_styles.get('opacity', '1')
        
        if display == 'none' or visibility == 'hidden':
            return False
        
        try:
            if float(opacity) < 0.1:
                return False
        except (ValueError, TypeError):
            pass
        
        return True
    
    def _is_element_interactive(self, tag_name: str, attributes: dict, ax_data: dict) -> bool:
        """
        Determine if element is interactive based on multiple signals
        """
        # HTML semantic interactivity
        interactive_tags = {'button', 'a', 'input', 'select', 'textarea', 'details', 'summary'}
        if tag_name in interactive_tags:
            return True
        
        # Event handlers
        event_attrs = {'onclick', 'onmousedown', 'onmouseup', 'onkeydown', 'onkeyup'}
        if any(attr in attributes for attr in event_attrs):
            return True
        
        # ARIA roles
        role = attributes.get('role', '').lower()
        interactive_roles = {'button', 'link', 'textbox', 'combobox', 'checkbox', 'radio', 'tab', 'menuitem'}
        if role in interactive_roles:
            return True
        
        # Accessibility tree signals
        ax_role = ax_data.get('role', '').lower()
        if ax_role in interactive_roles:
            return True
        
        # Focusable elements are generally interactive
        if ax_data.get('properties', {}).get('focusable'):
            return True
        
        return False
    
    def _is_element_clickable(self, tag_name: str, attributes: dict, ax_data: dict, computed_styles: dict) -> bool:
        """
        Determine if element is clickable (subset of interactive)
        """
        # Must be interactive first
        if not self._is_element_interactive(tag_name, attributes, ax_data):
            return False
        
        # Check for disabled state
        if attributes.get('disabled') == 'true' or attributes.get('disabled') == '':
            return False
        
        if ax_data.get('properties', {}).get('disabled'):
            return False
        
        # Check CSS cursor (strong signal for clickability)
        cursor = computed_styles.get('cursor', '')
        if cursor == 'pointer':
            return True
        
        # Check pointer events
        pointer_events = computed_styles.get('pointer-events', '')
        if pointer_events == 'none':
            return False
        
        # Specific tag-based rules
        if tag_name in {'button', 'a'}:
            return True
        
        if tag_name == 'input':
            input_type = attributes.get('type', 'text').lower()
            return input_type in {'button', 'submit', 'reset', 'checkbox', 'radio'}
        
        return True
    
    def _determine_action_type(self, tag_name: str, attributes: dict, ax_data: dict) -> str:
        """
        Determine what type of action this element supports
        """
        # Input elements
        if tag_name == 'input':
            input_type = attributes.get('type', 'text').lower()
            if input_type in {'text', 'email', 'password', 'search', 'url', 'tel'}:
                return 'input'
            elif input_type in {'checkbox', 'radio'}:
                return 'toggle'
            elif input_type in {'button', 'submit', 'reset'}:
                return 'click'
        
        if tag_name in {'textarea'}:
            return 'input'
        
        if tag_name == 'select':
            return 'select'
        
        # Accessibility role-based
        ax_role = ax_data.get('role', '').lower()
        if ax_role in {'textbox', 'searchbox'}:
            return 'input'
        elif ax_role in {'combobox', 'listbox'}:
            return 'select'
        elif ax_role in {'checkbox', 'radio', 'switch'}:
            return 'toggle'
        
        # Default to click for interactive elements
        return 'click'
    
    def _calculate_confidence_score(self, is_visible: bool, is_interactive: bool, 
                                  ax_data: dict, bounds_css: list) -> float:
        """
        Calculate confidence score (0-1) for how actionable this element is
        """
        score = 0.0
        
        # Base score for visibility and interactivity
        if is_visible:
            score += 0.3
        if is_interactive:
            score += 0.3
        
        # Accessibility data boosts confidence
        if ax_data.get('role'):
            score += 0.2
        if ax_data.get('name'):
            score += 0.1
        if ax_data.get('properties', {}).get('focusable'):
            score += 0.1
        
        # Size-based confidence (very small elements are suspicious)
        width, height = bounds_css[2], bounds_css[3]
        if width >= 10 and height >= 10:
            score += 0.1
        elif width < 5 or height < 5:
            score -= 0.2
        
        return max(0.0, min(1.0, score))
    
    def _filter_actionable_elements(self, enhanced_nodes: List[EnhancedNode]) -> List[EnhancedNode]:
        """
        Filter enhanced nodes to only actionable elements
        """
        actionable = []
        
        for node in enhanced_nodes:
            # Basic filters
            if not node.is_visible:
                continue
            
            if not node.is_interactive:
                continue
            
            # Confidence threshold
            if node.confidence_score < 0.3:
                continue
            
            # Size filters (avoid tiny decorative elements)
            width, height = node.bounds_css[2], node.bounds_css[3]
            if width < 3 or height < 3:
                continue
            
            actionable.append(node)
        
        # Sort by confidence score (highest first)
        actionable.sort(key=lambda x: x.confidence_score, reverse=True)
        
        return actionable

