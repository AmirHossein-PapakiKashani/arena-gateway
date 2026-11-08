"""Arena browser transport. Persistent login, isolated chats, no synthetic inference."""
import asyncio
import json
import re
import time
from urllib.parse import urlparse
from playwright.async_api import async_playwright
from arena_gateway.config import Settings


class ArenaError(RuntimeError):
    def __init__(self, message, code="ARENA_UNAVAILABLE", status_code=503):
        super().__init__(message)
        self.code, self.status_code = code, status_code


def parse_arena_stream(raw: str) -> str:
    fragments = []
    finished = False
    for line in raw.splitlines():
        kind, separator, payload = line.partition(":")
        if not separator or kind not in {"a0", "0", "ad", "d", "a3", "3"}:
            continue
        try:
            value = json.loads(payload)
        except ValueError as exc:
            raise ArenaError("Arena returned a malformed stream.", "ARENA_INVALID_STREAM", 502) from exc
        if kind in {"a3", "3"}:
            raise ArenaError("Arena's model provider returned an error.", "ARENA_PROVIDER_ERROR", 502)
        if kind in {"a0", "0"} and isinstance(value, str):
            fragments.append(value)
        if kind in {"ad", "d"}:
            if not isinstance(value, dict) or value.get("finishReason") not in {"stop", "length", "tool-calls"}:
                raise ArenaError("Arena's model provider did not complete successfully.", "ARENA_PROVIDER_ERROR", 502)
            finished = True
    if not finished:
        raise ArenaError("Arena's response stream ended before completion.", "ARENA_TRUNCATED_STREAM", 502)
    text = "".join(fragments).strip()
    if not text:
        raise ArenaError("Arena's model provider returned no text.", "ARENA_EMPTY_RESPONSE", 502)
    return text


class ArenaCDPClient:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.is_connected = False
        self._playwright = self._browser = self._context = self._page = None
        self._lock = asyncio.Lock()
        self._models, self._models_at = [], 0.0
        self.last_error = self.last_model = None

    async def connect(self):
        if self._browser and self._browser.is_connected() and self._page and not self._page.is_closed():
            return
        if self._playwright:
            await self._playwright.stop()
        self.is_connected = False
        self._playwright = await async_playwright().start()
        try:
            self._browser = await self._playwright.chromium.connect_over_cdp(self.settings.cdp_url, timeout=10000)
            self._context = self._browser.contexts[0]
            self._page = await self._context.new_page()
            self._page.set_default_timeout(10000)
            self.is_connected = True
        except Exception as exc:
            await self._playwright.stop()
            self._playwright = None
            raise ArenaError("Cannot attach to Arena Chrome. Use POST /api/cdp/launch, then sign in at arena.ai.", "CDP_UNAVAILABLE") from exc

    async def _fresh_chat(self):
        await self.connect()
        # CLI supplies full history. Fresh chats prevent cross-session contamination.
        await self._page.goto("https://arena.ai/text/direct", wait_until="domcontentloaded", timeout=30000)
        await self._page.locator("textarea[placeholder]").filter(visible=True).first.wait_for(state="visible", timeout=30000)

    async def _check_access(self):
        if await self._page.get_by_role("button", name="Continue with Google", exact=True).is_visible():
            raise ArenaError("Sign in to arena.ai in the Arena Chrome profile, then retry. No model response was generated.", "ARENA_AUTH_REQUIRED", 401)
        notices = []
        for element in await self._page.locator('[role="alert"], [role="dialog"]').all():
            if await element.is_visible():
                notices.append(await element.inner_text())
        body = "\n".join(notices)
        title = await self._page.title()
        if re.search(r"security verification|verify you are human|just a moment", body + "\n" + title, re.I):
            raise ArenaError("Complete Arena's security verification in Chrome, then retry.", "ARENA_VERIFICATION_REQUIRED", 403)
        if re.search(r"rate limit|too many requests|usage limit|daily limit", body, re.I):
            raise ArenaError("Arena reports a usage limit. Retry after the limit resets.", "ARENA_RATE_LIMITED", 429)

    async def _open_model_picker(self):
        candidates = []
        for button in await self._page.locator('button[aria-haspopup="dialog"]').all():
            if await button.is_visible() and (await button.inner_text()).strip():
                candidates.append(button)
        if len(candidates) != 1:
            raise ArenaError("Arena's model selector changed; cannot verify the requested model.", "ARENA_SELECTOR_CHANGED", 502)
        await candidates[0].click()
        await self._page.get_by_placeholder("Search models", exact=True).wait_for(state="visible")
        return candidates[0]

    async def list_models(self, refresh=False):
        async with self._lock:
            if self._models and not refresh and time.monotonic() - self._models_at < 300:
                return list(self._models)
            await self._fresh_chat()
            await self._check_access()
            await self._open_model_picker()
            options = self._page.locator('[cmdk-item][role="option"]')
            await options.first.wait_for(state="visible")
            names = []
            for option in await options.all():
                text = (await option.inner_text()).strip().splitlines()[0]
                if text and text not in names and text not in {"Max", "Router"}:
                    names.append(text)
            await self._page.keyboard.press("Escape")
            if not names:
                raise ArenaError("Arena returned an empty model list.", "ARENA_SELECTOR_CHANGED", 502)
            self._models, self._models_at = names, time.monotonic()
            return list(names)

    async def _select_model(self, model):
        button = await self._open_model_picker()
        await self._page.get_by_placeholder("Search models", exact=True).fill(model)
        option = self._page.get_by_role("option").filter(has_text=re.compile(r"^" + re.escape(model) + r"$"))
        try:
            await option.wait_for(state="visible", timeout=3000)
        except Exception as exc:
            await self._page.keyboard.press("Escape")
            raise ArenaError(f"Model '{model}' is not selectable in Arena Direct for this account. Refresh the model list; no substitute was used.", "ARENA_MODEL_UNAVAILABLE", 404) from exc
        await option.click()
        if (await button.inner_text()).strip() != model:
            raise ArenaError(f"Arena did not select '{model}'.", "ARENA_MODEL_MISMATCH", 502)
        self.last_model = model

    async def _get_current_bot_blocks(self, user_prompt=""):
        if not self._page:
            return []
        roots = self._page.locator('[data-message-author-role="assistant"], [data-role="assistant"]')
        if not await roots.count():
            roots = self._page.locator('.prose:not(.prose .prose):not(.self-end .prose):not(.items-end .prose)')
        blocks = []
        for root in await roots.all():
            text = (await root.inner_text()).strip()
            if text and text != user_prompt and not text.startswith("[System Instructions]"):
                blocks.append(text)
        return blocks

    async def send_chat_message(self, prompt, model_name=None, on_status=None,
                                user_instruction="", mode="code", workspace=None):
        model = (model_name or self.settings.default_model).removeprefix("models/")
        if not model or model in {"default", "gemini", "auto", "auto-gemini-3", "auto-gemini-2.5"}:
            raise ArenaError("Select an explicit Arena model with /model or the Arena launcher.", "ARENA_MODEL_REQUIRED", 400)
        if self.settings.mock_mode:
            raise ArenaError("MOCK_ARENA is enabled. Disable it for real Arena inference.", "MOCK_MODE_DISABLED")
        async with self._lock:
            try:
                async with asyncio.timeout(self.settings.request_timeout):
                    await self._fresh_chat()
                    await self._check_access()
                    await self._select_model(model)
                    textarea = self._page.locator("textarea[placeholder]").filter(visible=True).first
                    await textarea.fill(prompt)
                    if await textarea.input_value() != prompt:
                        raise ArenaError("Arena's input cannot hold the full request. Reduce the CLI context and retry.", "ARENA_CONTEXT_TOO_LARGE", 413)
                    # Observe only the normal browser request. No private API
                    # replay, cookie export, or bypass. Raw text survives the
                    # site's Markdown sanitizer, which can render XML as empty.
                    async def read_stream(response):
                        return parse_arena_stream((await response.body()).decode("utf8"))
                    def is_stream(response):
                        parsed = urlparse(response.url)
                        return (parsed.hostname == "arena.ai" and "/stream/" in parsed.path
                                and response.request.method == "POST"
                                and "text/event-stream" in response.headers.get("content-type", ""))
                    pending = []
                    def observe(response):
                        if is_stream(response):
                            pending.append(asyncio.create_task(read_stream(response)))
                    self._page.on("response", observe)
                    try:
                        await self._page.get_by_role("button", name="Send message", exact=True).click()
                        while True:
                            await asyncio.sleep(0.25)
                            await self._check_access()
                            if pending and pending[0].done():
                                text = await pending[0]
                                self.last_error = None
                                return text
                    finally:
                        self._page.remove_listener("response", observe)
                        for task in pending:
                            if not task.done():
                                task.cancel()
                        if pending:
                            await asyncio.gather(*pending, return_exceptions=True)
            except asyncio.CancelledError:
                if self._page and not self._page.is_closed():
                    await self._page.close()
                raise
            except TimeoutError as exc:
                self.last_error = "ARENA_TIMEOUT"
                raise ArenaError("Arena did not finish within REQUEST_TIMEOUT_SEC. No synthetic response was returned.", "ARENA_TIMEOUT", 504) from exc
            except ArenaError as exc:
                self.last_error = exc.code
                raise
            except Exception as exc:
                self.last_error = "ARENA_TRANSPORT_ERROR"
                raise ArenaError(f"Arena browser transport failed ({type(exc).__name__}). Check Chrome and retry.", "ARENA_TRANSPORT_ERROR", 502) from exc

    async def close(self):
        if self._page and not self._page.is_closed():
            await self._page.close()
        if self._playwright:
            await self._playwright.stop()
        self.is_connected = False
