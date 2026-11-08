"""Run an explicit live Arena probe without exposing credentials."""
import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from arena_gateway.cdp_client import ArenaCDPClient
from arena_gateway.config import Settings


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model")
    parser.add_argument("--prompt", default="Reply exactly ARENA_LIVE_CHECK_1108 and nothing else.")
    args = parser.parse_args()
    client = ArenaCDPClient(Settings())
    try:
        if args.model:
            print(await client.send_chat_message(args.prompt, args.model), flush=True)
            print("SELECTED_MODEL", client.last_model, flush=True)
        else:
            print(json.dumps(await client.list_models(refresh=True), ensure_ascii=False, indent=2), flush=True)
    finally:
        await client.close()


asyncio.run(main())
