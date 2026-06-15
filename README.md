# CloakBrowser MCP

A Model Context Protocol (MCP) server that wraps [CloakBrowser](https://github.com/czfrank/cloakbrowser) — a stealth Chromium browser with source-level anti-detection patches — into a set of AI-agent-friendly tools.

> **What does this do?** It lets AI agents (Claude, GPT, etc.) control a browser that looks like a real human to websites. Cloudflare, reCAPTCHA v3, FingerprintJS — the browser passes them all, while the agent reads snapshots, clicks elements, and extracts content just like a human would.

---

## Tools (14)

| Tool | Description |
|------|-------------|
| `launch_browser` | Launch a new stealth browser instance (CloakBrowser Chromium) |
| `close_browser` | Close the current browser instance |
| `navigate` | Navigate to a URL. Returns page title + URL. Auto-waits for page load. |
| `snapshot` | **Primary page understanding tool.** Uses CDP accessibility tree to return a structured view of the page. Each interactive element gets a `[ref]` ID. Two modes: `compact` (default, interactive elements only) and `full` (all visible nodes). |
| `click_ref` | **Sole click tool.** Click an element by its `[ref]` ID from `snapshot()`. Uses CDP Bézier mouse trajectory (human-like movement) + full `mousePressed/mouseReleased` event sequence (React SPA compatible). Detects side effects (new tabs, URL changes) and **auto-returns an updated snapshot**. No CSS selectors needed. |
| `type_text` | Type text into an input by CSS selector. Human-like per-character input. |
| `press_key` | Press a keyboard key (Enter, Escape, Tab, etc.) on the focused element. |
| `read_page` | Extract the current page's main content as **clean Markdown**. Uses Mozilla Readability (same algorithm as Firefox Reader View) to strip navigation/sidebars/ads. Falls back to `body.innerText` if no article structure is found. |
| `execute_js` | Execute arbitrary JavaScript in the browser. Use as a fallback when other tools can't reach shadow DOM or iframes. |
| `screenshot` | Capture a screenshot of the current page. Optionally return as base64 data URI or save to file. |
| `scroll` | Scroll the page by a given number of pixels (positive = down, negative = up). |
| `drag` | Drag and drop by offset or to a target selector. Uses Playwright's native drag API. |
| `list_pages` | List all open browser tabs/pages with their indexes, titles, and URLs. |
| `switch_page` | Switch the active page by index. |

---

## How It Works

```
snapshot()  →  LLM sees elements with [ref] IDs
                   ↓
click_ref(ref)  →  CDP Bézier mouse trajectory + click
                   ↓
             Detects: new tab? URL changed?
                   ↓
             Auto-returns updated snapshot()
```

### Key Design Decisions

- **No CSS selectors for clicking.** All interaction uses CDP coordinate-based clicks via `[ref]` IDs from the accessibility tree. This works across all frameworks (React, Vue, Angular, Shadow DOM) without framework-specific selectors.
- **Human-like input by default.** Mouse movements follow Bézier curves with easing and overshoot. Typing has per-character timing. All interactions are indistinguishable from real users.
- **Event-driven side-effect detection.** After each click, three concurrent detectors run (Playwright page event, CDP navigation event, polling fallback). No fixed sleep waits.
- **Auto-snapshot after actions.** When a click triggers navigation or opens a new tab, the tool automatically takes a fresh snapshot so the AI immediately sees the new state.

---

## Installation

### Prerequisites: Python 3.10+

Ensure Python 3.10 or later is installed:

```bash
python --version
```

If not installed, download from [python.org](https://python.org) or use your system package manager.

### Step 1: Install CloakBrowser

```bash
pip install cloakbrowser
```

### Step 2: Install the Chromium binary

CloakBrowser bundles its own custom Chromium binary (source-level fingerprint patches). Download it:

```bash
python -m cloakbrowser install
```

> This downloads ~535 MB to `~/.cloakbrowser/`. Do **not** run `playwright install chromium` — CloakBrowser uses its own binary.

Verify the installation:

```bash
python -m cloakbrowser info
```

### Step 3: Set environment variable (Windows only)

On Windows, set this environment variable so CloakBrowser can find its binary:

```powershell
$env:CLOAKBROWSER_AUTO_UPDATE = "false"
```

(Optional) Make permanent:

```powershell
[Environment]::SetEnvironmentVariable("CLOAKBROWSER_AUTO_UPDATE", "false", "User")
```

### Step 4: Clone the project

```bash
git clone https://github.com/dhdgves/CloakBrowser-MCP.git
cd CloakBrowser-MCP
```

Or download and extract the source to a directory of your choice.

### Step 5: Install dependencies

```bash
pip install -r requirements.txt
```

### Step 6: Configure MCP

Add this entry to your MCP client configuration:

```json
{
  "mcpServers": {
    "cloakbrowser-mcp": {
      "command": "python",
      "args": ["/path/to/CloakBrowser-MCP/mcp_server.py"],
      "env": {},
      "disabled": false
    }
  }
}
```

Replace `/path/to/CloakBrowser-MCP` with the actual full path where you cloned/extracted the project.

> **Note for Windows users:** Use the full Python interpreter path if `python` is not in your PATH, e.g.:
> ```json
> {
>   "command": "C:\\Users\\YourName\\AppData\\Local\\Programs\\Python\\Python312\\python.exe",
>   "args": ["C:\\Projects\\CloakBrowser-MCP\\mcp_server.py"]
> }
> ```

### Step 7: Restart your agent

After saving the config, restart your MCP host. The `cloakbrowser-mcp` tools will be available for use.

---

## Usage Example

```
1.  snapshot()
    → LLM sees: [15] <heading+> Search Results
                 [37] <heading+> 'Deep learning'
                 [38] <heading+> Deep learning
                 ...

2.  click_ref(38)
    → Clicked ref [38] (<heading>) at (461,338)
    → Opened new tab [2]: 'Deep learning - X-MOL'
    → --- Updated snapshot ---
      (new page's interactive elements)

3.  read_page()
    → # Deep learning
      Nature (IF 48.5) Pub Date: 2015-05-01
      Yann LeCun, Yoshua Bengio, Geoffrey Hinton
      ... (clean Markdown content)

4.  click_ref(30)  (查看原文)
    → Clicked ref [30] (<link>) at (200,300)
    → Opened new tab [3]: 'Deep learning | Nature'
    → --- Updated snapshot ---
```

---

## Architecture

```
┌─────────────┐     MCP stdio      ┌──────────────────┐
│  AI Agent   │ ◄──────────────►  │  mcp_server.py   │
│  (Claude,   │                    │  (Python + MCP)  │
│   GPT, etc) │                    │                   │
└─────────────┘                    │  CDP session     │
                                   │  ┌─────────────┐ │
                                   │  │ CloakBrowser │ │
                                   │  │  (Chromium)  │ │
                                   │  └─────────────┘ │
                                   └──────────────────┘
```

The server runs as a stdio MCP transport. Each AI agent tool call translates to a CDP command sent to the CloakBrowser page.

---

## License

MIT (code) — see [LICENSE](./LICENSE).  

CloakBrowser binary is subject to its own license (see [BINARY-LICENSE.md](https://github.com/czfrank/cloakbrowser/blob/master/BINARY-LICENSE.md)).
