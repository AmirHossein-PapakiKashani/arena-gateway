# Verification — 2026-11-08

The repaired integration uses real Arena website inference, with Gemini CLI
executing tools locally. No project Git repository was present; original source
files were copied to `.backups/2026-11-08-before-fix/` before production edits.

## Automated checks

Command executed in the project environment:

```text
rtk proxy .venv/Scripts/python.exe -X utf8 -m unittest discover -s tests -t . -v
Ran 19 tests in 5.251s
OK
```

Before repairs, 8 of the original 9 regression tests failed. Additional tests
were added for malformed Windows JSON, assistant-only extraction, full prompt
forwarding, isolated browser requests, real Arena stream framing, truncated and
failed provider streams, and Gemini SDK keepalives. Browser fixtures intercept
HTTP responses locally; these are separate from the real live tests below.
All top-level Python modules also passed `py_compile`.

## Real Gemini CLI acceptance tests

Gemini CLI version: 0.67.0. Arena Chrome profile was authenticated by the user.

1. `gpt-6-luna-max`, session `bb0395ec-7f66-4055-b05e-ae75e55d69f0`:
   actual `write_file` tool use succeeded, creating
   `tests/live_workspace/arena-proof-final.txt` with `ARENA_FINAL_LOOP_1108`.
   The tool result went back to Arena and the real model returned that marker.
   CLI exit status 0, reported `tool_calls: 1`, duration 133639 ms.
2. `gemini-4-argon-high`, session `680eaacf-4a8a-43a6-9e8b-eba363840417`:
   actual `read_file` tool use succeeded on a local random challenge file.
   Its contents were not in the prompt. The final model answer matched the
   random file exactly. CLI exit status 0, reported `tool_calls: 1`, duration
   30694 ms. Disk contents were independently checked afterward.
3. Gemini CLI `--list-models` displayed the 16 live Arena Direct models, with
   explicit custom model definitions. The Windows launcher
   `rtk proxy cmd /c arena.cmd --list-models` also exited 0.

The GPT test did not invoke `read_file` despite requesting both operations;
the separate Argon random-file test independently proves reading and returning
real local results. No claim is made that all 16 models were individually tested.

## Current state and limits

`GET /health` returned `inference: arena-browser`, `synthetic_fallback: false`,
`cdp_connected: true`, `last_error: null`, `last_model: gemini-4-argon-high`.
The gateway remains on `127.0.0.1:8000`, Chrome CDP on port 9222.

GPT-5.5 was absent from the actual Direct picker for this account during the
test. The old leaderboard JSON is not used to promise model availability.
SSE sends empty JSON keepalives and a completed response, rather than individual
tokens. Token counts remain estimates. Login, quotas, and website changes are
external dependencies. Existing global Gemini agent-definition/MCP warnings
were observed during startup; they did not prevent the successful tests.

Graph evidence at the start was dated 2026-10-08 and marked metadata changed.
Material source files were read directly; graph coverage was not treated as
proof of current behavior. This report records command and live-run evidence.
