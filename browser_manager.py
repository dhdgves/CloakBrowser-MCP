"""
Browser Manager — Singleton lifecycle manager for a persistent CloakBrowser instance.

Manages a single headed (user-visible) browser window that stays alive across
multiple MCP tool calls. Uses launch_persistent_context_async() for cookie/session persistence.
All interactions go through CloakBrowser's humanize=True pipeline for human-like behavior.
"""

from pathlib import Path

from cloakbrowser import launch_persistent_context_async

# Profile directory for persistent cookies/localStorage
PROFILE_DIR = Path(__file__).parent / "browser-profile"


class BrowserManager:
    """Singleton browser manager. One browser instance shared across all tool calls."""

    _instance = None
    _lock = None

    def __new__(cls):
        if cls._instance is None:
            import threading
            if cls._lock is None:
                cls._lock = threading.Lock()
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if getattr(self, "_initialized", False):
            return
        self._initialized = True
        self._context = None
        self._page = None
        self._ctx_lock = None  # lazy create asyncio.Lock

    def _get_lock(self):
        if self._ctx_lock is None:
            import asyncio
            self._ctx_lock = asyncio.Lock()
        return self._ctx_lock

    async def ensure_browser(self):
        """Ensure the browser is running. Returns the current page."""
        if self._page is not None:
            try:
                await self._page.evaluate("1 + 1")
                return self._page
            except Exception:
                pass  # page is dead, re-launch below

        lock = self._get_lock()
        async with lock:
            # Double-check
            if self._page is not None:
                try:
                    await self._page.evaluate("1 + 1")
                    return self._page
                except Exception:
                    pass

            # Close any stale context
            await self._close_internal()

            # Create profile directory
            PROFILE_DIR.mkdir(parents=True, exist_ok=True)

            # Launch persistent context (headed, humanized, persistent profile)
            self._context = await launch_persistent_context_async(
                str(PROFILE_DIR),
                headless=False,
                humanize=True,
                human_preset="default",
                viewport={"width": 1280, "height": 720},
            )
            self._page = await self._context.new_page()
            return self._page

    async def _close_internal(self):
        """Internal cleanup (caller must hold lock)."""
        try:
            if self._context is not None:
                await self._context.close()
        except Exception:
            pass
        self._context = None
        self._page = None

    async def get_page(self):
        """Get the current page, auto-launching if needed."""
        return await self.ensure_browser()

    async def list_pages(self):
        """List all open pages/tabs."""
        if self._context is None:
            return []
        pages = self._context.pages
        result = []
        for i, p in enumerate(pages):
            try:
                title = await p.title()
            except Exception:
                title = "(unreachable)"
            result.append({"index": i, "title": title, "url": p.url, "active": p is self._page})
        return result

    async def switch_page(self, index: int):
        """Switch to a specific page/tab by index (0-based)."""
        if self._context is None:
            raise RuntimeError("Browser not launched")
        pages = self._context.pages
        if index < 0 or index >= len(pages):
            raise RuntimeError(f"Page index {index} out of range (0-{len(pages)-1})")
        target = pages[index]
        try:
            await target.bring_to_front()
        except Exception:
            pass
        self._page = target
        return await target.title()

    def set_active_page(self, page):
        """Set the active page reference (used when switching tabs externally)."""
        self._page = page

    async def close(self):
        """Close the browser and clean up resources."""
        lock = self._get_lock()
        async with lock:
            await self._close_internal()

    @property
    def is_alive(self):
        """Check if the browser was launched (best-effort sync check)."""
        return self._page is not None
