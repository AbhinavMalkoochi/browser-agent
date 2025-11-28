"""
Enhanced Node Merger - Transforms raw CDP data into actionable browser elements.
"""

from dataclasses import dataclass
from typing import List, Dict, Optional, Tuple, Any

# P2-23: Module-level constants for interactive element detection
INTERACTIVE_TAGS = frozenset({
    'button', 'a', 'input', 'select', 'textarea', 'details', 'summary'
})

INTERACTIVE_ROLES = frozenset({
    'button', 'link', 'textbox', 'combobox', 'checkbox', 'radio', 
    'tab', 'menuitem', 'option', 'switch', 'searchbox', 'listbox'
})

EVENT_ATTRS = frozenset({
    'onclick', 'onmousedown', 'onmouseup', 'onkeydown', 'onkeyup'
})

INPUT_TYPES_TEXT = frozenset({
    'text', 'email', 'password', 'search', 'url', 'tel'
})

INPUT_TYPES_TOGGLE = frozenset({
    'checkbox', 'radio'
})

INPUT_TYPES_CLICK = frozenset({
    'button', 'submit', 'reset'
})

@dataclass
class EnhancedNode:
    """Unified representation of a browser element with action metadata."""
    backend_node_id: int
    tag_name: str
    bounds_css: Tuple[float, float, float, float]  # x, y, width, height
    click_point: Tuple[float, float]
    attributes: Dict[str, str]
    text_content: str
    ax_role: Optional[str]
    ax_name: str
    ax_properties: Dict[str, Any]
    is_visible: bool
    is_interactive: bool
    is_clickable: bool
    is_focusable: bool
    is_occluded: bool  # New field for occlusion
    computed_styles: Dict[str, str]
    paint_order: int
    action_type: str
    confidence_score: float
    frame_id: Optional[str] = None

class BrowserDataMerger:
    """Merges DOM, DOMSnapshot, and Accessibility data into enhanced nodes."""
    
    def __init__(self, viewport_width: int = 1280, viewport_height: int = 720):
        self.viewport_width = viewport_width
        self.viewport_height = viewport_height
        
    def merge_browser_data(self, dom_data: dict, snapshot_data: dict, 
                          ax_data: dict, metrics_data: dict) -> List[EnhancedNode]:
        """Main entry point: merge all CDP data sources into enhanced nodes."""
        dpr = self._calculate_dpr(metrics_data)
        self._update_viewport_from_metrics(metrics_data)
        
        # 1. Build Lookups
        snapshot_lookup = self._build_snapshot_lookup(snapshot_data, dpr)
        ax_lookup = self._build_ax_lookup(ax_data)
        
        # 2. Traverse and Create Nodes
        enhanced_nodes = []
        if 'root' in dom_data:
            self._traverse_dom_and_merge(
                dom_data['root'], 
                snapshot_lookup, 
                ax_lookup, 
                enhanced_nodes
            )
        
        # 3. Apply Occlusion Detection (Z-Index/Paint Order check)
        self._apply_occlusion_detection(enhanced_nodes)
        
        # 4. Filter and Sort
        return self._filter_actionable_elements(enhanced_nodes)
    
    def _calculate_dpr(self, metrics_data: dict) -> float:
        visual_viewport = metrics_data.get('visualViewport', {})
        css_viewport = metrics_data.get('cssVisualViewport', {})
        visual_width = visual_viewport.get('clientWidth', 1)
        css_width = css_viewport.get('clientWidth', 1)
        return visual_width / css_width if css_width > 0 else 1.0
    
    def _update_viewport_from_metrics(self, metrics_data: dict):
        css_viewport = metrics_data.get('cssVisualViewport', {})
        self.viewport_width = css_viewport.get('clientWidth', self.viewport_width)
        self.viewport_height = css_viewport.get('clientHeight', self.viewport_height)
    
    def _build_snapshot_lookup(self, snapshot_data: dict, dpr: float) -> Dict[int, dict]:
        """
        Build a lookup table: backend_node_id -> snapshot data.
        FIX: Iterates over ALL documents (main frame + iframes) in the snapshot.
        """
        lookup = {}
        strings = snapshot_data.get('strings', [])
        
        # Iterate over all documents (Main frame is index 0, iframes are subsequent)
        documents = snapshot_data.get('documents', [])
        
        for doc in documents:
            nodes = doc.get('nodes', {})
            layout = doc.get('layout', {})
            
            backend_ids = nodes.get('backendNodeId', [])
            node_types = nodes.get('nodeType', [])
            node_names = nodes.get('nodeName', [])
            
            bounds = layout.get('bounds', [])
            styles = layout.get('styles', [])
            paint_orders = layout.get('paintOrders', [])
            
            for i, backend_id in enumerate(backend_ids):
                if backend_id and i < len(bounds):
                    # CDP Snapshot bounds are usually viewport-relative already
                    device_bounds = bounds[i]
                    css_bounds = [coord / dpr for coord in device_bounds]
                    
                    node_name = ""
                    if i < len(node_names) and 0 <= node_names[i] < len(strings):
                        node_name = strings[node_names[i]]
                    
                    computed_styles = {}
                    if i < len(styles):
                        style_indices = styles[i]
                        for j in range(0, len(style_indices), 2):
                            if j + 1 < len(style_indices):
                                prop_idx = style_indices[j]
                                val_idx = style_indices[j + 1]
                                if (0 <= prop_idx < len(strings) and 
                                    0 <= val_idx < len(strings)):
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
        lookup = {}
        for node in ax_data.get('nodes', []):
            backend_id = node.get('backendDOMNodeId')
            if backend_id:
                role = node.get('role', {}).get('value', '')
                name = node.get('name', {}).get('value', '')
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
    
    def _traverse_dom_and_merge(self, root_node: dict, snapshot_lookup: dict, 
                               ax_lookup: dict, enhanced_nodes: list, frame_id: str = None):
        """
        Iteratively traverse DOM tree and merge with snapshot/AX data.
        
        Uses a stack-based approach instead of recursion to avoid hitting
        Python's recursion limit on deep DOM trees (P0-5).
        """
        # Stack holds tuples of (node, frame_id)
        stack = [(root_node, frame_id)]
        
        while stack:
            node, current_frame_id = stack.pop()
            
            # Update frame_id if we encounter a frame owner
            if node.get('frameId'):
                current_frame_id = node.get('frameId')

            node_type = node.get('nodeType', 0)
            
            if node_type == 1:  # Element node
                backend_id = node.get('backendNodeId')
                if backend_id and backend_id in snapshot_lookup:
                    enhanced_node = self._create_enhanced_node(
                        node, snapshot_lookup[backend_id], ax_lookup.get(backend_id, {}), current_frame_id
                    )
                    if enhanced_node:
                        enhanced_nodes.append(enhanced_node)
            
            # Add children to stack in reverse order to maintain traversal order
            children = node.get('children', [])
            for child in reversed(children):
                stack.append((child, current_frame_id))
            
            # Handle contentDocument (Iframes/Frames)
            if 'contentDocument' in node:
                stack.append((node['contentDocument'], current_frame_id))
            
            # Handle Shadow Roots
            if 'shadowRoots' in node:
                for root in reversed(node['shadowRoots']):
                    stack.append((root, current_frame_id))

    def _create_enhanced_node(self, dom_node: dict, snapshot_data: dict, ax_data: dict, frame_id: str) -> Optional[EnhancedNode]:
        backend_id = dom_node.get('backendNodeId')
        tag_name = dom_node.get('nodeName', '').lower()
        
        bounds_css = snapshot_data.get('bounds_css', [0, 0, 0, 0])
        x, y, width, height = bounds_css
        click_point = (x + width / 2, y + height / 2)
        
        attributes = {}
        attrs_list = dom_node.get('attributes', [])
        for i in range(0, len(attrs_list), 2):
            if i + 1 < len(attrs_list):
                attributes[attrs_list[i]] = attrs_list[i + 1]
        
        text_content = self._extract_text_content(dom_node)
        computed_styles = snapshot_data.get('computed_styles', {})
        
        is_visible = self._is_element_visible(bounds_css, computed_styles)
        is_interactive = self._is_element_interactive(tag_name, attributes, ax_data, computed_styles)
        is_clickable = self._is_element_clickable(tag_name, attributes, ax_data, computed_styles)
        is_focusable = ax_data.get('properties', {}).get('focusable', False)
        
        action_type = self._determine_action_type(tag_name, attributes, ax_data)
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
            is_occluded=False, # Will be calculated later
            computed_styles=computed_styles,
            paint_order=snapshot_data.get('paint_order', 0),
            action_type=action_type,
            confidence_score=confidence_score,
            frame_id=frame_id
        )

    def _apply_occlusion_detection(self, nodes: List[EnhancedNode]):
        """
        Detects if elements are covered by other elements using Paint Order.
        
        P1-13: Improved to check intersection area and respect pointer-events: none.
        This is an O(N^2) operation on the node list, but N is usually small (<500).
        """
        # Sort by paint order descending (top-most elements first)
        # We only care about visible elements for occlusion logic
        visible_nodes = [n for n in nodes if n.is_visible and n.bounds_css[2] > 0 and n.bounds_css[3] > 0]
        
        # Sort so we can iterate efficiently. 
        # Higher paint_order means it is drawn ON TOP.
        sorted_by_paint = sorted(visible_nodes, key=lambda x: x.paint_order, reverse=True)
        
        for target_node in nodes:
            if not target_node.is_visible:
                continue
            
            tx, ty, tw, th = target_node.bounds_css
            target_area = tw * th
            if target_area <= 0:
                continue
                
            # Check against all nodes that are painted AFTER (on top of) the target
            for obstacle in sorted_by_paint:
                # If we reached the target node itself or a layer below it, stop checking
                if obstacle.paint_order <= target_node.paint_order:
                    break
                
                # P1-13: Skip obstacles with pointer-events: none (they don't block clicks)
                if obstacle.computed_styles.get('pointer-events') == 'none':
                    continue
                
                # Skip transparent obstacles (opacity < 0.1)
                try:
                    opacity = float(obstacle.computed_styles.get('opacity', '1'))
                    if opacity < 0.1:
                        continue
                except (ValueError, TypeError):
                    pass
                
                ox, oy, owidth, oheight = obstacle.bounds_css
                
                # P1-13: Calculate intersection area instead of just center point
                # This prevents false negatives where element is 90% covered but center is visible
                ix = max(tx, ox)
                iy = max(ty, oy)
                ix2 = min(tx + tw, ox + owidth)
                iy2 = min(ty + th, oy + oheight)
                
                if ix < ix2 and iy < iy2:
                    intersection_area = (ix2 - ix) * (iy2 - iy)
                    coverage_ratio = intersection_area / target_area
                    
                    # Consider occluded if >90% covered
                    if coverage_ratio > 0.9:
                        target_node.is_occluded = True
                        target_node.is_clickable = False
                        target_node.confidence_score *= 0.1
                        break
                    # Partial occlusion penalty
                    elif coverage_ratio > 0.5:
                        target_node.confidence_score *= (1 - coverage_ratio * 0.5)

    def _extract_text_content(self, dom_node: dict) -> str:
        text_parts = []
        def collect_text(node):
            if node.get('nodeType') == 3:
                text = node.get('nodeValue', '').strip()
                if text:
                    text_parts.append(text)
            for child in node.get('children', []):
                collect_text(child)
        collect_text(dom_node)
        return ' '.join(text_parts)
    
    def _is_element_visible(self, bounds_css: list, computed_styles: dict) -> bool:
        x, y, width, height = bounds_css
        
        if width < 1 or height < 1: # Stricter size check
            return False
        
        # Check if completely off-screen
        if x > self.viewport_width or y > self.viewport_height:
            return False
        if x + width < 0 or y + height < 0:
            return False
            
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
    
    def _is_element_interactive(self, tag_name: str, attributes: dict, ax_data: dict, 
                                  computed_styles: dict = None) -> bool:
        """
        Determine if an element is interactive.
        
        P1-12: Enhanced to better detect modern framework elements (React, Vue, etc.)
        by relying more on computed styles rather than just inline event attributes.
        """
        computed_styles = computed_styles or {}
        
        # Check computed styles first (P1-12: Trust cursor: pointer for React/Vue elements)
        cursor = computed_styles.get('cursor', '')
        if cursor == 'pointer':
            return True
        
        # Check if pointer-events: none (definitely not interactive)
        pointer_events = computed_styles.get('pointer-events', '')
        if pointer_events == 'none':
            return False
        
        # Use module-level constants (P2-23)
        if tag_name in INTERACTIVE_TAGS:
            return True
        
        if any(attr in attributes for attr in EVENT_ATTRS):
            return True
        
        role = attributes.get('role', '').lower()
        if role in INTERACTIVE_ROLES:
            return True
        
        ax_role = ax_data.get('role', '').lower()
        if ax_role in INTERACTIVE_ROLES:
            return True
        
        if ax_data.get('properties', {}).get('focusable'):
            return True
        
        # Check for tabindex (makes element focusable/interactive)
        tabindex = attributes.get('tabindex', '')
        if tabindex and tabindex != '-1':
            return True
        
        return False
    
    def _is_element_clickable(self, tag_name: str, attributes: dict, ax_data: dict, computed_styles: dict) -> bool:
        if not self._is_element_interactive(tag_name, attributes, ax_data):
            return False
        
        if attributes.get('disabled') == 'true' or attributes.get('disabled') == '':
            return False
        
        if ax_data.get('properties', {}).get('disabled'):
            return False
        
        cursor = computed_styles.get('cursor', '')
        if cursor == 'pointer':
            return True
        
        pointer_events = computed_styles.get('pointer-events', '')
        if pointer_events == 'none':
            return False
        
        if tag_name in {'button', 'a'}:
            return True
        
        if tag_name == 'input':
            input_type = attributes.get('type', 'text').lower()
            return input_type in {'button', 'submit', 'reset', 'checkbox', 'radio'}
        
        return True
    
    def _determine_action_type(self, tag_name: str, attributes: dict, ax_data: dict) -> str:
        # Use module-level constants (P2-23)
        if tag_name == 'input':
            input_type = attributes.get('type', 'text').lower()
            if input_type in INPUT_TYPES_TEXT:
                return 'input'
            elif input_type in INPUT_TYPES_TOGGLE:
                return 'toggle'
            elif input_type in INPUT_TYPES_CLICK:
                return 'click'
        
        if tag_name == 'textarea':
            return 'input'
        
        if tag_name == 'select':
            return 'select'
        
        ax_role = ax_data.get('role', '').lower()
        if ax_role in {'textbox', 'searchbox'}:
            return 'input'
        elif ax_role in {'combobox', 'listbox'}:
            return 'select'
        elif ax_role in {'checkbox', 'radio', 'switch'}:
            return 'toggle'
        
        return 'click'
    
    def _calculate_confidence_score(self, is_visible: bool, is_interactive: bool, 
                                  ax_data: dict, bounds_css: list) -> float:
        score = 0.0
        
        if is_visible:
            score += 0.3
        if is_interactive:
            score += 0.3
        
        if ax_data.get('role'):
            score += 0.2
        if ax_data.get('name'):
            score += 0.1
        if ax_data.get('properties', {}).get('focusable'):
            score += 0.1
        
        width, height = bounds_css[2], bounds_css[3]
        if width >= 10 and height >= 10:
            score += 0.1
        elif width < 5 or height < 5:
            score -= 0.2
        
        return max(0.0, min(1.0, score))
    
    def _filter_actionable_elements(self, enhanced_nodes: List[EnhancedNode]) -> List[EnhancedNode]:
        actionable = []
        
        for node in enhanced_nodes:
            # Filter out occluded or invisible nodes
            if not node.is_visible or node.is_occluded:
                continue
            
            if not node.is_interactive:
                continue
            
            if node.confidence_score < 0.3:
                continue
            
            width, height = node.bounds_css[2], node.bounds_css[3]
            if width < 3 or height < 3:
                continue
            
            actionable.append(node)
        
        actionable.sort(key=lambda x: x.confidence_score, reverse=True)
        return actionable