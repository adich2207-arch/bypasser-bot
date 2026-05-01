import asyncio
import logging
import os
import re
from urllib.parse import urlparse, urljoin

import aiohttp
from aiohttp import web
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, Command
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Message
from dotenv import load_dotenv

load_dotenv()

# ── Config ─────────────────────────────────────────────────────────────────────

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN is not set")

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# ── URL extraction ─────────────────────────────────────────────────────────────

URL_REGEX = re.compile(r'https?://[^\s<>"{}|\\^`\[\]]+', re.IGNORECASE)

def extract_urls(text: str) -> list[str]:
    return URL_REGEX.findall(text)

# ── Link resolver ──────────────────────────────────────────────────────────────

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}


async def resolve_url(url: str, max_hops: int = 15) -> tuple[str, list[str]]:
    """
    Follow all redirects (301, 302, 303, 307, 308) and return
    (final_url, full_redirect_chain).
    Tries HEAD first, falls back to GET if needed.
    """
    chain = []
    current = url
    timeout = aiohttp.ClientTimeout(total=20)

    async with aiohttp.ClientSession(timeout=timeout, headers=HEADERS) as session:
        for _ in range(max_hops):
            if current in chain:
                break  # loop detected
            chain.append(current)

            # Try HEAD first (faster, no body download)
            location = None
            for method in ("HEAD", "GET"):
                try:
                    req = session.head if method == "HEAD" else session.get
                    async with req(current, allow_redirects=False, ssl=False) as resp:
                        if resp.status in (301, 302, 303, 307, 308):
                            location = resp.headers.get("Location", "")
                        else:
                            # No more redirects
                            return current, chain
                    break
                except aiohttp.ClientError:
                    if method == "GET":
                        return current, chain

            if not location:
                break

            # Resolve relative URLs
            if location.startswith("//"):
                parsed = urlparse(current)
                location = f"{parsed.scheme}:{location}"
            elif location.startswith("/"):
                parsed = urlparse(current)
                location = f"{parsed.scheme}://{parsed.netloc}{location}"
            elif not location.startswith("http"):
                location = urljoin(current, location)

            current = location

    return current, chain


# ── Bot setup ──────────────────────────────────────────────────────────────────

bot = Bot(token=BOT_TOKEN)
dp  = Dispatcher(storage=MemoryStorage())

# ── Handlers ───────────────────────────────────────────────────────────────────

@dp.message(CommandStart())
async def cmd_start(message: Message):
    await message.answer(
        "🔗 <b>Link Unshortener Bot</b>\n\n"
        "I reveal the real destination behind any shortened or redirected link.\n\n"
        "<b>How to use:</b>\n"
        "Just send me any link and I'll show you exactly where it leads.\n\n"
        "<b>Supported shorteners:</b>\n"
        "bit.ly • tinyurl.com • t.co • goo.gl • ow.ly • adf.ly\n"
        "shorturl.at • cutt.ly • rb.gy • t.ly • is.gd • tiny.cc\n"
        "linktr.ee • lnkd.in • amzn.to • youtu.be • and any other!",
        parse_mode="HTML",
    )


@dp.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(
        "ℹ️ <b>Help</b>\n\n"
        "Send me any shortened or suspicious link.\n"
        "I will follow all redirects and show you:\n\n"
        "• ✅ The final destination URL\n"
        "• 🔗 The full redirect chain\n"
        "• 🔢 Number of hops\n\n"
        "<b>You can send multiple links in one message.</b>\n"
        "I process up to 5 links per message.",
        parse_mode="HTML",
    )


@dp.message(F.text)
async def handle_message(message: Message):
    urls = extract_urls(message.text)
    if not urls:
        await message.answer(
            "❌ No links found in your message.\n\nSend me a URL starting with http:// or https://"
        )
        return

    urls = list(dict.fromkeys(urls))[:5]  # deduplicate, max 5

    processing = await message.answer(f"🔍 Resolving {len(urls)} link(s)...")

    results = []
    for url in urls:
        try:
            final, chain = await resolve_url(url)
            hops = len(chain)

            if hops <= 1 and final == url:
                results.append(
                    f"🔗 <b>URL:</b> <code>{url}</code>\n"
                    f"✅ No redirects — this is already the final URL."
                )
            else:
                # Build chain display (show max 5 intermediate steps)
                chain_lines = ""
                if hops > 1:
                    display = chain[:5]
                    chain_lines = "\n<b>Redirect chain:</b>\n" + "\n".join(
                        f"  {i+1}. <code>{u}</code>" for i, u in enumerate(display)
                    )
                    if hops > 5:
                        chain_lines += f"\n  ... ({hops - 5} more hops)"

                results.append(
                    f"🔗 <b>Original:</b> <code>{url}</code>\n"
                    f"🎯 <b>Final URL:</b> <code>{final}</code>\n"
                    f"↪️ <b>Hops:</b> {hops}"
                    + chain_lines
                )

        except asyncio.TimeoutError:
            results.append(
                f"⏱ <b>Timeout</b>\n"
                f"<code>{url}</code>\n"
                f"The server took too long to respond."
            )
        except Exception as e:
            results.append(
                f"❌ <b>Error</b>\n"
                f"<code>{url}</code>\n"
                f"{str(e)[:120]}"
            )

    await processing.edit_text(
        "\n\n─────────────────\n\n".join(results),
        parse_mode="HTML",
        disable_web_page_preview=True,
    )


# ── Health check web server (required by Render Web Service) ───────────────────

async def health(request):
    return web.Response(text="OK")


async def run_web():
    app = web.Application()
    app.router.add_get("/", health)
    app.router.add_get("/health", health)
    port = int(os.environ.get("PORT", 8080))
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", port).start()
    logger.info(f"Web server running on port {port}")


async def main():
    logger.info("Link Unshortener Bot starting...")
    await asyncio.gather(run_web(), dp.start_polling(bot))


if __name__ == "__main__":
    asyncio.run(main())
