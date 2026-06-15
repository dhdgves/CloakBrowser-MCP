"""
MCP Server — Exposes CloakBrowser as a persistent browser agent via MCP tools.

Run with: python mcp_server.py
Uses stdio transport for MCP protocol.
"""

import base64
import math
import threading
from io import BytesIO
from PIL import Image

from mcp.server.fastmcp import FastMCP
from browser_manager import BrowserManager

# ---------------------------------------------------------------------------
# MCP Server
# ---------------------------------------------------------------------------
mcp = FastMCP(
    name="browser-agent",
    instructions="""Persistent browser agent powered by CloakBrowser.
You have full control over a headed (user-visible) Chromium browser.
The browser stays alive across tool calls until explicitly closed.
All interactions are human-like (mouse movement, typing, scrolling).

Core workflow:
  1. launch_browser → open the browser window
  2. navigate(url)  → load a page (returns title + URL)
  3. snapshot()     → understand page via accessibility tree with [ref] IDs
  4. click_ref(n)   → click by snapshot ref (works everywhere, including Shadow DOM)
  5. type_text()    → fill in text fields
  6. press_key()    → Enter, Escape, etc.
  7. screenshot()   → verify result visually
  8. close_browser  → clean up

Available tools (13 total):
- Lifecycle:   launch_browser, close_browser
- Navigation:  navigate (returns title + URL)
- Reading:     snapshot (CDP a11y tree with [ref] IDs), execute_js (fallback)
- Interact:    click_ref (via [ref] — recommended), type_text, press_key, drag (slider)
- Visual:      screenshot (base64 JPEG, optional return_path)
- Tabs:        list_pages, switch_page
- Misc:        scroll"""
)

# Lazy singleton — created on first use so test patches work
_bm_instance = None
_bm_lock = threading.Lock()
_snapshot_cache = {}  # ref_id -> backend info (populated by snapshot(), used by click_ref())


def _get_bm() -> BrowserManager:
    """Get or create the BrowserManager singleton lazily."""
    global _bm_instance
    if _bm_instance is None:
        with _bm_lock:
            if _bm_instance is None:
                _bm_instance = BrowserManager()
    return _bm_instance


# ---------------------------------------------------------------------------
# Tool: Launch / Lifecycle
# ---------------------------------------------------------------------------
@mcp.tool()
async def launch_browser() -> str:
    """Launch the persistent browser window (headed mode, human-like). Returns status."""
    try:
        bm = _get_bm()
        page = await bm.ensure_browser()
        title = await page.title()
        return f"Browser launched successfully. Current page title: '{title}'"
    except Exception as e:
        return f"Error launching browser: {str(e)}"


@mcp.tool()
async def close_browser() -> str:
    """Close the browser and clean up resources."""
    try:
        bm = _get_bm()
        await bm.close()
        return "Browser closed successfully"
    except Exception as e:
        return f"Error closing browser: {str(e)}"


# ---------------------------------------------------------------------------
# Tool: Navigation
# ---------------------------------------------------------------------------
@mcp.tool()
async def navigate(url: str) -> str:
    """Navigate to a URL. Returns page title and URL.

    This replaces get_current_url and get_page_title — both values are returned here.
    """
    try:
        bm = _get_bm()
        page = await bm.get_page()
        await page.goto(url)
        title = await page.title()
        return f"OK: {title}\nURL: {page.url}"
    except Exception as e:
        return f"Error navigating to {url}: {str(e)}"


# ---------------------------------------------------------------------------
# Tool: Snapshot — CDP accessibility tree (primary page reading tool)
# ---------------------------------------------------------------------------
@mcp.tool()
async def snapshot(mode: str = "compact", max_items: int = 80) -> str:
    """Take a structured snapshot using Chrome's CDP accessibility tree.
    
    The PRIMARY way to understand a page. Each interactive element gets a [ref] ID
    that can be used with click_ref() to click it, including inside Shadow DOM.
    
    Two modes:
      "compact" (default): Only interactive elements (buttons, links, inputs, etc.)
                           — minimal LLM token usage, shows what you can act on.
      "full":              All visible nodes including text (StaticText, etc.)
    
    Workflow: snapshot() → LLM picks ref → click_ref(ref)
    
    Args:
        mode: "compact" (default) or "full".
        max_items: Max lines to display (default 80).
    """
    return await _snapshot(mode, max_items)


async def _snapshot(mode: str = "compact", max_items: int = 80) -> str:
    """Internal: take snapshot and return output string. Callable from both
    the MCP snapshot tool and from click_ref for auto-snapshot."""
    try:
        bm = _get_bm()
        page = await bm.get_page()
        cdp = await page.context.new_cdp_session(page)

        # Enable accessibility — required for getFullAXTree
        await cdp.send('Accessibility.enable')
        result = await cdp.send('Accessibility.getFullAXTree')
        all_nodes = result.get('nodes', [])

        clickable_roles = {'button', 'link', 'menuitem', 'tab', 'checkbox',
                          'radio', 'switch', 'combobox', 'searchbox', 'textbox',
                          'spinbutton', 'slider', 'listbox', 'treeitem', 'colorwell',
                          'heading'}
        
        # Non-interactive text roles — folded in compact mode
        text_roles = {'StaticText', 'InlineTextBox', 'LabelText', 'generic'}

        nodes_out = []
        click_counter = 0
        total_node_count = 0
        global _snapshot_cache
        _snapshot_cache = {}

        for node in all_nodes:
            if node.get('ignored', False):
                continue

            role_full = node.get('role', {}) or {}
            role = role_full.get('value', 'unknown')
            name = (node.get('name', {}) or {}).get('value', '') or ''
            name = name.replace('\\n', ' ').replace('\\r', '').strip()[:60]
            backend_id = node.get('backendDOMNodeId', 0)
            child_ids = node.get('childIds', [])
            total_node_count += 1

            # Skip invisible text-only elements in compact mode
            if mode == "compact" and role in text_roles:
                continue

            if not name and role not in clickable_roles:
                continue

            is_clickable = role in clickable_roles and bool(name.strip())
            if is_clickable:
                _snapshot_cache[click_counter] = {
                    'backendId': backend_id,
                    'nodeId': node.get('nodeId', ''),
                    'role': role,
                }
                ref_str = f"[{click_counter:>3}]"
                click_counter += 1
            else:
                ref_str = "     "

            has_children = bool(child_ids)
            marker = "+" if has_children else " "
            nodes_out.append(f"  {ref_str} <{role}{marker}> {name}")

        nodes_out = nodes_out[:max_items]

        try:
            await cdp.send('Accessibility.disable')
        except Exception:
            pass

        total_clickable = click_counter
        
        # Build header with context info
        shown_count = len(nodes_out)
        hidden_count = max(0, total_node_count - shown_count)
        
        lines = ['=== Page Snapshot (CDP accessibility tree) ===']
        
        if mode == "compact":
            lines.append(f'--- Interactive elements ({total_clickable} clickable). '
                         f'Use click_ref(ref) to click. ---')
        else:
            lines.append(f'--- All visible nodes (showing {shown_count}/{total_node_count} total. '
                         f'{total_clickable} clickable. click_ref(ref) to click.) ---')
        
        if hidden_count > 0:
            lines.append(f'--- ({hidden_count} nodes hidden, try mode="full" or increase max_items) ---')
        
        lines.append('')
        lines.extend(nodes_out)
        lines.append('')
        lines.append(f'--- {total_clickable} clickable elements. Use click_ref(ref) to click the one you need. ---')
        return '\n'.join(lines)
    except Exception as e:
        return f"Error taking snapshot: {str(e)}"


# ---------------------------------------------------------------------------
# Tool: Clicking (single entry via CDP coordinate click)
# ---------------------------------------------------------------------------
@mcp.tool()
async def click_ref(ref: int) -> str:
    """Click an element by its [ref] ID from snapshot().
    
    This is the ONLY click tool — use it for ALL clicking needs:
      - Regular buttons, links, inputs
      - Elements inside Shadow DOM (CDP coordinates work at all depths)
      - Elements that require precise positioning
    
    Always call snapshot() first to get the [ref] IDs, then click_ref(ref).
    
    After clicking, the tool detects side effects:
      - If a new tab opens → auto-switches and reports it
      - If the page URL changes → reports the new URL
      - If any side effect is detected → automatically runs snapshot()
        and includes the result so the LLM immediately sees the new page state.
    
    Uses CDP to find the element's bounding box and dispatch a mouse click.
    
    Args:
        ref: The [ref] number from the most recent snapshot() output.
    """
    global _snapshot_cache
    try:
        bm = _get_bm()
        page = await bm.get_page()
        entry = _snapshot_cache.get(ref)
        if not entry:
            return f"Error: ref [{ref}] not found. Call snapshot() first to refresh refs (page may have changed)."

        backend_id = entry.get('backendId')
        if not backend_id or backend_id == 0:
            return f"Error: ref [{ref}] has no backend DOM node."

        cdp = await page.context.new_cdp_session(page)

        # Get the element's bounding quads via CDP
        quads = await cdp.send('DOM.getContentQuads', {
            'backendNodeId': backend_id
        })
        quads_list = quads.get('quads', [])
        if not quads_list:
            return f"Error: ref [{ref}] element not visible."

        # Compute center of the first quad (page/document coordinates)
        q = quads_list[0]
        xs = q[0::2]
        ys = q[1::2]
        cx_page = sum(xs) / len(xs)
        cy_page = sum(ys) / len(ys)

        # Scroll element into view so mouse events land correctly.
        # DOM.getContentQuads returns page coordinates, but Playwright's
        # mouse.* methods work in viewport coordinates. Without adjustment,
        # clicks miss when the page is scrolled.
        await page.evaluate(f'window.scrollTo(0, {cy_page - 300})')

        # Read scroll offset AFTER scrolling
        scroll_y = await page.evaluate('window.scrollY')
        scroll_x = await page.evaluate('window.scrollX')

        # Convert page coordinates → viewport coordinates
        cx = cx_page - scroll_x
        cy = cy_page - scroll_y

        context = page.context
        import asyncio
        role = entry.get('role', '?')
        effect = {'type': None}  # mutable container for nonlocal-like access

        # Capture page state BEFORE click (object identity set for reliable diff,
        # plus count-based baseline).  This is done before Bézier movement so we
        # don't miss pages created synchronously during CDP mousePressed/release.
        pages_before = set(context.pages)
        url_before = page.url

        # ------------------------------------------------------------------
        # Single CDP humanized click — replaces two-phase design
        # Sends Bézier mouse movement + full mousePressed/mouseReleased
        # sequence via CDP, which gives us both:
        #   - Human-like trajectory (stealth)
        #   - Complete event sequence → React recognizes the click
        # ------------------------------------------------------------------

        # 1. Humanized Bézier mouse movement to target
        #    (random steps, smooth easing — anti-detection)
        steps = max(8, min(20, int(math.hypot(cx, cy) / 30)))
        start_x, start_y = await page.evaluate(
            '[window.scrollX + innerWidth/2, window.scrollY + innerHeight/2]')
        for i in range(1, steps + 1):
            t = i / steps
            ease = t * t * (3 - 2 * t)  # smoothstep
            cur_x = start_x + (cx - start_x) * ease
            cur_y = start_y + (cy - start_y) * ease
            await cdp.send('Input.dispatchMouseEvent', {
                'type': 'mouseMoved',
                'x': cur_x, 'y': cur_y,
            })
            await asyncio.sleep(0.015)

        # 2. Full click event sequence via CDP
        #    mousePressed → mouseReleased triggers browser to synthesize
        #    pointerdown + mousedown + pointerup + mouseup + click.
        #    This is trusted input that React SPAs cannot ignore.
        await cdp.send('Input.dispatchMouseEvent', {
            'type': 'mousePressed',
            'x': cx, 'y': cy,
            'button': 'left', 'clickCount': 1,
        })
        await asyncio.sleep(0.05)  # human-like hold time
        await cdp.send('Input.dispatchMouseEvent', {
            'type': 'mouseReleased',
            'x': cx, 'y': cy,
            'button': 'left', 'clickCount': 1,
        })

        # ------------------------------------------------------------------
        # Concurrent side-effect detection (event-driven + object-identity diff)
        # ------------------------------------------------------------------
        feedback = [f"Clicked ref [{ref}] (<{role}>) at ({int(cx)},{int(cy)})"]

        async def _report_new_page(new_page):
            """Common reporting helper for new-page detection."""
            if effect['type'] is not None:
                return
            effect['type'] = 'new_tab'
            try:
                await new_page.bring_to_front()
                bm.set_active_page(new_page)
                new_title = await new_page.title()
                new_index = context.pages.index(new_page)
                feedback.append(f"→ Opened new tab [{new_index}]: '{new_title}'")
                feedback.append(f"  URL: {new_page.url}")
            except Exception:
                feedback.append("→ New tab opened (could not retrieve details)")

        async def detect_new_tab():
            """Path A: event-driven wait_for_page (fast, but may miss sync events)."""
            try:
                new_page = await context.wait_for_event('page', timeout=2.0)
                if new_page not in pages_before:
                    await _report_new_page(new_page)
            except Exception:
                pass
            # Path B: object-identity snapshot diff (reliable fallback)
            if effect['type'] is None:
                for p in context.pages:
                    if p not in pages_before:
                        await _report_new_page(p)
                        return

        async def detect_navigation():
            try:
                await cdp.send('Page.enable')
            except Exception:
                pass
            start = asyncio.get_event_loop().time()
            while (asyncio.get_event_loop().time() - start) < 2.0 and effect['type'] is None:
                await asyncio.sleep(0.1)
                if page.url != url_before:
                    effect['type'] = 'navigation'
                    feedback.append(f"→ Navigated to: {page.url}")
                    return

        async def fallback_poll():
            """Path C: poll + object-identity diff (last resort)."""
            for _ in range(20):
                if effect['type'] is not None:
                    return
                await asyncio.sleep(0.1)
                for p in context.pages:
                    if p not in pages_before:
                        await _report_new_page(p)
                        return
                if page.url != url_before:
                    effect['type'] = 'navigation'
                    feedback.append(f"→ Navigated to: {page.url}")
                    return

        # Run all detectors concurrently, first result wins
        await asyncio.gather(
            detect_new_tab(),
            detect_navigation(),
            fallback_poll(),
        )

        # Wait a moment then do a final unconditional scan
        await asyncio.sleep(0.5)
        if effect['type'] is None:
            for p in context.pages:
                if p not in pages_before:
                    await _report_new_page(p)
            if effect['type'] is None and page.url != url_before:
                effect['type'] = 'navigation'
                feedback.append(f"→ Navigated to: {page.url}")

        # Invalidate snapshot cache so next snapshot is fresh
        _snapshot_cache = {}

        if effect['type'] is None:
            feedback.append("(no page change detected)")
        else:
            # Auto-snapshot after detected side effects so the LLM immediately
            # sees the new page state without an extra snapshot() call.
            try:
                snap = await _snapshot()
                feedback.append("")
                feedback.append("--- Updated snapshot ---")
                feedback.append(snap)
            except Exception:
                feedback.append("(could not take auto-snapshot)")

        return "\n".join(feedback)
    except Exception as e:
        return f"Error clicking ref [{ref}]: {str(e)}"


# ---------------------------------------------------------------------------
# Tool: Typing
# ---------------------------------------------------------------------------
@mcp.tool()
async def type_text(selector: str, text: str) -> str:
    """Type text into an input/textarea by CSS selector. Human-like per-character typing."""
    try:
        bm = _get_bm()
        page = await bm.get_page()
        await page.fill(selector, text)
        display = text[:50] + ("..." if len(text) > 50 else "")
        return f"Typed '{display}' into {selector}"
    except Exception as e:
        return f"Error typing into {selector}: {str(e)}"


# ---------------------------------------------------------------------------
# Tool: Keyboard
# ---------------------------------------------------------------------------
@mcp.tool()
async def press_key(key: str) -> str:
    """Press a keyboard key (Enter, Escape, Tab, ArrowDown, ArrowUp, etc.).
    
    Sends the key event to the currently focused element (not hardcoded to <body>),
    so it works in iframes, input fields, and shadow DOM context.
    """
    try:
        bm = _get_bm()
        page = await bm.get_page()
        await page.keyboard.press(key)
        return f"Pressed key: {key}"
    except Exception as e:
        return f"Error pressing key {key}: {str(e)}"


# ---------------------------------------------------------------------------
# Tool: Read page (Markdown content extraction)
# ---------------------------------------------------------------------------
@mcp.tool()
async def read_page() -> str:
    """Extract the current page's main content as clean Markdown.
    
    Uses Mozilla's Readability algorithm (same as Firefox Reader View)
    to identify the article/main content, strips navigation/sidebars/ads,
    then converts to Markdown.  Ideal for reading articles, documentation,
    or any long-form text content.
    
    Use this INSTEAD of execute_js when you need to understand the text
    content of a page — it's cleaner, more readable, and costs fewer tokens.
    
    Returns the page content as Markdown text, or a message if no
    readable content was found.
    """
    try:
        bm = _get_bm()
        page = await bm.get_page()

        READABILITY_JS = r'''
        (() => {
            // Load Readability & Turndown from CDN
            return new Promise((resolve, reject) => {
                const scripts = [
                    'https://unpkg.com/@mozilla/readability@0.5.0/Readability.js',
                    'https://unpkg.com/turndown@7.2.0/lib/turndown.es.js',
                ];
                let loaded = 0;
                scripts.forEach(url => {
                    const s = document.createElement('script');
                    s.src = url;
                    s.onload = () => { loaded++; if (loaded === scripts.length) resolve(); };
                    s.onerror = reject;
                    document.head.appendChild(s);
                });
            });
        })()
        '''

        try:
            await page.evaluate(READABILITY_JS)
        except Exception as e:
            return f"Could not load readability libraries: {str(e)}"

        result = await page.evaluate(r'''
        (() => {
            try {
                // Clone document to avoid modifying the live page
                const doc = document.cloneNode(true);
                const reader = new Readability(doc);
                const article = reader.parse();
                if (!article || !article.content) {
                    // Fallback: return <body> text if no article found
                    const text = document.body.innerText || '';
                    return { title: document.title, content: text, format: 'text' };
                }
                // Convert HTML to Markdown
                const turndown = new TurndownService({
                    headingStyle: 'atx',
                    codeBlockStyle: 'fenced',
                });
                const markdown = turndown.turndown(article.content);
                return { title: article.title, content: markdown, format: 'markdown', excerpt: article.excerpt || '' };
            } catch (e) {
                return { title: document.title, content: document.body.innerText || '', format: 'text', error: e.message };
            }
        })
        ''')

        lines = [f"# {result.get('title', 'Untitled')}"]
        if result.get('excerpt'):
            lines.append(f"\n> {result['excerpt']}\n")
        lines.append(result.get('content', ''))
        return '\n'.join(lines)
    except Exception as e:
        return f"Error reading page: {str(e)}"


# ---------------------------------------------------------------------------
# Tool: JavaScript execution (fallback)
# ---------------------------------------------------------------------------
@mcp.tool()
async def execute_js(code: str) -> str:
    """Execute arbitrary JavaScript in the browser and return the result as string.
    
    Use this as a FALLBACK when standard tools can't reach content
    inside shadow DOM, iframes, or dynamically rendered web components.
    
    Also use for tasks like: reading element text, dispatch hover events,
    directly accessing closed shadow roots, or any custom DOM manipulation.
    
    Args:
        code: JavaScript code to execute (e.g. "document.title" or a function).
              Results are JSON-serialized. For large text, return it as a string.
    
    Example: 
      execute_js(code='document.querySelector("my-component").shadowRoot.querySelector(".reply").innerText')
    """
    try:
        bm = _get_bm()
        page = await bm.get_page()
        result = await page.evaluate(code)
        if result is None:
            return "(null)"
        if isinstance(result, (dict, list)):
            import json
            return json.dumps(result, ensure_ascii=False, indent=2)
        return str(result)
    except Exception as e:
        return f"Error executing JS: {str(e)}"


# ---------------------------------------------------------------------------
# Tool: Screenshot
# ---------------------------------------------------------------------------
@mcp.tool()
async def screenshot(max_width: int = 1024, quality: int = 40, return_path: bool = False) -> str:
    """Take a screenshot. Returns a compressed JPEG as base64 data URI.
    
    Args:
        max_width: Maximum width in pixels (downscaled to this, default 1024).
                   Set to 0 to skip resizing.
        quality: JPEG quality 1-100 (default 40). Lower = smaller file.
        return_path: If True, save to local file and return path instead of base64.
                     Useful for large screenshots or VLM tools that read local files.
    """
    try:
        bm = _get_bm()
        page = await bm.get_page()
        raw_bytes = await page.screenshot()

        img = Image.open(BytesIO(raw_bytes))

        if max_width > 0 and img.width > max_width:
            ratio = max_width / img.width
            new_size = (max_width, int(img.height * ratio))
            img = img.resize(new_size, Image.LANCZOS)

        buf = BytesIO()
        img.save(buf, format="JPEG", quality=quality, optimize=True)
        compressed = buf.getvalue()

        if return_path:
            from pathlib import Path
            import time
            cache_dir = Path(__file__).parent / "screenshots"
            cache_dir.mkdir(exist_ok=True)
            filename = f"screenshot_{int(time.time())}.jpg"
            filepath = cache_dir / filename
            with open(filepath, "wb") as f:
                f.write(compressed)
            return f"Screenshot saved: {filepath} ({len(compressed)} bytes)"

        b64 = base64.b64encode(compressed).decode("utf-8")
        return f"data:image/jpeg;base64,{b64}"
    except Exception as e:
        return f"Error taking screenshot: {str(e)}"


# ---------------------------------------------------------------------------
# Tool: Scrolling
# ---------------------------------------------------------------------------
@mcp.tool()
async def scroll(amount: int = 300) -> str:
    """Scroll the page. Positive amount = down, negative amount = up.
    
    Args:
        amount: Pixels to scroll. Positive scrolls down, negative scrolls up.
    """
    try:
        bm = _get_bm()
        page = await bm.get_page()
        direction = "down" if amount >= 0 else "up"
        await page.evaluate(f"window.scrollBy(0, {amount})")
        return f"Scrolled {direction} by {abs(amount)} pixels"
    except Exception as e:
        return f"Error scrolling: {str(e)}"


# ---------------------------------------------------------------------------
# Tool: Drag (滑块验证)
# ---------------------------------------------------------------------------
@mcp.tool()
async def drag(selector: str, target_selector: str = None, x: int = None, y: int = None) -> str:
    """Drag an element (e.g. slider) — human-like movement via CloakBrowser.
    
    Two modes:
    1. Drag to another element: drag(selector="#slider", target_selector="#target")
    2. Drag by pixel offset: drag(selector="#slider", x=300, y=0)
    
    For slider verification, use mode 2: drag to offset by the required pixel distance.
    The movement goes through CloakBrowser's humanize pipeline (Bézier curves).
    """
    try:
        bm = _get_bm()
        page = await bm.get_page()
        locator = page.locator(selector)

        if target_selector:
            target_loc = page.locator(target_selector)
            await locator.drag_to(target_loc)
            return f"Dragged {selector} to {target_selector}"
        elif x is not None and y is not None:
            box = await locator.bounding_box()
            if not box:
                return f"Error: element {selector} has no bounding box (not visible)"
            start_x = box['x'] + box['width'] / 2
            start_y = box['y'] + box['height'] / 2
            end_x = start_x + x
            end_y = start_y + y
            # Human-like drag: move to start → press → step to end → release
            await page.mouse.move(start_x, start_y)
            await page.mouse.down()
            # Smooth movement in steps (human-like)
            steps = max(20, abs(x) // 5)
            for i in range(1, steps + 1):
                t = i / steps
                # Non-linear easing for human feel
                ease = t * t * (3 - 2 * t)  # smoothstep
                cur_x = start_x + x * ease
                cur_y = start_y + y * ease
                await page.mouse.move(cur_x, cur_y)
            await page.mouse.up()
            return f"Dragged {selector} by ({x}, {y}) from ({int(start_x)},{int(start_y)}) to ({int(end_x)},{int(end_y)})"
        else:
            return "Error: provide target_selector or (x, y) offset"
    except Exception as e:
        return f"Error dragging {selector}: {str(e)}"


# ---------------------------------------------------------------------------
# Tool: Tab Management
# ---------------------------------------------------------------------------
@mcp.tool()
async def list_pages() -> str:
    """List all open browser tabs with their index, title, and URL."""
    try:
        bm = _get_bm()
        pages_info = await bm.list_pages()
        if not pages_info:
            return "No pages open. Launch the browser first."
        lines = []
        for p in pages_info:
            active = " ◄ ACTIVE" if p["active"] else ""
            lines.append(f"[{p['index']}] {p['title']}{active}")
            lines.append(f"     {p['url']}")
        return "\n".join(lines)
    except Exception as e:
        return f"Error listing pages: {str(e)}"


@mcp.tool()
async def switch_page(index: int) -> str:
    """Switch to a specific browser tab by index (0-based). Use list_pages first to see indices."""
    try:
        bm = _get_bm()
        title = await bm.switch_page(index)
        return f"Switched to tab [{index}]: '{title}'"
    except Exception as e:
        return f"Error switching to page {index}: {str(e)}"


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    mcp.run(transport="stdio")
