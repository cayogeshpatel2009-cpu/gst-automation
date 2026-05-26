import os
import asyncio
from dotenv import load_dotenv
from aiogram import Bot

load_dotenv()
async def main():
    token = os.environ["TELEGRAM_BOT_TOKEN"]

    bot = Bot(token)

    me = await bot.get_me()
    webhook = await bot.get_webhook_info()
    updates = await bot.get_updates(limit=10, timeout=2)

    print("BOT:", me.username, me.id)
    print("WEBHOOK:", webhook.model_dump())
    print("UPDATES_COUNT:", len(updates))

    for u in updates:
        msg = getattr(u, "message", None)

        print(
            "UPDATE:",
            u.update_id,
            "HAS_MESSAGE:",
            msg is not None,
            "TEXT:",
            (getattr(msg, "text", None) or "")[:120],
        )

    await bot.session.close()

asyncio.run(main())