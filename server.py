import asyncio
import base64
import json
import re
import time
import uuid
from pathlib import Path
from typing import Any
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse, HTMLResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from arena_gateway.config import Settings
from arena_gateway.prompt_injection import inject_tools_into_prompt, parse_response_for_tools
from arena_gateway.cdp_client import ArenaCDPClient, ArenaError
from arena_gateway.compaction import compact_conversation
from arena_gateway.file_service import generate_diff, write_workspace_file
from arena_gateway.text_extractor import extract_text_from_bytes

settings = Settings()
cdp_client = ArenaCDPClient(settings=settings)
app = FastAPI(title="Arena Gateway", version="0.2.0")

@app.exception_handler(ArenaError)
async def arena_error_handler(request: Request, exc: ArenaError):
    status = {400: "INVALID_ARGUMENT", 401: "UNAUTHENTICATED", 403: "PERMISSION_DENIED", 404: "NOT_FOUND", 429: "RESOURCE_EXHAUSTED", 504: "DEADLINE_EXCEEDED"}.get(exc.status_code, "UNAVAILABLE")
    return JSONResponse(status_code=exc.status_code, content={"error": {"code": exc.status_code, "status": status, "message": str(exc), "details": [{"reason": exc.code}]}}, headers={"Cache-Control": "no-store"})


STATIC_DIR = Path(__file__).parent / "static"
STATIC_DIR.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
INDEX_HTML = STATIC_DIR / "index.html"

class DiffRequest(BaseModel):
    workspace: str
    path: str
    content: str | list[dict[str, Any]] | None = None
    tool_calls: list[dict[str, Any]] | None = None
    tool_call_id: str | None = None

class WriteFileRequest(BaseModel):
    workspace: str
    path: str
    content: str | list[dict[str, Any]] | None = None
    tool_calls: list[dict[str, Any]] | None = None
    tool_call_id: str | None = None

class CompactRequest(BaseModel):
    messages: list[dict[str, Any]]
    target_model: str
    active_mode: str = "ask"

class ExtractAttachmentRequest(BaseModel):
    filename: str
    content: str | list[dict[str, Any]] | None = None
    tool_calls: list[dict[str, Any]] | None = None
    tool_call_id: str | None = None
    is_base64: bool = False

@app.get("/", response_class=HTMLResponse)
@app.get("/ui", response_class=HTMLResponse)
async def serve_ui():
    if INDEX_HTML.exists():
        return FileResponse(INDEX_HTML)
    return HTMLResponse("<!DOCTYPE html><html><head><title>Arena Gateway Studio</title></head><body><h1>Arena Gateway Studio</h1><p>UI loading...</p></body></html>")

@app.post("/api/files/diff")
async def api_diff_file(req: DiffRequest):
    try:
        return generate_diff(req.workspace, req.path, req.content)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/api/files/write")
async def api_write_file(req: WriteFileRequest):
    try:
        return write_workspace_file(req.workspace, req.path, req.content)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/api/context/compact")
async def api_compact_context(req: CompactRequest):
    try:
        return compact_conversation(req.messages, req.target_model, req.active_mode)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/api/attachments/extract")
async def api_extract_attachment(req: ExtractAttachmentRequest):
    try:
        if req.is_base64:
            raw_bytes = base64.b64decode(req.content)
        else:
            raw_bytes = req.content.encode("utf-8")
        return extract_text_from_bytes(req.filename, raw_bytes)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

def detect_project_stack(p: Path) -> str:
    try:
        if not p.exists() or not p.is_dir():
            return "General"
        if any(p.glob("*.csproj")) or any(p.glob("*.sln")):
            return ".NET 9"
        if (p / "pyproject.toml").exists() or (p / "requirements.txt").exists() or any(p.glob("*.py")):
            return "Python"
        if (p / "package.json").exists():
            return "Node / TS"
        if any(p.glob("*.go")):
            return "Go"
        if (p / "Cargo.toml").exists():
            return "Rust"
    except Exception:
        pass
    return "General"

@app.get("/api/workspace/drives")
async def api_get_workspace_drives():
    import string
    import os
    drives = []
    for letter in string.ascii_uppercase:
        drive_path = f"{letter}:\\"
        if os.path.exists(drive_path):
            drives.append({"drive": f"{letter}:", "path": drive_path})
    
    shortcuts = []
    home = Path.home()
    if home.exists():
        shortcuts.append({"name": "User Home", "path": str(home)})
        desktop = home / "Desktop"
        if desktop.exists():
            shortcuts.append({"name": "Desktop", "path": str(desktop)})
        docs = home / "Documents"
        if docs.exists():
            shortcuts.append({"name": "Documents", "path": str(docs)})
    
    scratch = Path("C:/Users/User/.gemini/antigravity/scratch")
    if scratch.exists():
        shortcuts.append({"name": "Scratch", "path": str(scratch)})

    return {"drives": drives, "shortcuts": shortcuts}

@app.get("/api/workspace/list-dirs")
async def api_list_workspace_dirs(path: str = ""):
    import os
    target_path = path.strip() if path else ""
    if not target_path:
        default_drive = "E:\\" if os.path.exists("E:\\") else "C:\\"
        target_path = default_drive
    
    p = Path(target_path)
    if not p.exists() or not p.is_dir():
        p = Path.home()
    
    resolved_path = str(p.resolve())
    parent_path = str(p.parent.resolve()) if p.parent and p.parent != p else None

    dirs = []
    skip_names = {
        "$recycle.bin", "system volume information", "msocache",
        "recovery", ".git", "node_modules", "__pycache__", ".venv", "venv", "bin", "obj"
    }
    try:
        for item in p.iterdir():
            try:
                if item.is_dir() and item.name.lower() not in skip_names and not item.name.startswith("."):
                    stack = detect_project_stack(item)
                    dirs.append({
                        "name": item.name,
                        "path": str(item.resolve()),
                        "stack": stack
                    })
            except (PermissionError, OSError):
                continue
    except (PermissionError, OSError) as e:
        return {"current_path": resolved_path, "parent_path": parent_path, "dirs": [], "error": str(e)}

    dirs.sort(key=lambda x: x["name"].lower())
    return {
        "current_path": resolved_path,
        "parent_path": parent_path,
        "dirs": dirs[:120]
    }

class ValidatePathRequest(BaseModel):
    path: str

@app.post("/api/workspace/validate-path")
async def api_validate_workspace_path(req: ValidatePathRequest):
    raw = req.path.strip()
    p = Path(raw)
    if not p.exists() or not p.is_dir():
        return {"valid": False, "message": "پوشه مشخص‌شده در سیستم وجود ندارد."}
    
    stack = detect_project_stack(p)
    return {
        "valid": True,
        "path": str(p.resolve()),
        "name": p.name or "Project",
        "stack": stack
    }

@app.post("/api/workspace/browse")
async def api_browse_workspace(mock_path: str | None = None):
    import os
    import sys
    if mock_path or "pytest" in sys.modules or os.environ.get("TESTING"):
        chosen = mock_path or str(Path.cwd())
        p = Path(chosen)
        return {"status": "success", "path": str(p.resolve()), "name": p.name, "stack": detect_project_stack(p)}

    def _open_folder_dialog():
        import subprocess
        ps_script = (
            "Add-Type -AssemblyName System.Windows.Forms; "
            "[System.Windows.Forms.Application]::EnableVisualStyles(); "
            "$f = New-Object System.Windows.Forms.FolderBrowserDialog; "
            "$f.Description = 'پوشه پروژه را انتخاب کنید'; "
            "$f.ShowNewFolderButton = $true; "
            "$res = $f.ShowDialog(); "
            "if ($res -eq [System.Windows.Forms.DialogResult]::OK) { "
            "    Write-Output $f.SelectedPath "
            "}"
        )
        try:
            proc = subprocess.run(
                ["powershell", "-Sta", "-NoProfile", "-Command", ps_script],
                capture_output=True,
                text=True,
                timeout=45
            )
            chosen = proc.stdout.strip()
            if chosen and Path(chosen).exists():
                p = Path(chosen)
                return {"status": "success", "path": str(p.resolve()), "name": p.name, "stack": detect_project_stack(p)}
        except Exception as e:
            print(f"Browse dialog error: {e}")
        return {"status": "cancelled", "path": None, "name": None, "stack": None}

    return await asyncio.to_thread(_open_folder_dialog)

class ChatMessage(BaseModel):

    role: str
    content: str | list[dict[str, Any]] | None = None
    tool_calls: list[dict[str, Any]] | None = None
    tool_call_id: str | None = None

class ChatCompletionRequest(BaseModel):
    model: str = Field(default=settings.default_model)
    messages: list[ChatMessage]
    tools: list[dict[str, Any]] | None = None
    stream: bool = False
    mode: str = Field(default="code")
    workspace: dict[str, Any] | None = None

@app.get("/health")
async def health():
    return {"status": "ok", "inference": "arena-browser", "synthetic_fallback": False, "cdp_connected": cdp_client.is_connected, "last_error": cdp_client.last_error, "last_model": cdp_client.last_model}

@app.get("/api/cdp/status")
async def api_cdp_status():
    import urllib.request
    import json
    def _check():
        try:
            req = urllib.request.Request("http://127.0.0.1:9222/json/version", headers={"User-Agent": "ArenaGateway"})
            with urllib.request.urlopen(req, timeout=1.5) as resp:
                data = json.loads(resp.read().decode())
                return {"connected": True, "browser": data.get("Browser", "Chrome"), "port": 9222}
        except Exception as e:
            return {"connected": False, "error": str(e), "port": 9222}
    return await asyncio.to_thread(_check)

@app.post("/api/cdp/launch")
async def api_cdp_launch():
    import subprocess
    import os

    candidates = [
        Path(os.environ.get("PROGRAMFILES", "C:\\Program Files")) / "Google" / "Chrome" / "Application" / "chrome.exe",
        Path(os.environ.get("PROGRAMFILES(X86)", "C:\\Program Files (x86)")) / "Google" / "Chrome" / "Application" / "chrome.exe",
        Path.home() / "AppData" / "Local" / "Google" / "Chrome" / "Application" / "chrome.exe",
    ]
    chrome_path = next((p for p in candidates if p.exists()), None)
    if not chrome_path:
        raise HTTPException(status_code=404, detail="Google Chrome executable not found on system.")

    profile_dir = Path.home() / ".arena_chrome_profile"
    profile_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        str(chrome_path),
        "--remote-debugging-port=9222",
        f"--user-data-dir={profile_dir}",
        "https://arena.ai/text/direct"
    ]
    try:
        creation_flag = subprocess.DETACHED_PROCESS if os.name == 'nt' else 0
        subprocess.Popen(cmd, creationflags=creation_flag)
        return {"status": "launched", "port": 9222, "profile": str(profile_dir)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to launch Chrome: {e}")



# -------------------------------------------------------------
# OpenAI-compatible API Endpoint
# -------------------------------------------------------------
@app.post("/v1/chat/completions")
async def chat_completions(request: ChatCompletionRequest):
    if request.stream:
        raise HTTPException(status_code=400, detail="Streaming is not yet supported in basic tier")

    raw_messages = [m.model_dump(exclude_none=True) for m in request.messages]
    
    # Inject workspace and mode prefix so both live models and synthesizer are aware of project context
    ws_prefix = ""
    if request.workspace:
        ws_name = request.workspace.get("name", "Project")
        ws_path = request.workspace.get("path", "")
        ws_stack = request.workspace.get("stack", "General")
        ws_prefix = f"[Project: {ws_name} | Path: {ws_path} | Stack: {ws_stack} | Mode: {request.mode.upper()}]\n"
    elif request.mode:
        ws_prefix = f"[Mode: {request.mode.upper()}]\n"

    full_prompt = inject_tools_into_prompt(raw_messages, tools=request.tools)
    if ws_prefix and ws_prefix not in full_prompt:
        full_prompt = f"{ws_prefix}{full_prompt}"
    
    try:
        raw_response, _, _ = await _infer_with_tools(full_prompt, request.model, request.tools)
        
        # Extract thought if present
        thought_match = re.search(r'<thought>\s*(.*?)\s*</thought>', raw_response, re.DOTALL)
        thought_content = thought_match.group(1).strip() if thought_match else None
        
        text_without_thought = re.sub(r'<thought>.*?</thought>', '', raw_response, flags=re.DOTALL).strip()
        clean_content, tool_calls = parse_response_for_tools(text_without_thought) if request.tools else (text_without_thought, None)
        if tool_calls:
            declared = {t["function"]["name"] for t in request.tools}
            if any(t["function"]["name"] not in declared for t in tool_calls):
                raise ArenaError("Arena requested an undeclared tool.", "ARENA_INVALID_TOOL_CALL", 502)
        
        # If client did not request tools (e.g. Web UI) but tool_calls were produced, convert to markdown code deck
        if (not clean_content or clean_content.isspace()) and tool_calls and not request.tools:
            tc = tool_calls[0].get("function", {})
            try:
                args = json.loads(tc.get("arguments", "{}"))
                fp = args.get("file_path", "main.py")
                code_body = args.get("content", "")
                ext = fp.split(".")[-1] if "." in fp else "txt"
                lang_map = {"cs": "csharp", "py": "python", "js": "javascript", "ts": "typescript", "go": "go", "rs": "rust"}
                lang = lang_map.get(ext, ext)
                clean_content = f"کدهای پیاده‌سازی شده برای پروژه:\n\n```{lang}:{fp}\n{code_body}\n```"
            except Exception:
                pass

        response_message = {
            "role": "assistant",
            "content": clean_content if clean_content else None,
            "thought": thought_content,
        }
        if tool_calls and request.tools:
            response_message["tool_calls"] = tool_calls

            
        return {
            "id": f"chatcmpl-{uuid.uuid4().hex[:12]}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": request.model,
            "choices": [{
                "index": 0,
                "message": response_message,
                "finish_reason": "tool_calls" if (tool_calls and request.tools) else "stop"
            }],
            "usage": {
                "prompt_tokens": len(full_prompt.split()),
                "completion_tokens": len(raw_response.split()),
                "total_tokens": len(full_prompt.split()) + len(raw_response.split())
            }
        }
    except ArenaError:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))

# -------------------------------------------------------------
# Google Gemini API compatible Endpoints (for Gemini CLI)
# -------------------------------------------------------------
async def _infer_with_tools(prompt: str, model: str, tools: list[dict] | None):
    raw = await cdp_client.send_chat_message(prompt, model_name=model)
    text, calls = parse_response_for_tools(raw) if tools else (raw.strip(), None)
    if tools and "<tool_call>" in raw and not calls:
        correction = (prompt + "\n\n[Assistant]\n" + raw +
            "\n\n[System Instructions]\nYour last tool_call payload was invalid JSON. "
            "Correct it without changing the intended action. Use forward slashes in Windows paths "
            "(E:/project/file.txt), valid JSON object arguments, and only declared tool names. "
            "Return only the corrected <tool_call> JSON </tool_call>. No tool has executed yet.")
        raw = await cdp_client.send_chat_message(correction, model_name=model)
        text, calls = parse_response_for_tools(raw)
        if not calls:
            raise ArenaError("Arena returned invalid tool-call JSON after one correction attempt. No tool was executed.", "ARENA_INVALID_TOOL_CALL", 502)
    return raw, text, calls


@app.post("/v1beta/models/{model_path:path}:generateContent")
@app.post("/v1beta/models/{model_path:path}:streamGenerateContent")
async def gemini_generate_content(model_path: str, request: Request):
    try:
        body = await request.json()
        if not isinstance(body, dict):
            raise ValueError("Expected a JSON object")
    except (ValueError, UnicodeDecodeError) as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON request body") from exc

    messages = []
    system = body.get("systemInstruction", body.get("system_instruction", {}))
    if system:
        messages.append({"role": "system", "content": "\n".join(p.get("text", "") for p in system.get("parts", []))})
    for content in body.get("contents", []):
        role = "assistant" if content.get("role") == "model" else content.get("role", "user")
        parts = []
        for part in content.get("parts", []):
            if "text" in part:
                parts.append(part["text"])
            elif "functionCall" in part:
                fc = part["functionCall"]
                parts.append("<tool_call>\n" + json.dumps({"name": fc["name"], "arguments": fc.get("args", {}), "id": fc.get("id")}, ensure_ascii=False) + "\n</tool_call>")
            elif "functionResponse" in part:
                parts.append("<tool_response>\n" + json.dumps(part["functionResponse"], ensure_ascii=False) + "\n</tool_response>")
            else:
                raise HTTPException(status_code=400, detail="This Arena text gateway supports text and function parts only.")
        if parts:
            messages.append({"role": role, "content": "\n".join(parts)})
    if not messages:
        raise HTTPException(status_code=400, detail="contents must include at least one text or function part")

    declared_tools = []
    for tool in body.get("tools", []):
        for fd in tool.get("functionDeclarations", tool.get("function_declarations", [])):
            declared_tools.append({"type": "function", "function": {
                "name": fd["name"], "description": fd.get("description", ""),
                "parameters": fd.get("parametersJsonSchema", fd.get("parameters", {}))}})
    print(json.dumps({"arena_request": model_path, "body_keys": list(body), "tool_keys": [list(t) for t in body.get("tools", [])], "declared_tools": [t["function"]["name"] for t in declared_tools], "tool_config": body.get("toolConfig", {})}), flush=True)
    function_config = body.get("toolConfig", {}).get("functionCallingConfig", {})
    if function_config.get("mode") == "NONE":
        declared_tools = []
    allowed_names = function_config.get("allowedFunctionNames")
    if allowed_names is not None:
        declared_tools = [t for t in declared_tools if t["function"]["name"] in allowed_names]

    generation = body.get("generationConfig", {})
    if generation.get("responseMimeType") == "application/json":
        schema = generation.get("responseJsonSchema", generation.get("responseSchema"))
        instruction = "Return only valid JSON, without markdown fences."
        if schema:
            instruction += "\nRequired JSON schema: " + json.dumps(schema, ensure_ascii=False)
        messages.insert(0, {"role": "system", "content": instruction})
    full_prompt = inject_tools_into_prompt(messages, declared_tools or None)

    async def complete():
        raw, text, calls = await _infer_with_tools(full_prompt, model_path, declared_tools)
        response_parts = []
        if text:
            response_parts.append({"text": text})
        if calls:
            declared = {t["function"]["name"] for t in declared_tools}
            for call in calls:
                function = call["function"]
                if function["name"] not in declared:
                    raise ArenaError("Arena requested an undeclared tool.", "ARENA_INVALID_TOOL_CALL", 502)
                response_parts.append({"functionCall": {"id": call["id"], "name": function["name"], "args": json.loads(function["arguments"])}})
        if not response_parts:
            raise ArenaError("Arena returned an empty response.", "ARENA_EMPTY_RESPONSE", 502)
        chunk = {"candidates": [{"content": {"role": "model", "parts": response_parts}, "finishReason": "STOP", "index": 0}],
                 "modelVersion": model_path, "responseId": "arena-" + uuid.uuid4().hex}
        return chunk

    if "streamGenerateContent" in request.url.path or request.query_params.get("alt") == "sse":
        async def events():
            task = asyncio.create_task(complete())
            try:
                # The bundled Google SDK requires JSON data events; SSE
                # comment heartbeats leave unconsumed bytes in its buffer.
                yield 'data: {"candidates": []}\n\n'
                while not task.done():
                    done, _ = await asyncio.wait({task}, timeout=10)
                    if not done:
                        yield 'data: {"candidates": []}\n\n'
                chunk = await task
                yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
            except ArenaError as exc:
                error = {"error": {"code": exc.status_code, "status": "UNAVAILABLE",
                                  "message": str(exc), "details": [{"reason": exc.code}]}}
                # Google's SDK recognizes a bare JSON error mid-stream.
                yield json.dumps(error)
            finally:
                if not task.done():
                    task.cancel()
                await asyncio.gather(task, return_exceptions=True)
        return StreamingResponse(events(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})
    return await complete()


async def _live_models(refresh: bool = False):
    return await cdp_client.list_models(refresh=refresh)


@app.get("/v1/models")
async def openai_list_models(refresh: bool = False):
    names = await _live_models(refresh)
    return {"object": "list", "data": [{"id": name, "object": "model", "owned_by": "arena"} for name in names]}


def _model_info(name: str):
    return {"name": f"models/{name}", "version": "001", "displayName": name + " (Arena)",
            "description": "Available in the live Arena Direct model picker",
            "supportedGenerationMethods": ["generateContent", "streamGenerateContent", "countTokens"]}


@app.get("/v1beta/models")
async def list_models(refresh: bool = False):
    return {"models": [_model_info(name) for name in await _live_models(refresh)]}


@app.get("/v1beta/models/{model_path:path}")
async def get_model(model_path: str):
    name = model_path.removeprefix("models/")
    if name not in await _live_models():
        raise HTTPException(status_code=404, detail="Model is not available in Arena Direct")
    return _model_info(name)


@app.post("/v1beta/models/{model_path:path}:countTokens")
async def count_tokens(model_path: str, request: Request):
    # Approximation only: Arena does not expose the selected model's tokenizer.
    body = await request.json()
    text = json.dumps(body, ensure_ascii=False)
    return {"totalTokens": max(1, (len(text.encode("utf-8")) + 3) // 4)}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("arena_gateway.server:app", host="127.0.0.1", port=8000, reload=True)


