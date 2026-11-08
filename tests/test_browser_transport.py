import unittest
import json
from unittest.mock import AsyncMock, patch

from playwright.async_api import async_playwright
from arena_gateway.cdp_client import ArenaCDPClient
from arena_gateway.config import Settings


class BrowserTransportTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.pw = await async_playwright().start()
        self.browser = await self.pw.chromium.launch(
            executable_path="C:/Program Files/Google/Chrome/Application/chrome.exe", headless=True)
        self.page = await self.browser.new_page()
        self.client = ArenaCDPClient(Settings())
        self.client._page = self.page

    async def asyncTearDown(self):
        await self.browser.close()
        await self.pw.stop()

    async def test_response_keeps_entire_tool_call_and_excludes_user_bubble(self):
        await self.page.set_content('''
            <div class="prose">Before<pre><code>&lt;tool_call&gt;{"name":"read_file","arguments":{}}&lt;/tool_call&gt;</code></pre>After</div>
            <div class="self-end"><div class="prose">User bubble after model</div></div>''')
        blocks = await self.client._get_current_bot_blocks("unrelated")
        self.assertEqual(len(blocks), 1)
        self.assertIn("<tool_call>", blocks[0])
        self.assertTrue(blocks[0].endswith("After"))

    async def test_user_question_about_limits_does_not_become_transport_error(self):
        await self.page.set_content('<div class="self-end"><div class="prose">Explain rate limits and security verification.</div></div>')
        await self.client._check_access()

    async def test_full_prompt_is_sent_and_no_answer_is_reused_across_requests(self):
        html = '''<textarea placeholder="Ask anything"></textarea>
          <button aria-haspopup="dialog" id="model" onclick="document.querySelector('#picker').hidden=false">Max</button>
          <div id="picker" hidden><input placeholder="Search models">
          <div role="option" onclick="document.querySelector('#model').textContent='fixture-model'; document.querySelector('#picker').hidden=true">fixture-model</div></div>
          <button aria-label="Send message" onclick="fetch('https://arena.ai/nextjs-api/stream/create-evaluation',{method:'POST',body:document.querySelector('textarea').value})">Send</button>'''
        async def stream(route):
            text = "answer:" + route.request.post_data
            await route.fulfill(status=200, content_type="text/event-stream", headers={"Access-Control-Allow-Origin": "*"},
                                body="a0:" + json.dumps(text) + '\nad:{"finishReason":"stop"}\n')
        await self.page.route("https://arena.ai/nextjs-api/stream/create-evaluation", stream)
        async def fresh():
            await self.page.set_content(html)
        with patch.object(self.client, "_fresh_chat", side_effect=fresh):
            first = await self.client.send_chat_message("[System Instructions]\ntools\n[User]\nFIRST", "fixture-model")
            self.assertIn("[System Instructions]\ntools", first)
            second = await self.client.send_chat_message("[User]\nSECOND", "fixture-model")
        self.assertIn("SECOND", second)
        self.assertNotIn("FIRST", second)


if __name__ == "__main__":
    unittest.main()
