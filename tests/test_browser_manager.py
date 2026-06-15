"""
Unit tests for BrowserManager (TDD first).
Uses mocked cloakbrowser to avoid launching real Chromium.
"""

from unittest.mock import MagicMock, AsyncMock, patch
import pytest
import asyncio
import threading
from pathlib import Path

from browser_manager import BrowserManager, PROFILE_DIR


@pytest.fixture(autouse=True)
def reset_singleton():
    """Reset the BrowserManager singleton before each test."""
    BrowserManager._instance = None
    yield
    BrowserManager._instance = None


class TestBrowserManagerSingleton:
    """Tests for the singleton pattern."""

    def test_singleton_returns_same_instance(self):
        m1 = BrowserManager()
        m2 = BrowserManager()
        assert m1 is m2

    def test_singleton_thread_safe(self):
        instances = []

        def get_instance():
            instances.append(BrowserManager())

        threads = [threading.Thread(target=get_instance) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert all(i is instances[0] for i in instances)

    def test_reset_singleton_creates_new(self):
        m1 = BrowserManager()
        BrowserManager._instance = None
        m2 = BrowserManager()
        assert m1 is not m2


class TestBrowserManagerLifecycle:
    """Tests for browser lifecycle management."""

    @patch("browser_manager.launch_persistent_context_async")
    def test_ensure_browser_creates_on_first_call(self, mock_launch):
        """First call to ensure_browser should launch the browser."""
        mock_context = MagicMock()
        mock_page = MagicMock()
        mock_context.new_page = AsyncMock(return_value=mock_page)
        mock_launch.return_value = mock_context

        manager = BrowserManager()

        async def run():
            page = await manager.ensure_browser()
            return page

        page = asyncio.run(run())

        mock_launch.assert_called_once()
        call_kwargs = mock_launch.call_args[1]
        assert call_kwargs["headless"] is False
        assert call_kwargs["humanize"] is True

        assert page == mock_page
        assert manager._page == mock_page

    @patch("browser_manager.launch_persistent_context_async")
    def test_ensure_browser_reuses_existing_page(self, mock_launch):
        """Subsequent calls should reuse the existing page if alive."""
        mock_context = MagicMock()
        mock_page = MagicMock()
        mock_page.evaluate = AsyncMock(return_value=2)
        mock_context.new_page = AsyncMock(return_value=mock_page)
        mock_launch.return_value = mock_context

        manager = BrowserManager()

        async def run():
            page1 = await manager.ensure_browser()
            page2 = await manager.ensure_browser()
            return page1, page2

        page1, page2 = asyncio.run(run())

        mock_launch.assert_called_once()
        assert page1 is page2

    @patch("browser_manager.launch_persistent_context_async")
    def test_ensure_browser_restarts_on_dead_page(self, mock_launch):
        """If page is dead, ensure_browser should re-launch."""
        mock_context1 = MagicMock()
        mock_page1 = MagicMock()
        mock_page1.evaluate = AsyncMock(side_effect=[Exception("browser gone")])
        mock_context1.new_page = AsyncMock(return_value=mock_page1)

        mock_context2 = MagicMock()
        mock_page2 = MagicMock()
        mock_page2.evaluate = AsyncMock(return_value=2)
        mock_context2.new_page = AsyncMock(return_value=mock_page2)

        mock_launch.side_effect = [mock_context1, mock_context2]

        manager = BrowserManager()

        async def run():
            await manager.ensure_browser()  # First call - creates
            # Second call - first page dies, re-launches
            p2 = await manager.ensure_browser()
            return p2

        page2 = asyncio.run(run())

        assert mock_launch.call_count == 2
        assert page2 is mock_page2

    @patch("browser_manager.launch_persistent_context_async")
    def test_is_alive_returns_false_when_not_launched(self, mock_launch):
        """is_alive should be False before any launch."""
        manager = BrowserManager()
        assert manager.is_alive is False

    @patch("browser_manager.launch_persistent_context_async")
    def test_is_alive_returns_true_after_ensure_browser(self, mock_launch):
        """is_alive should be True after ensure_browser."""
        mock_context = MagicMock()
        mock_page = MagicMock()
        mock_page.evaluate = AsyncMock(return_value=2)
        mock_context.new_page = AsyncMock(return_value=mock_page)
        mock_launch.return_value = mock_context

        manager = BrowserManager()

        async def run():
            await manager.ensure_browser()
            return manager.is_alive

        assert asyncio.run(run()) is True

    @patch("browser_manager.launch_persistent_context_async")
    def test_is_alive_returns_false_after_close(self, mock_launch):
        """is_alive should be False after close()."""
        mock_context = MagicMock()
        mock_context.close = AsyncMock()
        mock_page = MagicMock()
        mock_page.evaluate = AsyncMock(return_value=2)
        mock_context.new_page = AsyncMock(return_value=mock_page)
        mock_launch.return_value = mock_context

        manager = BrowserManager()

        async def run():
            await manager.ensure_browser()
            await manager.close()
            return manager.is_alive

        assert asyncio.run(run()) is False

    @patch("browser_manager.launch_persistent_context_async")
    def test_close_closes_context(self, mock_launch):
        """close() should call context.close()."""
        mock_context = MagicMock()
        mock_context.close = AsyncMock()
        mock_page = MagicMock()
        mock_page.evaluate = AsyncMock(return_value=2)
        mock_context.new_page = AsyncMock(return_value=mock_page)
        mock_launch.return_value = mock_context

        manager = BrowserManager()

        async def run():
            await manager.ensure_browser()
            await manager.close()
            return manager._page, manager._context

        page, ctx = asyncio.run(run())

        mock_context.close.assert_called_once()
        assert page is None
        assert ctx is None

    @patch("browser_manager.launch_persistent_context_async")
    def test_get_page_auto_launches(self, mock_launch):
        """get_page() should auto-launch if not yet started."""
        mock_context = MagicMock()
        mock_page = MagicMock()
        mock_page.evaluate = AsyncMock(return_value=2)
        mock_context.new_page = AsyncMock(return_value=mock_page)
        mock_launch.return_value = mock_context

        manager = BrowserManager()

        async def run():
            page = await manager.get_page()
            return page

        page = asyncio.run(run())
        assert page == mock_page
        mock_launch.assert_called_once()

    def test_profile_dir_exists(self):
        """The profile directory should be set to a reasonable path."""
        assert isinstance(PROFILE_DIR, Path)
        assert "browser-profile" in str(PROFILE_DIR)


class TestBrowserManagerThreadSafety:
    """Tests for thread safety of BrowserManager."""

    @patch("browser_manager.launch_persistent_context_async")
    def test_concurrent_ensure_browser_only_launches_once(self, mock_launch):
        """Multiple concurrent ensure_browser should only launch once."""
        mock_context = MagicMock()
        mock_page = MagicMock()
        mock_page.evaluate = AsyncMock(return_value=2)
        mock_context.new_page = AsyncMock(return_value=mock_page)
        mock_launch.return_value = mock_context

        manager = BrowserManager()
        results = []

        async def call_ensure():
            p = await manager.ensure_browser()
            results.append(p)

        async def run_concurrent():
            await asyncio.gather(
                call_ensure(), call_ensure(), call_ensure(),
                call_ensure(), call_ensure(),
            )

        asyncio.run(run_concurrent())

        mock_launch.assert_called_once()
        assert len(results) == 5
        assert all(r is results[0] for r in results)
