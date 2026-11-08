import sys
from pathlib import Path

# Ensure E:\ and E:\arena_gateway are accessible
current_dir = Path(__file__).resolve().parent
parent_dir = current_dir.parent
if str(parent_dir) not in sys.path:
    sys.path.insert(0, str(parent_dir))
if str(current_dir) not in sys.path:
    sys.path.insert(0, str(current_dir))

import uvicorn
from arena_gateway.config import Settings
from arena_gateway.server import app

def get_app():
    return app

if __name__ == "__main__":
    settings = Settings()
    print("=====================================================")
    print(f"  Starting Arena Gateway on port {settings.port}")
    print(f"  Studio UI: http://127.0.0.1:{settings.port}/")
    print(f"  OpenAI API: http://127.0.0.1:{settings.port}/v1/chat/completions")
    print(f"  Gemini API: http://127.0.0.1:{settings.port}/v1beta/models")
    print(f"  Chrome CDP Target: {settings.cdp_url}")
    print("=====================================================")
    uvicorn.run("arena_gateway.server:app", host="127.0.0.1", port=settings.port, reload=False)
