"""
Unit tests for MCP Server (TDD first).
Uses mocked BrowserManager to avoid launching real Chromium.
"""

from unittest.mock import MagicMock, AsyncMock, patch
import pytest
import asyncio

from browser_manager import BrowserManager


@pytest.fixture(autouse=True)
def reset_browser_manager():
    """Reset the BrowserManager singleton AND the mcp_server lazy singleton before each test."""
    BrowserManager._instance = None
    import mcp_server
    mcp_server._bm_instance = None
    yield
    BrowserManager._instance = None
    mcp_server._bm_instance = None


class TestMCPServerTools:
    """Tests that the MCP server exposes all required tools."""

    def test_server_created_with_correct_name(self):
        import mcp_server
        assert mcp_server.mcp.name == "browser-agent"

    def test_server_has_instructions(self):
        import mcp_server
        assert mcp_server.mcp.instructions is not None
        assert len(mcp_server.mcp.instructions) > 0

    def test_all_required_tools_registered(self):
        import mcp_server
        tool_names = [tool.name for tool in mcp_server.mcp._tool_manager.list_tools()]
        expected_tools = [
            "launch_browser", "close_browser", "navigate",
            "snapshot", "click_ref", "type_text", "press_key",
            "read_page",
            "execute_js", "screenshot", "scroll", "drag",
            "list_pages", "switch_page",
        ]
        for tool_name in expected_tools:
            assert tool_name in tool_names, f"Missing tool: {tool_name}"
        assert len(tool_names) == len(expected_tools)

    def test_deleted_tools_not_registered(self):
        import mcp_server
        tool_names = [tool.name for tool in mcp_server.mcp._tool_manager.list_tools()]
        deleted = ["click", "get_element_text", "get_page_text",
                   "get_current_url", "get_page_title", "wait",
                   "hover", "select_option"]
        for name in deleted:
            assert name not in tool_names, f"Should have removed: {name}"


class TestToolFunctions:
    """Tests for individual tool function behavior."""

    # ------------------------------------------------------------------
    # launch_browser
    # ------------------------------------------------------------------
    @patch("mcp_server.BrowserManager")
    def test_launch_browser_calls_ensure_browser(self, mock_bm_cls):
        mock_instance = MagicMock()
        mock_page = MagicMock()
        mock_page.title = AsyncMock(return_value="Test Page")
        mock_instance.ensure_browser = AsyncMock(return_value=mock_page)
        mock_bm_cls.return_value = mock_instance

        import mcp_server

        async def run():
            return await mcp_server.launch_browser()

        result = asyncio.run(run())
        mock_instance.ensure_browser.assert_awaited_once()
        assert "launched" in result.lower()

    # ------------------------------------------------------------------
    # close_browser
    # ------------------------------------------------------------------
    @patch("mcp_server.BrowserManager")
    def test_close_browser_calls_manager_close(self, mock_bm_cls):
        mock_instance = MagicMock()
        mock_instance.close = AsyncMock()
        mock_bm_cls.return_value = mock_instance

        import mcp_server

        async def run():
            return await mcp_server.close_browser()

        result = asyncio.run(run())
        mock_instance.close.assert_awaited_once()
        assert "closed" in result.lower()

    # ------------------------------------------------------------------
    # navigate
    # ------------------------------------------------------------------
    @patch("mcp_server.BrowserManager")
    def test_navigate_calls_page_goto(self, mock_bm_cls):
        mock_instance = MagicMock()
        mock_page = MagicMock()
        mock_page.title = AsyncMock(return_value="Example")
        mock_page.goto = AsyncMock()
        mock_page.url = "https://example.com"
        mock_instance.get_page = AsyncMock(return_value=mock_page)
        mock_bm_cls.return_value = mock_instance

        import mcp_server

        async def run():
            return await mcp_server.navigate("https://example.com")

        result = asyncio.run(run())
        mock_page.goto.assert_awaited_once_with("https://example.com")
        assert "Example" in result

    @patch("mcp_server.BrowserManager")
    def test_navigate_returns_title_and_url(self, mock_bm_cls):
        mock_instance = MagicMock()
        mock_page = MagicMock()
        mock_page.title = AsyncMock(return_value="Google")
        mock_page.goto = AsyncMock()
        mock_page.url = "https://google.com"
        mock_instance.get_page = AsyncMock(return_value=mock_page)
        mock_bm_cls.return_value = mock_instance

        import mcp_server

        async def run():
            return await mcp_server.navigate("https://google.com")

        result = asyncio.run(run())
        assert "OK:" in result
        assert "Google" in result
        assert "URL:" in result
        assert "https://google.com" in result

    # ------------------------------------------------------------------
    # type_text
    # ------------------------------------------------------------------
    @patch("mcp_server.BrowserManager")
    def test_type_text_calls_page_fill(self, mock_bm_cls):
        mock_instance = MagicMock()
        mock_page = MagicMock()
        mock_page.fill = AsyncMock()
        mock_instance.get_page = AsyncMock(return_value=mock_page)
        mock_bm_cls.return_value = mock_instance

        import mcp_server

        async def run():
            return await mcp_server.type_text("#search", "hello world")

        result = asyncio.run(run())
        mock_page.fill.assert_awaited_once_with("#search", "hello world")
        assert "typed" in result.lower()

    # ------------------------------------------------------------------
    # press_key
    # ------------------------------------------------------------------
    @patch("mcp_server.BrowserManager")
    def test_press_key_calls_keyboard_press(self, mock_bm_cls):
        mock_instance = MagicMock()
        mock_page = MagicMock()
        mock_page.keyboard = MagicMock()
        mock_page.keyboard.press = AsyncMock()
        mock_instance.get_page = AsyncMock(return_value=mock_page)
        mock_bm_cls.return_value = mock_instance

        import mcp_server

        async def run():
            return await mcp_server.press_key("Enter")

        result = asyncio.run(run())
        mock_page.keyboard.press.assert_awaited_once_with("Enter")
        assert "pressed" in result.lower()

    # ------------------------------------------------------------------
    # execute_js
    # ------------------------------------------------------------------
    @patch("mcp_server.BrowserManager")
    def test_execute_js_returns_string_result(self, mock_bm_cls):
        mock_instance = MagicMock()
        mock_page = MagicMock()
        mock_page.evaluate = AsyncMock(return_value="hello from browser")
        mock_instance.get_page = AsyncMock(return_value=mock_page)
        mock_bm_cls.return_value = mock_instance

        import mcp_server

        async def run():
            return await mcp_server.execute_js("document.title")

        result = asyncio.run(run())
        mock_page.evaluate.assert_awaited_once_with("document.title")
        assert result == "hello from browser"

    @patch("mcp_server.BrowserManager")
    def test_execute_js_returns_json_for_dict(self, mock_bm_cls):
        mock_instance = MagicMock()
        mock_page = MagicMock()
        mock_page.evaluate = AsyncMock(return_value={"key": "value", "num": 42})
        mock_instance.get_page = AsyncMock(return_value=mock_page)
        mock_bm_cls.return_value = mock_instance

        import mcp_server

        async def run():
            return await mcp_server.execute_js("return {key: 'value', num: 42}")

        result = asyncio.run(run())
        assert '"key": "value"' in result
        assert '"num": 42' in result

    # ------------------------------------------------------------------
    # screenshot
    # ------------------------------------------------------------------
    @patch("mcp_server.BrowserManager")
    def test_screenshot_returns_base64_data_uri(self, mock_bm_cls):
        mock_instance = MagicMock()
        mock_page = MagicMock()
        # Create a minimal 1x1 JPEG using PIL (so it's valid)
        from PIL import Image
        import io
        img = Image.new("RGB", (1, 1), (255, 0, 0))
        buf = io.BytesIO()
        img.save(buf, format="JPEG")
        mock_page.screenshot = AsyncMock(return_value=buf.getvalue())
        mock_instance.get_page = AsyncMock(return_value=mock_page)
        mock_bm_cls.return_value = mock_instance

        import mcp_server

        async def run():
            return await mcp_server.screenshot()

        result = asyncio.run(run())
        mock_page.screenshot.assert_awaited_once()
        assert result.startswith("data:image/jpeg;base64,")

    @patch("mcp_server.BrowserManager")
    def test_screenshot_return_path(self, mock_bm_cls):
        mock_instance = MagicMock()
        mock_page = MagicMock()
        # Return a valid 1x1 JPEG
        from PIL import Image
        import io
        img = Image.new("RGB", (1, 1), (255, 0, 0))
        buf = io.BytesIO()
        img.save(buf, format="JPEG")
        mock_page.screenshot = AsyncMock(return_value=buf.getvalue())
        mock_instance.get_page = AsyncMock(return_value=mock_page)
        mock_bm_cls.return_value = mock_instance

        import mcp_server

        async def run():
            return await mcp_server.screenshot(return_path=True)

        result = asyncio.run(run())
        assert "Screenshot saved:" in result
        assert ".jpg" in result

    # ------------------------------------------------------------------
    # scroll
    # ------------------------------------------------------------------
    @patch("mcp_server.BrowserManager")
    def test_scroll_down(self, mock_bm_cls):
        mock_instance = MagicMock()
        mock_page = MagicMock()
        mock_page.evaluate = AsyncMock()
        mock_instance.get_page = AsyncMock(return_value=mock_page)
        mock_bm_cls.return_value = mock_instance

        import mcp_server

        async def run():
            return await mcp_server.scroll(300)

        result = asyncio.run(run())
        mock_page.evaluate.assert_awaited()
        call_args = mock_page.evaluate.await_args[0][0]
        assert "scrollBy(0, 300)" in call_args
        assert "scrolled" in result.lower()
        assert "down" in result.lower()

    @patch("mcp_server.BrowserManager")
    def test_scroll_up(self, mock_bm_cls):
        mock_instance = MagicMock()
        mock_page = MagicMock()
        mock_page.evaluate = AsyncMock()
        mock_instance.get_page = AsyncMock(return_value=mock_page)
        mock_bm_cls.return_value = mock_instance

        import mcp_server

        async def run():
            return await mcp_server.scroll(-200)

        result = asyncio.run(run())
        mock_page.evaluate.assert_awaited()
        call_args = mock_page.evaluate.await_args[0][0]
        assert "scrollBy(0, -200)" in call_args
        assert "scrolled" in result.lower()
        assert "up" in result.lower()

    # ------------------------------------------------------------------
    # list_pages
    # ------------------------------------------------------------------
    @patch("mcp_server.BrowserManager")
    def test_list_pages_returns_page_info(self, mock_bm_cls):
        mock_instance = MagicMock()
        mock_instance.list_pages = AsyncMock(return_value=[
            {"index": 0, "title": "Page 1", "url": "https://a.com", "active": True},
            {"index": 1, "title": "Page 2", "url": "https://b.com", "active": False},
        ])
        mock_bm_cls.return_value = mock_instance

        import mcp_server

        async def run():
            return await mcp_server.list_pages()

        result = asyncio.run(run())
        assert "Page 1" in result
        assert "https://a.com" in result
        assert "ACTIVE" in result

    # ------------------------------------------------------------------
    # switch_page
    # ------------------------------------------------------------------
    @patch("mcp_server.BrowserManager")
    def test_switch_page_calls_manager(self, mock_bm_cls):
        mock_instance = MagicMock()
        mock_instance.switch_page = AsyncMock(return_value="Target Tab")
        mock_bm_cls.return_value = mock_instance

        import mcp_server

        async def run():
            return await mcp_server.switch_page(1)

        result = asyncio.run(run())
        mock_instance.switch_page.assert_awaited_once_with(1)
        assert "Target Tab" in result
        assert "1" in result

    # ------------------------------------------------------------------
    # drag
    # ------------------------------------------------------------------
    @patch("mcp_server.BrowserManager")
    def test_drag_by_offset(self, mock_bm_cls):
        mock_instance = MagicMock()
        mock_page = MagicMock()
        mock_locator = MagicMock()
        mock_locator.bounding_box = AsyncMock(return_value={"x": 100, "y": 200, "width": 40, "height": 20})
        mock_page.locator = MagicMock(return_value=mock_locator)
        mock_page.mouse = MagicMock()
        mock_page.mouse.move = AsyncMock()
        mock_page.mouse.down = AsyncMock()
        mock_page.mouse.up = AsyncMock()
        mock_instance.get_page = AsyncMock(return_value=mock_page)
        mock_bm_cls.return_value = mock_instance

        import mcp_server

        async def run():
            return await mcp_server.drag(selector="#slider", x=150, y=0)

        result = asyncio.run(run())
        mock_page.locator.assert_called_once_with("#slider")
        assert "Dragged" in result
        assert "150" in result
        assert "120" in result  # start_x = 100 + 20 = 120

    @patch("mcp_server.BrowserManager")
    def test_drag_to_target_selector(self, mock_bm_cls):
        mock_instance = MagicMock()
        mock_page = MagicMock()
        mock_source_locator = MagicMock()
        mock_source_locator.drag_to = AsyncMock()
        mock_page.locator = MagicMock(return_value=mock_source_locator)
        mock_instance.get_page = AsyncMock(return_value=mock_page)
        mock_bm_cls.return_value = mock_instance

        import mcp_server

        async def run():
            return await mcp_server.drag(selector="#slider", target_selector="#target")

        result = asyncio.run(run())
        assert "Dragged" in result
        assert "#target" in result
        mock_source_locator.drag_to.assert_awaited_once()

    # ------------------------------------------------------------------
    # click_ref (requires _snapshot_cache)
    # ------------------------------------------------------------------
    @patch("mcp_server.BrowserManager")
    def test_click_ref_requires_snapshot_first(self, mock_bm_cls):
        mock_instance = MagicMock()
        mock_page = MagicMock()
        mock_instance.get_page = AsyncMock(return_value=mock_page)
        mock_bm_cls.return_value = mock_instance

        import mcp_server
        # Clear cache to simulate no snapshot taken
        mcp_server._snapshot_cache = {}

        async def run():
            return await mcp_server.click_ref(5)

        result = asyncio.run(run())
        assert "not found" in result.lower()
        assert "snapshot" in result.lower()

    @patch("mcp_server.BrowserManager")
    def test_click_ref_clicks_cached_element(self, mock_bm_cls):
        """CDP-based click: verify Bézier move + press + release sequence."""
        mock_instance = MagicMock()
        mock_page = MagicMock()
        mock_page.url = "https://example.com/page"
        mock_page.context = MagicMock()
        mock_page.context.pages = [mock_page]  # no new tab
        mock_page.context.wait_for_event = AsyncMock(
            side_effect=asyncio.TimeoutError())
        # page.evaluate: scrollTo, scrollY, scrollX, mouse start pos
        mock_page.evaluate = AsyncMock(side_effect=[None, 0, 0, [400, 300]])
        mock_instance.get_page = AsyncMock(return_value=mock_page)

        # Mock CDP session: getContentQuads + Page.enable + mouse events
        mock_cdp = AsyncMock()
        async def cdp_send(method, params=None):
            if method == "DOM.getContentQuads":
                return {"quads": [[100, 150, 200, 150, 200, 200, 100, 200]]}
            if method == "Page.enable":
                return {}
            return {}
        mock_cdp.send = AsyncMock(side_effect=cdp_send)
        mock_page.context.new_cdp_session = AsyncMock(return_value=mock_cdp)

        mock_bm_cls.return_value = mock_instance

        import mcp_server
        mcp_server._snapshot_cache = {5: {"backendId": 42, "role": "button"}}

        async def run():
            return await mcp_server.click_ref(5)

        result = asyncio.run(run())
        assert "Clicked ref [5]" in result
        assert "button" in result
        # Verify CDP was used to get coordinates
        mock_cdp.send.assert_any_call("DOM.getContentQuads", {"backendNodeId": 42})
        # Verify CDP mousePress was sent (core click event)
        press_calls = [c for c in mock_cdp.send.call_args_list
                       if c[0][0] == "Input.dispatchMouseEvent"
                       and c[0][1].get('type') == 'mousePressed']
        assert len(press_calls) >= 1, "CDP mousePressed should have been sent"

    @patch("mcp_server.BrowserManager")
    def test_click_ref_detects_new_tab(self, mock_bm_cls):
        """Verify click_ref detects and reports a newly opened tab."""
        mock_instance = MagicMock()
        mock_page = MagicMock()
        mock_page.url = "https://example.com/page"
        mock_page.evaluate = AsyncMock(side_effect=[None, 0, 0, [400, 300]])

        pages_list = [mock_page]
        mock_page.context = MagicMock()
        mock_page.context.pages = pages_list
        mock_page.context.wait_for_event = AsyncMock(
            side_effect=asyncio.TimeoutError())  # new tab detected by poll, not event

        mock_new_page = MagicMock()
        mock_new_page.bring_to_front = AsyncMock()
        mock_new_page.title = AsyncMock(return_value="New Tab Title")
        mock_new_page.url = "https://example.com/new-tab"

        mock_instance.get_page = AsyncMock(return_value=mock_page)
        mock_instance.set_active_page = MagicMock()

        # CDP sends the click. After click, add a new page to simulate new tab.
        mock_cdp = AsyncMock()
        async def cdp_send_side_effect(method, params=None):
            if method == "DOM.getContentQuads":
                return {"quads": [[100, 150, 200, 150, 200, 200, 100, 200]]}
            if method == "Input.dispatchMouseEvent" and params and params.get('type') == 'mouseReleased':
                pages_list.append(mock_new_page)  # new tab appears after click
            return {}
        mock_cdp.send = AsyncMock(side_effect=cdp_send_side_effect)
        mock_page.context.new_cdp_session = AsyncMock(return_value=mock_cdp)

        mock_bm_cls.return_value = mock_instance

        import mcp_server
        mcp_server._snapshot_cache = {5: {"backendId": 42, "role": "link"}}

        async def run():
            return await mcp_server.click_ref(5)

        result = asyncio.run(run())
        assert "Clicked ref [5]" in result
        assert "Opened new tab [1]" in result
        assert "New Tab Title" in result
        mock_instance.set_active_page.assert_called_with(mock_new_page)

    # ------------------------------------------------------------------
    # snapshot (basic structure test — full test requires CDP mock)
    # ------------------------------------------------------------------
    @patch("mcp_server.BrowserManager")
    def test_snapshot_returns_structure(self, mock_bm_cls):
        mock_instance = MagicMock()
        mock_page = MagicMock()

        # Mock CDP session
        mock_cdp = AsyncMock()
        mock_cdp.send = AsyncMock(return_value={
            "nodes": [
                {"role": {"value": "RootWebArea"}, "name": {"value": "Test Page"},
                 "ignored": False, "childIds": ["c1"]},
                {"role": {"value": "button"}, "name": {"value": "Click Me"},
                 "ignored": False, "backendDOMNodeId": 10, "childIds": []},
                {"role": {"value": "StaticText"}, "name": {"value": "Some text"},
                 "ignored": False, "childIds": []},
                {"role": {"value": "textbox"}, "name": {"value": "Search"},
                 "ignored": False, "backendDOMNodeId": 20, "childIds": []},
            ]
        })
        mock_page.context.new_cdp_session = AsyncMock(return_value=mock_cdp)
        mock_instance.get_page = AsyncMock(return_value=mock_page)
        mock_bm_cls.return_value = mock_instance

        import mcp_server

        async def run():
            return await mcp_server.snapshot()

        result = asyncio.run(run())
        assert "Page Snapshot" in result
        # compact mode: StaticText hidden, 2 interactive shown
        assert "Click Me" in result
        assert "Search" in result
        assert "Some text" not in result  # folded in compact mode

    @patch("mcp_server.BrowserManager")
    def test_snapshot_full_mode_shows_all(self, mock_bm_cls):
        mock_instance = MagicMock()
        mock_page = MagicMock()

        mock_cdp = AsyncMock()
        mock_cdp.send = AsyncMock(return_value={
            "nodes": [
                {"role": {"value": "RootWebArea"}, "name": {"value": "Test"},
                 "ignored": False, "childIds": []},
                {"role": {"value": "StaticText"}, "name": {"value": "Visible text"},
                 "ignored": False, "childIds": []},
            ]
        })
        mock_page.context.new_cdp_session = AsyncMock(return_value=mock_cdp)
        mock_instance.get_page = AsyncMock(return_value=mock_page)
        mock_bm_cls.return_value = mock_instance

        import mcp_server

        async def run():
            return await mcp_server.snapshot(mode="full")

        result = asyncio.run(run())
        assert "Visible text" in result  # full mode shows text


class TestToolErrorHandling:
    """Tests that tools handle errors gracefully."""

    @patch("mcp_server.BrowserManager")
    def test_navigate_handles_error(self, mock_bm_cls):
        mock_instance = MagicMock()
        mock_page = MagicMock()
        mock_page.goto = AsyncMock(side_effect=Exception("Navigation timeout"))
        mock_instance.get_page = AsyncMock(return_value=mock_page)
        mock_bm_cls.return_value = mock_instance

        import mcp_server

        async def run():
            return await mcp_server.navigate("https://bad-site.com")

        result = asyncio.run(run())
        assert "error" in result.lower()

    @patch("mcp_server.BrowserManager")
    def test_screenshot_handles_error(self, mock_bm_cls):
        mock_instance = MagicMock()
        mock_page = MagicMock()
        mock_page.screenshot = AsyncMock(side_effect=Exception("screenshot failed"))
        mock_instance.get_page = AsyncMock(return_value=mock_page)
        mock_bm_cls.return_value = mock_instance

        import mcp_server

        async def run():
            return await mcp_server.screenshot()

        result = asyncio.run(run())
        assert "error" in result.lower()

    @patch("mcp_server.BrowserManager")
    def test_click_ref_handles_stale_ref(self, mock_bm_cls):
        mock_instance = MagicMock()
        mock_page = MagicMock()
        mock_instance.get_page = AsyncMock(return_value=mock_page)
        mock_bm_cls.return_value = mock_instance

        import mcp_server

        async def run():
            return await mcp_server.click_ref(999)

        result = asyncio.run(run())
        assert "error" in result.lower()

    @patch("mcp_server.BrowserManager")
    def test_drag_missing_params(self, mock_bm_cls):
        mock_instance = MagicMock()
        mock_page = MagicMock()
        mock_instance.get_page = AsyncMock(return_value=mock_page)
        mock_bm_cls.return_value = mock_instance

        import mcp_server

        async def run():
            return await mcp_server.drag(selector="#slider")

        result = asyncio.run(run())
        assert "error" in result.lower()

    @patch("mcp_server.BrowserManager")
    def test_execute_js_handles_error(self, mock_bm_cls):
        mock_instance = MagicMock()
        mock_page = MagicMock()
        mock_page.evaluate = AsyncMock(side_effect=Exception("JS runtime error"))
        mock_instance.get_page = AsyncMock(return_value=mock_page)
        mock_bm_cls.return_value = mock_instance

        import mcp_server

        async def run():
            return await mcp_server.execute_js("bad code }")

        result = asyncio.run(run())
        assert "error" in result.lower()
