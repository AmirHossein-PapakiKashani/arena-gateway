import argparse
import sys
import uvicorn

# Ensure UTF-8 output on Windows consoles
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

def main():
    parser = argparse.ArgumentParser(description="Arena Gateway Server & Studio Pro UI")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind server to (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8000, help="Port to listen on (default: 8000)")
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload for development")
    args = parser.parse_args()

    print("=====================================================")
    print("  Arena Gateway Studio Pro v0.2.0")
    print(f"  Studio UI: http://{args.host}:{args.port}/")
    print(f"  OpenAI API: http://{args.host}:{args.port}/v1/chat/completions")
    print(f"  Gemini API: http://{args.host}:{args.port}/v1beta/models")
    print("=====================================================")
    uvicorn.run("arena_gateway.server:app", host=args.host, port=args.port, reload=args.reload)

if __name__ == "__main__":
    main()
