import asyncio
import inspect
import logging
import os
from aiohttp import web
from aiogram import BaseMiddleware, Dispatcher
from aiogram.types import Message

import admin
import appeals
import automod
import chat_lock
import db
import economy_shop
import info
import moderation
import pm_panel
import report
import reputation
import roulette
import rp
import webapp
import welcome
from loader import bot

logging.basicConfig(level=logging.INFO)

class TrackerAndRegisterMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        try:
            if getattr(event, 'from_user', None):
                db.touch_user(event.from_user.id, event.from_user.username, event.from_user.full_name)
            if isinstance(event, Message) and event.chat.type in ("group", "supergroup"):
                db.register_chat(event.chat.id, event.chat.title)
        except Exception as e:
            logging.warning("Ошибка middleware: %s", e)
        return await handler(event, data)

async def start_web_server():
    app = web.Application()
    app.router.add_get("/", lambda r: web.Response(text="Bot is alive!"))
    webapp.setup_routes(app)

    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.getenv("PORT", 10000))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logging.info("Веб-сервер запущен на порту %s", port)

async def main():
    if hasattr(db, "init_db"):
        res = db.init_db()
        if inspect.isawaitable(res):
            await res

    dp = Dispatcher()
    dp.message.outer_middleware(TrackerAndRegisterMiddleware())

    # Подключаем модули (порядок важен!)
    dp.include_router(pm_panel.router)
    dp.include_router(chat_lock.router)
    dp.include_router(report.router)
    dp.include_router(appeals.router)
    dp.include_router(economy_shop.router)
    dp.include_router(reputation.router)
    dp.include_router(roulette.router)
    dp.include_router(rp.router)
    dp.include_router(admin.router)
    dp.include_router(moderation.router)
    dp.include_router(info.router)
    dp.include_router(welcome.router)
    dp.include_router(automod.router) # Автомод - всегда последний!

    await start_web_server()
    await bot.delete_webhook(drop_pending_updates=True)
    await bot.start_polling(
        bot,
        allowed_updates=["message", "edited_message", "callback_query", "chat_member", "my_chat_member", "chat_join_request"],
    )

if __name__ == "__main__":
    asyncio.run(main())
