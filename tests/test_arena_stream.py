import unittest
from arena_gateway.cdp_client import parse_arena_stream, ArenaError


class ArenaStreamTests(unittest.TestCase):
    def test_actual_arena_stream_reconstructs_raw_xml(self):
        stream = 'a2:[{"type":"heartbeat"}]\na0:"<tool_call>"\na0:"{\\"name\\":\\"read_file\\",\\"arguments\\":{}}"\na0:"</tool_call>"\nad:{"finishReason":"stop"}\n'
        self.assertEqual(parse_arena_stream(stream), '<tool_call>{"name":"read_file","arguments":{}}</tool_call>')

    def test_truncated_stream_is_rejected(self):
        with self.assertRaises(ArenaError):
            parse_arena_stream('a0:"partial"\n')

    def test_provider_error_is_not_an_answer(self):
        with self.assertRaises(ArenaError):
            parse_arena_stream('a3:"Provider failed"\nad:{"finishReason":"error"}\n')
