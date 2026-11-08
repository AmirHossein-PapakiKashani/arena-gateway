# Arena Gateway

Run Gemini CLI's tools and agent loop on your computer, with model inference from
the existing signed-in Chrome session on **arena.ai**.

## Start

From the directory you want the agent to work in:

```powershell
E:\arena_gateway\arena.cmd
```

Choose a model from Arena's live Direct menu. Gemini CLI opens with that model;
use `/model` to switch to another available model. The launcher starts the local
gateway and Arena Chrome profile when needed. Sign in to Arena in that Chrome
profile if prompted. It stores workspace configuration in `.gemini/settings.json`
and saves the original as `.gemini/settings.before-arena.json` before changing an
existing file. Global Gemini settings are not rewritten.

```powershell
E:\arena_gateway\arena.cmd --list-models
E:\arena_gateway\arena.cmd --model gemini-4-argon-high
E:\arena_gateway\arena.cmd --model gpt-6-luna-max --workspace E:\my-project
```

Only models currently selectable in **Direct** are offered. The old leaderboard
file `arena_models.json` is not used for routing: ranking entries, retired models,
and image/agent-only models do not imply Direct access. A missing model returns
an explicit error; the gateway never silently selects a substitute. Model access
and Arena account limits can change.

## How it works

1. Gemini CLI sends the selected model, system instructions, history, and tool
   schemas to `http://127.0.0.1:8000/v1beta`.
2. The gateway opens a fresh Direct chat inside the persistent Chrome context,
   verifies the visible model selection, and sends the entire transcript.
3. It observes the response stream produced by that normal browser request.
   It reads raw model text because Arena's Markdown rendering can hide XML calls.
4. Tool calls become Gemini `functionCall` parts. Gemini CLI executes its local
   tools with its normal approval policy, then sends actual tool results back
   through the gateway for the next model decision.

The gateway does not execute CLI tools, generate replacement answers, or invent
successful file operations. `MOCK_ARENA=true` fails explicitly. `FALLBACK_MOCK` is
retained only for configuration compatibility and cannot enable synthetic output.
Each request carries full history into a fresh browser chat, so separate CLI
sessions cannot inherit another session's conversation. Browser requests are
serialized. Only model metadata is cached, for five minutes; inference is not
cached. The launcher explicitly refreshes metadata each time it starts.

## Requirements and limits

- Python 3.12+, the project dependencies (`uv sync`), Google Chrome, and Gemini
  CLI on PATH. Verified here with Gemini CLI 0.67.0 and Playwright 1.63.0.
- The default persistent Chrome profile is `%USERPROFILE%\.arena_chrome_profile`,
  with local remote debugging on port 9222. No cookies are exported. Complete
  login or security verification yourself when Arena requests it.
- Arena website inference is not an official model API. Website changes, model
  availability, input limits, and account quotas can interrupt the integration.
  The adapter observes the existing browser requests; it does not replay private
  APIs or bypass access controls.
- The Gemini adapter supports text, declared functions, and function results.
  It rejects unsupported image/file parts. Responses use SSE with empty JSON
  keepalives, then the completed response. They are not incremental token output.
  Errors remain explicit HTTP errors or Google-compatible stream errors.
- `countTokens` is a byte-based estimate; Arena exposes no tokenizer endpoint.
  Gemini CLI's displayed generic context limits are not verified Arena limits.
  JSON MIME/schema requests reach the actual model rather than a local classifier.

The CLI process sends inference to localhost, with explicit proxy environment
variables removed for that child process because Node proxy agents can ignore
`NO_PROXY`. Chrome continues to use the existing Windows/Clash network setup.

## Diagnostics and checks

```powershell
curl.exe http://127.0.0.1:8000/health
curl.exe http://127.0.0.1:8000/api/cdp/status
curl.exe "http://127.0.0.1:8000/v1beta/models?refresh=true"
python -m unittest discover -s tests -t . -v
python scripts/live_probe.py --model gemini-4-argon-high
```

`uv sync` also installs the `httpx` test dependency. Browser fixture tests use installed Chrome on
Windows. Live probes submit only the prompt supplied on the command line and
consume normal Arena usage. Local startup logs are in `.runtime/gateway.log`.
The API also retains the existing nonstreaming OpenAI endpoint and Studio UI at
`http://127.0.0.1:8000/ui`. The API listener binds to loopback only.

Typical error reasons: `CDP_UNAVAILABLE`, `ARENA_AUTH_REQUIRED`,
`ARENA_MODEL_UNAVAILABLE`, `ARENA_VERIFICATION_REQUIRED`, `ARENA_TIMEOUT`,
`ARENA_INVALID_TOOL_CALL`, and `ARENA_TRUNCATED_STREAM`. A failed tool call is
returned to the model as a failure; there is no fixed "file created" response.

Original gateway files are preserved in `.backups/2026-11-08-before-fix/` in this
workspace. No project Git repository was present at the start of this repair.
