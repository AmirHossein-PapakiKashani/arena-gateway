"""Launch Gemini CLI with live Arena models and the local Gemini tool loop."""
import argparse
import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parent


def build_settings(existing, models, selected):
    if selected not in models:
        raise ValueError(f"Model {selected!r} is not in the live Arena Direct list.")
    config = copy.deepcopy(existing)
    config.setdefault("security", {}).setdefault("auth", {})["selectedType"] = "gemini-api-key"
    config.setdefault("experimental", {})["dynamicModelConfiguration"] = True
    config.setdefault("model", {})["name"] = selected
    config.setdefault("general", {})["enableAutoUpdate"] = False
    registry = config.setdefault("modelConfigs", {})
    definitions = registry.setdefault("modelDefinitions", {})
    # Hide known built-in Google options: they are not the Arena model catalog.
    builtin = ["auto", "auto-gemini-3", "auto-gemini-2.5", "pro", "flash", "flash-lite",
               "gemini-2.5-pro", "gemini-2.5-flash", "gemini-2.5-flash-lite",
               "gemini-3-pro-preview", "gemini-3-flash-preview", "gemini-3.1-pro-preview",
               "gemini-3.1-pro-preview-customtools", "gemini-3.1-flash-lite",
               "gemini-3.1-flash-lite-preview", "gemini-3.5-flash-lite", "gemini-3.5-flash",
               "gemini-3.8-flash", "gemma-4-31b-it", "gemma-4-26b-a4b-it"]
    for name in list(definitions) + builtin:
        definitions[name] = {**definitions.get(name, {}), "isVisible": False}
    for name in models:
        definitions[name] = {"displayName": name + " (Arena)", "tier": "custom", "family": "arena",
                             "isVisible": True, "isPreview": False,
                             "dialogDescription": "Live Arena Direct model; local Gemini tools and loop",
                             "features": {"thinking": False, "multimodalToolUse": False}}
    aliases = registry.setdefault("aliases", {})
    aliases["chat-base"] = {"extends": "base", "modelConfig": {"model": selected}}
    for name in ["classifier", "numerical-classifier", "edit-corrector", "fast-ack-helper",
                 "summarizer-default", "summarizer-shell", "web-fetch", "web-fetch-fallback",
                 "web-search", "loop-detection", "loop-detection-double-check", "llm-edit-fixer",
                 "next-speaker-checker", "context-snapshotter", "chat-compression-3-pro",
                 "chat-compression-3-flash", "chat-compression-2.5-pro", "chat-compression-2.5-flash"]:
        aliases[name] = {"extends": "base", "modelConfig": {"model": selected}}
    for name in models:
        aliases[name] = {"extends": "chat-base", "modelConfig": {"model": name}}
    return config


def request_json(base, path, method="GET"):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        timeout = 420 if path.startswith("/v1beta/models") else 10
        with opener.open(urllib.request.Request(base + path, method=method), timeout=timeout) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        payload = json.loads(exc.read())
        raise RuntimeError(payload.get("error", {}).get("message", payload.get("detail", str(exc)))) from exc


def ensure_gateway(base, port):
    try:
        health = request_json(base, "/health")
        if health.get("synthetic_fallback") is not False:
            raise RuntimeError("A different gateway is using this port. Stop it or choose --port.")
        return
    except urllib.error.URLError:
        pass
    log_dir = ROOT / ".runtime"
    log_dir.mkdir(exist_ok=True)
    env = os.environ.copy()
    env.update({"ARENA_GATEWAY_PORT": str(port), "MOCK_ARENA": "false", "FALLBACK_MOCK": "false"})
    with (log_dir / "gateway.log").open("a", encoding="utf8") as log:
        process = subprocess.Popen([sys.executable, "-X", "utf8", str(ROOT / "main.py")],
            cwd=ROOT, env=env, stdout=log, stderr=log,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    for _ in range(50):
        if process.poll() is not None:
            raise RuntimeError(f"Gateway exited. Read {log_dir / 'gateway.log'}")
        try:
            request_json(base, "/health")
            return
        except urllib.error.URLError:
            time.sleep(0.2)
    raise RuntimeError("Gateway did not start within 10 seconds.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model")
    parser.add_argument("--workspace", type=Path, default=Path.cwd())
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--list-models", action="store_true")
    parser.add_argument("--configure-only", action="store_true")
    parser.add_argument("cli_args", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    base = f"http://127.0.0.1:{args.port}"
    ensure_gateway(base, args.port)
    if not request_json(base, "/api/cdp/status").get("connected"):
        request_json(base, "/api/cdp/launch", "POST")
        time.sleep(2)
    models = [m["name"].removeprefix("models/") for m in request_json(base, "/v1beta/models?refresh=true")["models"]]
    if args.list_models:
        print("\n".join(models))
        return
    selected = args.model
    if not selected:
        for index, name in enumerate(models, 1):
            print(f"{index:2}. {name}")
        choice = input("Choose an Arena model (number or exact model ID): ").strip()
        selected = models[int(choice) - 1] if choice.isdigit() and 1 <= int(choice) <= len(models) else choice
    workspace = args.workspace.resolve()
    if not workspace.is_dir():
        raise ValueError(f"Workspace does not exist: {workspace}")
    path = workspace / ".gemini" / "settings.json"
    existing = json.loads(path.read_text(encoding="utf-8-sig")) if path.exists() else {}
    config = build_settings(existing, models, selected)
    path.parent.mkdir(exist_ok=True)
    if path.exists():
        backup = path.with_name("settings.before-arena.json")
        if not backup.exists():
            shutil.copy2(path, backup)
    path.write_text(json.dumps(config, indent=2, ensure_ascii=False) + "\n", encoding="utf8")
    print(f"Arena model: {selected}\nWorkspace: {workspace}\nChange model inside Gemini CLI with /model.", flush=True)
    if args.configure_only:
        return
    # Only localhost inference is sent by the CLI. Browser traffic keeps the
    # Windows/Clash proxy. Explicit proxy agents can ignore NO_PROXY in Node.
    env = os.environ.copy()
    for key in list(env):
        if key.lower() in {"http_proxy", "https_proxy", "all_proxy"}:
            env.pop(key)
    env.update({"GOOGLE_GEMINI_BASE_URL": base, "GEMINI_API_KEY": "arena-local",
                "NO_PROXY": "localhost,127.0.0.1,::1", "GEMINI_CLI_NO_RELAUNCH": "1"})
    cli = shutil.which("gemini.cmd") if os.name == "nt" else shutil.which("gemini")
    if not cli:
        raise RuntimeError("Gemini CLI is not installed or is not on PATH.")
    # Resolve the JS entry point to avoid cmd.exe quoting of user prompts.
    if os.name == "nt":
        entry = Path(cli).parent / "node_modules" / "@google" / "gemini-cli" / "bundle" / "gemini.js"
        command = [shutil.which("node") or "node", str(entry)]
    else:
        command = [cli]
    extra = args.cli_args[1:] if args.cli_args[:1] == ["--"] else args.cli_args
    return subprocess.call(command + ["--model", selected] + extra, cwd=workspace, env=env)


if __name__ == "__main__":
    try:
        sys.exit(main() or 0)
    except (RuntimeError, ValueError, TimeoutError, urllib.error.URLError) as exc:
        print(f"Arena Gateway: {exc}", file=sys.stderr)
        sys.exit(1)
