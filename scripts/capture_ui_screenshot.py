"""Capture a clean screenshot of the local Prefect UI via the DevTools protocol.

Chrome's one-shot ``--screenshot`` flag cannot dismiss the community modal that
Prefect shows on first load, so this helper drives the browser properly: it
removes the modal overlay, waits for the flow-run graph to paint, then captures
the viewport.
"""

from __future__ import annotations

import asyncio
import base64
import json
import sys
import urllib.request
from pathlib import Path

import websockets

DEBUG_PORT = 9222


async def capture(
    url: str, out_path: Path, wait_seconds: float = 6.0, click_label: str | None = None
) -> None:
    targets = json.loads(
        urllib.request.urlopen(f"http://127.0.0.1:{DEBUG_PORT}/json", timeout=10).read()
    )
    page = next((target for target in targets if target["type"] == "page"), None)
    if page is None:
        raise RuntimeError("no page target found - is Chrome running with --remote-debugging-port?")

    async with websockets.connect(page["webSocketDebuggerUrl"], max_size=50 * 1024 * 1024) as ws:
        message_id = 0

        async def call(method: str, params: dict | None = None) -> dict:
            nonlocal message_id
            message_id += 1
            await ws.send(json.dumps({"id": message_id, "method": method, "params": params or {}}))
            while True:
                response = json.loads(await ws.recv())
                if response.get("id") == message_id:
                    return response

        await call("Page.enable")
        await call("Runtime.enable")
        await call("Page.navigate", {"url": url})
        await asyncio.sleep(wait_seconds)

        cleanup = """
        (() => {
          const kill = [];
          document.querySelectorAll('div[role="dialog"], [aria-modal="true"]').forEach(n => kill.push(n));
          document.querySelectorAll('div').forEach(n => {
            const cls = n.className && n.className.toString ? n.className.toString() : '';
            if (cls.includes('fixed') && cls.includes('inset-0') && cls.includes('z-')) kill.push(n);
          });
          let removed = 0;
          kill.forEach(n => { if (n && n.parentNode) { n.parentNode.removeChild(n); removed++; } });
          document.body.style.overflow = 'auto';
          return removed;
        })()
        """
        removed = await call("Runtime.evaluate", {"expression": cleanup, "returnByValue": True})
        print("overlays removed:", removed.get("result", {}).get("result", {}).get("value"))

        if click_label:
            click = """
            (() => {
              const label = %s;
              const target = [...document.querySelectorAll('button, a')]
                 .find(node => node.textContent.trim() === label);
              if (target) { target.click(); return 'clicked'; }
              return 'not found';
            })()
            """ % json.dumps(click_label)
            outcome = await call("Runtime.evaluate", {"expression": click, "returnByValue": True})
            print("tab:", outcome.get("result", {}).get("result", {}).get("value"))

        await asyncio.sleep(2.0)
        shot = await call("Page.captureScreenshot", {"format": "png", "captureBeyondViewport": False})
        data = shot["result"]["data"]
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(base64.b64decode(data))
        print("saved", out_path, out_path.stat().st_size, "bytes")


if __name__ == "__main__":
    url_argument = sys.argv[1]
    destination = Path(sys.argv[2])
    click_argument = sys.argv[3] if len(sys.argv) > 3 else None
    asyncio.run(capture(url_argument, destination, click_label=click_argument))
