import json
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from arena_gateway import server
from arena_gateway.config import Settings
from arena_gateway.cdp_client import ArenaCDPClient
from arena_gateway.cdp_client import ArenaError
from arena_gateway.prompt_injection import parse_response_for_tools


class GatewayTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=server.app, raise_app_exceptions=False),
            base_url="http://test",
        )

    async def asyncTearDown(self):
        await self.client.aclose()

    async def test_tool_result_returns_to_arena_for_next_decision(self):
        body = {"contents": [
            {"role": "user", "parts": [{"text": "Read then update my file"}]},
            {"role": "model", "parts": [{"functionCall": {"name": "read_file", "args": {"path": "demo.py"}}}]},
            {"role": "user", "parts": [{"functionResponse": {"name": "read_file", "response": {"error": "File not found"}}}]},
        ]}
        with patch.object(server.cdp_client, "send_chat_message", AsyncMock(return_value="The file does not exist.")) as send:
            response = await self.client.post("/v1beta/models/gpt-5.5:generateContent", json=body)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["candidates"][0]["content"]["parts"][0]["text"], "The file does not exist.")
        self.assertIn("File not found", send.call_args.args[0])
        self.assertIn("read_file", send.call_args.args[0])

    async def test_system_instruction_and_json_schema_reach_arena(self):
        body = {"systemInstruction": {"parts": [{"text": "Use the actual repository facts"}]},
                "contents": [{"role": "user", "parts": [{"text": "Classify this issue"}]}],
                "generationConfig": {"responseMimeType": "application/json", "responseSchema": {"type": "OBJECT", "properties": {"answer": {"type": "STRING"}}}}}
        with patch.object(server.cdp_client, "send_chat_message", AsyncMock(return_value='{"answer":"actual"}')) as send:
            response = await self.client.post("/v1beta/models/gpt-5.5:generateContent", json=body)
        self.assertEqual(response.json()["candidates"][0]["content"]["parts"][0]["text"], '{"answer":"actual"}')
        self.assertIn("Use the actual repository facts", send.call_args.args[0])
        self.assertIn("answer", send.call_args.args[0])

    async def test_invalid_windows_tool_json_gets_model_correction(self):
        invalid = r'<tool_call>{"name":"write_file","arguments":{"file_path":"E:\arena\proof.txt","content":"ok"}}</tool_call>'
        valid = '<tool_call>{"name":"write_file","arguments":{"file_path":"E:/arena/proof.txt","content":"ok"}}</tool_call>'
        body = {"contents": [{"role": "user", "parts": [{"text": "Create proof"}]}],
                "tools": [{"functionDeclarations": [{"name": "write_file", "parameters": {"type": "OBJECT"}}]}]}
        with patch.object(server.cdp_client, "send_chat_message", AsyncMock(side_effect=[invalid, valid])) as send:
            response = await self.client.post("/v1beta/models/gpt-6-luna-max:generateContent", json=body)
        self.assertEqual(response.status_code, 200)
        part = response.json()["candidates"][0]["content"]["parts"][0]
        self.assertIn("functionCall", part)
        self.assertEqual(part["functionCall"]["args"]["file_path"], "E:/arena/proof.txt")
        self.assertEqual(send.await_count, 2)

    async def test_stream_has_real_content_and_no_fabricated_thoughts(self):
        body = {"contents": [{"role": "user", "parts": [{"text": "hello"}]}]}
        with patch.object(server.cdp_client, "send_chat_message", AsyncMock(return_value="From Arena")):
            response = await self.client.post("/v1beta/models/gpt-5.5:streamGenerateContent?alt=sse", json=body)
        events = [json.loads(x[6:]) for x in response.text.splitlines() if x.startswith("data: ")]
        self.assertEqual(events[-1]["candidates"][0]["content"]["parts"], [{"text": "From Arena"}])
        self.assertFalse(any(p.get("thought") for e in events for c in e.get("candidates", []) for p in c["content"]["parts"]))

    async def test_stream_reports_provider_error_with_keepalive(self):
        body = {"contents": [{"role": "user", "parts": [{"text": "hello"}]}]}
        with patch.object(server.cdp_client, "send_chat_message", AsyncMock(side_effect=ArenaError("Sign in", "ARENA_AUTH_REQUIRED", 401))):
            response = await self.client.post("/v1beta/models/gpt-6-luna-max:streamGenerateContent?alt=sse", json=body)
        self.assertTrue(response.text.startswith('data: {"candidates": []}\n\n'))
        event = json.loads(response.text.split("\n\n")[-1])
        self.assertEqual(event["error"]["code"], 401)
        self.assertNotIn("candidates", event)

    async def test_bad_json_is_a_client_error(self):
        with patch.object(server.cdp_client, "send_chat_message", AsyncMock(return_value="unexpected dispatch")):
            response = await self.client.post("/v1beta/models/gpt-5.5:generateContent", content="{", headers={"content-type": "application/json"})
        self.assertEqual(response.status_code, 400)

    async def test_count_tokens_depends_on_input(self):
        short = await self.client.post("/v1beta/models/gpt-5.5:countTokens", json={"contents": [{"parts": [{"text": "Hi"}]}]})
        long = await self.client.post("/v1beta/models/gpt-5.5:countTokens", json={"contents": [{"parts": [{"text": "word " * 1000}]}]})
        self.assertGreater(long.json()["totalTokens"], short.json()["totalTokens"])

    async def test_openai_preserves_tool_history(self):
        body = {"model": "gpt-5.5", "messages": [
            {"role": "user", "content": "Read file"},
            {"role": "assistant", "content": None, "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "read_file", "arguments": "{}"}}]},
            {"role": "tool", "tool_call_id": "c1", "content": "file data"}]}
        with patch.object(server.cdp_client, "send_chat_message", AsyncMock(return_value="Read actual data")) as send:
            response = await self.client.post("/v1/chat/completions", json=body)
        self.assertEqual(response.status_code, 200)
        self.assertIn("read_file", send.call_args.args[0])
        self.assertIn("file data", send.call_args.args[0])

    async def test_connection_failure_does_not_synthesize_answer(self):
        client = ArenaCDPClient(Settings(fallback_mock=True))
        with patch.object(client, "connect", AsyncMock(side_effect=ConnectionError("CDP down"))):
            with self.assertRaises(Exception):
                await client.send_chat_message("write a file", model_name="gpt-5.5")


class ToolTests(unittest.TestCase):
    def test_all_parallel_calls_and_gemini_args_are_preserved(self):
        raw = '<tool_call>{"name":"read_file","arguments":{"path":"a"}}</tool_call>\n<tool_call>{"name":"read_file","args":{"path":"b"}}</tool_call>'
        text, calls = parse_response_for_tools(raw)
        self.assertEqual(text, "")
        self.assertEqual([json.loads(c["function"]["arguments"])["path"] for c in calls], ["a", "b"])

    def test_malformed_call_is_not_executed(self):
        raw = '<tool_call>{"name":"write_file","arguments":"bad"}</tool_call>'
        text, calls = parse_response_for_tools(raw)
        self.assertIsNone(calls)
        self.assertEqual(text, raw)


if __name__ == "__main__":
    unittest.main()
