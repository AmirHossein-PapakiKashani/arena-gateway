"""Inspect only the public response format for a harmless Arena test prompt."""
import asyncio
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from arena_gateway.cdp_client import ArenaCDPClient
from arena_gateway.config import Settings


async def main():
    client = ArenaCDPClient(Settings())
    pending = []
    async def observe(response):
        if response.request.method != "POST":
            return
        content_type = response.headers.get("content-type", "")
        if "stream" not in content_type and "text/plain" not in content_type:
            return
        print("STREAM", response.url.split("?")[0], response.status, content_type, flush=True)
        try:
            print("RESPONSE_BYTES", (await response.body()).decode("utf8")[:5000], flush=True)
        except Exception as exc:
            print(type(exc).__name__, flush=True)
    try:
        await client._fresh_chat()
        await client._select_model("gemini-3.8-flash-high")
        client._page.on("response", lambda response: pending.append(asyncio.create_task(observe(response))))
        await client._page.locator("textarea[placeholder]").filter(visible=True).first.fill("Reply only with the word STREAM_PROBE_1108.")
        await client._page.get_by_role("button", name="Send message", exact=True).click()
        await asyncio.sleep(15)
        await asyncio.wait_for(asyncio.gather(*pending), timeout=20)
        print("RENDER", await client._get_current_bot_blocks(), flush=True)
    finally:
        await client.close()


asyncio.run(main())
