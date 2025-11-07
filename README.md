# Browser Agent

A high-performance browser automation library that transforms raw Chrome DevTools Protocol (CDP) data into actionable elements for LLM-driven browser interaction.

## Features

- **Intelligent Element Detection**: Correlates DOM, DOMSnapshot, and Accessibility data to identify truly interactive elements
- **Precise Coordinate Calculation**: Handles device pixel ratio conversion for accurate click targeting
- **Confidence Scoring**: Ranks elements by actionability confidence (0-1 scale)
- **Visibility Filtering**: Removes hidden, occluded, and non-interactive elements
- **Action Type Classification**: Categorizes elements as click, input, select, or toggle actions

## Quick Start

### Prerequisites

- Chrome/Chromium browser
- Python 3.12+

### Installation

```bash
# Clone the repository
git clone <your-repo-url>
cd browser-agent

# Install dependencies
pip install -e .
```

### Basic Usage

1. **Start Chrome with debugging enabled:**
```bash
python launch_chrome.py
```

2. **Extract actionable elements from a webpage:**
```python
import asyncio
from cdp import get_enhanced_elements

async def main():
    elements = await get_enhanced_elements("https://example.com")
    
    for element in elements:
        print(f"{element.tag_name}: '{element.ax_name}'")
        print(f"  Click at: {element.click_point}")
        print(f"  Confidence: {element.confidence_score:.2f}")

asyncio.run(main())
```

## Architecture

### Core Components

- **`CDPClient`**: WebSocket client for Chrome DevTools Protocol communication
- **`BrowserDataMerger`**: Correlates and processes DOM, snapshot, and accessibility data
- **`EnhancedNode`**: Unified representation of actionable browser elements

### Data Flow

1. **Collection**: Gather DOM tree, DOMSnapshot, Accessibility tree, and layout metrics
2. **Correlation**: Match elements across data sources using `backendNodeId`
3. **Enhancement**: Calculate positions, visibility, interactivity, and confidence scores
4. **Filtering**: Remove non-actionable elements and sort by confidence

## API Reference

### `get_enhanced_elements(url: str) -> List[EnhancedNode]`

Returns a list of actionable elements from the specified webpage.

### `EnhancedNode` Properties

```python
@dataclass
class EnhancedNode:
    backend_node_id: int              # Stable element identifier
    tag_name: str                     # HTML tag name
    bounds_css: Tuple[float, ...]     # Element bounds in CSS pixels
    click_point: Tuple[float, float]  # Optimal click coordinates
    attributes: Dict[str, str]        # HTML attributes
    text_content: str                 # Visible text content
    ax_role: Optional[str]            # Accessibility role
    ax_name: str                      # Accessible name
    is_visible: bool                  # Element visibility
    is_interactive: bool              # Element interactivity
    is_clickable: bool                # Element clickability
    action_type: str                  # Action type (click/input/select/toggle)
    confidence_score: float           # Actionability confidence (0-1)
```

## Configuration

### Viewport Settings

```python
merger = BrowserDataMerger(viewport_width=1920, viewport_height=1080)
```

### Confidence Thresholds

Elements are filtered with a minimum confidence score of 0.3. Adjust in `_filter_actionable_elements()`.

## Development

### Project Structure

```
browser-agent/
├── cdp.py              # CDP client and main interface
├── enhanced_merger.py  # Core data processing logic
├── dom/
│   └── main.py        # DOM data collection
├── launch_chrome.py   # Chrome launcher utility
└── pyproject.toml     # Project configuration
```

### Running Tests

```bash
# Test with a live webpage
python cdp.py
```

## Technical Details

### Coordinate Systems

- **Device Pixels**: Raw coordinates from DOMSnapshot (affected by zoom/DPI)
- **CSS Pixels**: Converted coordinates for accurate interaction
- **Conversion**: `css_pixels = device_pixels / device_pixel_ratio`

### Element Detection Logic

1. **HTML Semantics**: `button`, `a`, `input`, `select`, `textarea`
2. **Event Handlers**: `onclick`, `onmousedown`, etc.
3. **ARIA Roles**: `button`, `link`, `textbox`, `combobox`
4. **Accessibility Properties**: `focusable`, `pressed`, `disabled`
5. **CSS Properties**: `cursor: pointer`, `pointer-events: none`

### Confidence Scoring

- **Base Score**: Visibility (0.3) + Interactivity (0.3)
- **Accessibility Bonus**: Role (+0.2), Name (+0.1), Focusable (+0.1)
- **Size Penalty**: Elements < 5px width/height (-0.2)

## License

MIT License - see LICENSE file for details.

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests if applicable
5. Submit a pull request

## Troubleshooting

### Chrome Connection Issues

- Ensure Chrome is running: `python launch_chrome.py`
- Check port 9222 is available
- Verify Chrome launched with `--remote-debugging-port=9222`

### No Elements Found

- Check if page has loaded completely (increase sleep time)
- Verify elements are actually interactive (not decorative)
- Lower confidence threshold if needed

### Coordinate Accuracy

- Ensure proper device pixel ratio handling
- Check viewport dimensions match browser window
- Verify elements are within viewport bounds
