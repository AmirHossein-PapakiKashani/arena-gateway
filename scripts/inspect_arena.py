"""Read-only live diagnostics; never prints cookies or local prompts."""
import asyncio
import json
from playwright.async_api import async_playwright


async def main():
    async with async_playwright() as pw:
        browser = await pw.chromium.connect_over_cdp("http://127.0.0.1:9222")
        for context in browser.contexts:
            for page in context.pages:
                if "arena.ai" not in page.url:
                    continue
                print(json.dumps({"url": page.url, "title": await page.title(),
                    "body": (await page.locator("body").inner_text())[-6000:],
                    "inputs": await page.locator("textarea,input").evaluate_all("es => es.map(e => ({tag:e.tagName,placeholder:e.placeholder,role:e.getAttribute('role')}))"),
                    "buttons": await page.locator("button").evaluate_all("es => es.map(e=>({text:e.innerText,label:e.getAttribute('aria-label'),state:e.getAttribute('data-state')}))")}, ensure_ascii=False, indent=2))
                print("SELECTORS", await page.locator('[role="combobox"], [role="listbox"], select, [data-testid]').evaluate_all("es=>es.map(e=>e.outerHTML.slice(0,1600))"))
                print("MESSAGES", await page.locator('.prose, [data-message-author-role], [data-role]').evaluate_all("es=>es.map(e=>({tag:e.tagName,classes:e.className,role:e.getAttribute('data-role'),text:e.innerText.slice(0,2000)}))"))


asyncio.run(main())
