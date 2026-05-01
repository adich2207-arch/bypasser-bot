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

# ── Config ─────────────────────────────────────────────

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN is not set")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ── Economy System ─────────────────────────────────────

users = {}
REFERRAL_BONUS = 5
BYPASS_REWARD = 1

# ── URL extraction ─────────────────────────────────────

URL_REGEX = re.compile(r'https?://[^\s<>"{}|\\^`\[\]]+', re.IGNORECASE)

def extract_urls(text: str) -> list[str]:
    return URL_REGEX.findall(text)

# ── Headers ────────────────────────────────────────────

HEADERS = {
    "User-Agent": "Mozilla/5.0",
}

# ── Bypass APIs ───────────────────────────────────────

BYPASS_APIS = [
    "https://api.bypass.vip/?url={}",
    "https://bypass.pm/bypass?url={}"
]

# ── Resolver ──────────────────────────────────────────

async def resolve_url(url: str, max_hops: int = 10):
    chain = []
    current = url

    async with aiohttp.ClientSession(headers=HEADERS) as session:
        for _ in range(max_hops):
            if current in chain:
                break
            chain.append(current)

            try:
                async with session.get(current, allow_redirects=False) as resp:
                    if resp.status in (301, 302, 303, 307, 308):
                        location = resp.headers.get("Location")
                        if not location:
                            break

                        if not location.startswith("http"):
                            location = urljoin(current, location)

                        current = location
                    else:
                        return current, chain
            except:
                return current, chain

    return current, chain

# ── Bypass Function ───────────────────────────────────

async def bypass_url(url: str):
    async with aiohttp.ClientSession() as session:
        for api in BYPASS_APIS:
            try:
                async with session.get(api.format(url), timeout=10) as resp:
                    if resp.status == 200:
                        data = await resp.json()

                        final = (
                            data.get("destination")
                            or data.get("url")
                            or data.get("result")
                        )

                        if final and final.startswith("http"):
                            return final, "API"
            except:
                continue

    return None, None

# ── Bot setup ─────────────────────────────────────────

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# ── Handlers ──────────────────────────────────────────

@dp.message(CommandStart())
async def start(message: Message):
    user_id = message.from_user.id
    args = message.text.split()

    if user_id not in users:
        users[user_id] = {"coins": 0, "ref": 0}

        if len(args) > 1:
            try:
                ref = int(args[1])
                if ref != user_id and ref in users:
                    users[ref]["coins"] += REFERRAL_BONUS
                    users[ref]["ref"] += 1
            except:
                pass

    await message.answer(
        f"🚀 <b>Pro Bypass Bot</b>\n\n"
        f"💰 Coins: {users[user_id]['coins']}\n\n"
        f"🔗 Send any link to bypass",
        parse_mode="HTML"
    )

@dp.message(Command("help"))
async def help_cmd(message: Message):
    await message.answer(
        "📌 Send any shortened link\n"
        "⚙️ I will bypass it using API + redirect system"
    )

@dp.message(Command("balance"))
async def balance(message: Message):
    user = users.get(message.from_user.id, {"coins": 0, "ref": 0})
    await message.answer(
        f"💰 Coins: {user['coins']}\n👥 Referrals: {user['ref']}"
    )

@dp.message(Command("refer"))
async def refer(message: Message):
    user_id = message.from_user.id
    bot_username = "YOUR_BOT_USERNAME"

    link = f"https://t.me/{bot_username}?start={user_id}"

    await message.answer(
        f"🔗 Your referral link:\n{link}\n\n"
        f"🎁 Earn {REFERRAL_BONUS} coins per user"
    )

# ── Main handler ──────────────────────────────────────

@dp.message(F.text)
async def handle(message: Message):
    user_id = message.from_user.id

    if user_id not in users:
        users[user_id] = {"coins": 0, "ref": 0}

    urls = extract_urls(message.text)

    if not urls:
        return await message.answer("❌ Send a valid link")

    msg = await message.answer("🔍 Bypassing...")

    results = []

    for url in urls[:5]:
        try:
            final, method = await bypass_url(url)

            if not final:
                final, _ = await resolve_url(url)
                method = "Redirect"

            users[user_id]["coins"] += BYPASS_REWARD

            results.append(
                f"✨ <b>Bypassed</b>\n\n"
                f"🔗 <code>{url}</code>\n\n"
                f"🚀 <code>{final}</code>\n\n"
                f"⚙️ {method} | 💰 +{BYPASS_REWARD}"
            )

        except Exception as e:
            results.append(f"❌ Error: {str(e)}")

    await msg.edit_text("\n\n──────────────\n\n".join(results), parse_mode="HTML")

# ── Web server ────────────────────────────────────────

async def health(request):
    return web.Response(text="OK")

async def run_web():
    app = web.Application()
    app.router.add_get("/", health)
    port = int(os.getenv("PORT", 8080))
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", port).start()

# ── Main ──────────────────────────────────────────────

async def main():
    await asyncio.gather(run_web(), dp.start_polling(bot))

if __name__ == "__main__":
    asyncio.run(main())
