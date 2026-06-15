"""
MCP Client Test — Verifies the browser-mcp MCP server works via stdio protocol.
Opens Baidu, searches "late-cli", keeps browser alive.
"""

import json
import subprocess
import sys
import time

MCP_SERVER = r"C:\Users\qxm22\AppData\Roaming\late\skills\browser-mcp\mcp_server.py"
PYTHON = r"D:\program_file\anaconda\envs\package\python.exe"


def send_msg(proc, msg):
    """Send a JSON-RPC message to the MCP server process."""
    line = json.dumps(msg)
    proc.stdin.write(line + "\n")
    proc.stdin.flush()
    print(f"  >>> {msg.get('method', '?')} (id={msg.get('id')})")


def read_response(proc, timeout=60):
    """Read one JSON line from the MCP server's stdout."""
    import select
    import os
    start = time.time()
    while time.time() - start < timeout:
        # Check if data is available
        line = proc.stdout.readline()
        if line:
            try:
                resp = json.loads(line.strip())
                print(f"  <<< {resp.get('id', '?')}: {json.dumps(resp, ensure_ascii=False)[:200]}")
                return resp
            except json.JSONDecodeError:
                print(f"  <<< (non-json) {line.strip()[:100]}")
                continue
    print("  !!! Timeout waiting for response")
    return None


def main():
    print("=" * 60)
    print("MCP Client Test — browser-mcp")
    print("=" * 60)

    # Start MCP server process
    print("\n1️⃣  Starting MCP server...")
    proc = subprocess.Popen(
        [PYTHON, MCP_SERVER],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )
    print(f"   PID: {proc.pid}")

    # Step 1: Initialize
    print("\n2️⃣  Sending initialize...")
    send_msg(proc, {
        "jsonrpc": "2.0", "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "test-client", "version": "1.0"},
        },
    })
    resp = read_response(proc)
    assert resp and "result" in resp, "Initialize failed!"
    print("   ✅ Server initialized!")

    # Send initialized notification (no response expected)
    send_msg(proc, {
        "jsonrpc": "2.0", "id": 2,
        "method": "notifications/initialized",
        "params": {},
    })
    time.sleep(0.5)

    # Step 2: Navigate to Baidu
    print("\n3️⃣  Navigating to https://www.baidu.com ...")
    send_msg(proc, {
        "jsonrpc": "2.0", "id": 3,
        "method": "tools/call",
        "params": {
            "name": "navigate",
            "arguments": {"url": "https://www.baidu.com"},
        },
    })
    resp = read_response(proc, timeout=60)
    if resp and "result" in resp:
        text = resp["result"]["content"][0]["text"]
        print(f"   ✅ {text}")
    else:
        print(f"   ❌ navigate failed: {resp}")

    # Step 3: Type text
    print("\n4️⃣  Typing 'late-cli' into search box...")
    send_msg(proc, {
        "jsonrpc": "2.0", "id": 4,
        "method": "tools/call",
        "params": {
            "name": "type_text",
            "arguments": {"selector": "#kw", "text": "late-cli"},
        },
    })
    resp = read_response(proc, timeout=30)
    if resp and "result" in resp:
        text = resp["result"]["content"][0]["text"]
        print(f"   ✅ {text}")
    else:
        print(f"   ❌ type_text failed: {resp}")

    # Step 4: Snapshot to find search button ref
    print("\n5️⃣  Taking snapshot to find search button...")
    send_msg(proc, {
        "jsonrpc": "2.0", "id": 5,
        "method": "tools/call",
        "params": {
            "name": "snapshot",
            "arguments": {},
        },
    })
    resp = read_response(proc, timeout=30)
    if resp and "result" in resp:
        text = resp["result"]["content"][0]["text"]
        print(f"   ✅ Snapshot taken")
        print(f"   {text[:300]}...")
    else:
        print(f"   ❌ snapshot failed: {resp}")

    # Use execute_js to click search button (direct JS fallback)
    print("\n6️⃣  Clicking search button via execute_js...")
    send_msg(proc, {
        "jsonrpc": "2.0", "id": 6,
        "method": "tools/call",
        "params": {
            "name": "execute_js",
            "arguments": {"code": "document.querySelector('#su').click()"},
        },
    })
    resp = read_response(proc, timeout=30)
    if resp and "result" in resp:
        text = resp["result"]["content"][0]["text"]
        print(f"   ✅ {text}")
    else:
        print(f"   ⚠️ execute_js click failed (search may still work via Enter): {resp}")

    # Step 7: Get page title via execute_js
    print("\n7️⃣  Getting page title...")
    send_msg(proc, {
        "jsonrpc": "2.0", "id": 7,
        "method": "tools/call",
        "params": {
            "name": "execute_js",
            "arguments": {"code": "document.title"},
        },
    }

    # Done
    print("\n" + "=" * 60)
    print("✅ Test complete! Browser is staying open.")
    print("   Close the browser window manually when done.")
    print("   Press Ctrl+C to stop the server.")
    print("=" * 60)

    # Keep the process alive — read stderr for any errors
    try:
        while True:
            line = proc.stderr.readline()
            if line:
                print(f"   [stderr] {line.strip()}")
            time.sleep(0.1)
    except KeyboardInterrupt:
        print("\n   Shutting down...")
        proc.terminate()


if __name__ == "__main__":
    main()
