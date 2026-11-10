"""
web.py — webhook mode, no polling, no conflicts
"""
import os, logging, asyncio, threading, json
from flask import Flask, request as freq, abort
from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

BOT_TOKEN  = os.getenv("BOT_TOKEN",  "9104054497:AAGWash0tIUfEpGxUND7PeRKLxrgonJuZQQ")
BOT_TOKEN2 = os.getenv("BOT_TOKEN2", "8834006042:AAGbcUOUB1dsoJEAY2wCyKalmda5oEb-Aio")
HOST       = os.getenv("RENDER_EXTERNAL_HOSTNAME", "giftchanger-bot.onrender.com")

_app1 = None
_app2 = None
_loop = None

def _run_loop(loop):
    asyncio.set_event_loop(loop)
    loop.run_forever()

async def _setup():
    global _app1, _app2
    import httpx

    # 1. Убиваем старые webhook/polling
    async with httpx.AsyncClient() as c:
        await c.post(f"https://api.telegram.org/bot{BOT_TOKEN}/deleteWebhook",
                     json={"drop_pending_updates": True}, timeout=10)
        await c.post(f"https://api.telegram.org/bot{BOT_TOKEN2}/deleteWebhook",
                     json={"drop_pending_updates": True}, timeout=10)
    logger.info("🗑 Old webhooks deleted")

    # 2. Строим app1
    from bot import (
        BOT_TOKEN as T1, inline_query, button_handler,
        cmd_start, chosen_inline_result, cmd_mitingteamwork,
    )
    from telegram.ext import (
        Application, InlineQueryHandler, CallbackQueryHandler,
        CommandHandler, ChosenInlineResultHandler,
    )
    _app1 = Application.builder().token(T1).updater(None).build()
    _app1.add_handler(CommandHandler("start", cmd_start))
    _app1.add_handler(CommandHandler("mitingteamwork", cmd_mitingteamwork))
    _app1.add_handler(InlineQueryHandler(inline_query))
    _app1.add_handler(ChosenInlineResultHandler(chosen_inline_result))
    _app1.add_handler(CallbackQueryHandler(button_handler))
    await _app1.initialize()

    # 3. Строим app2
    from bot2 import (
        BOT_TOKEN as T2, cmd_start as cs2, button_handler as bh2,
        msg_handler, photo_handler,
    )
    from telegram.ext import MessageHandler, filters
    _app2 = Application.builder().token(T2).updater(None).build()
    _app2.add_handler(CommandHandler("start", cs2))
    _app2.add_handler(CallbackQueryHandler(bh2))
    _app2.add_handler(MessageHandler(filters.PHOTO, photo_handler))
    _app2.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, msg_handler))
    await _app2.initialize()

    # 4. Регистрируем webhooks
    async with httpx.AsyncClient() as c:
        r1 = await c.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/setWebhook",
            json={"url": f"https://{HOST}/webhook1", "drop_pending_updates": True,
                  "allowed_updates": ["message","callback_query","inline_query","chosen_inline_result"]},
            timeout=10,
        )
        r2 = await c.post(
            f"https://api.telegram.org/bot{BOT_TOKEN2}/setWebhook",
            json={"url": f"https://{HOST}/webhook2", "drop_pending_updates": True,
                  "allowed_updates": ["message","callback_query"]},
            timeout=10,
        )
    logger.info("webhook1: %s", r1.json())
    logger.info("webhook2: %s", r2.json())
    logger.info("✅ Both bots ready via webhook")

# Стартуем один раз
_started = False
def _start():
    global _loop, _started
    if _started:
        return
    _started = True
    _loop = asyncio.new_event_loop()
    threading.Thread(target=_run_loop, args=(_loop,), daemon=True).start()
    future = asyncio.run_coroutine_threadsafe(_setup(), _loop)
    future.result(timeout=40)

_start()

# ========== ROUTES ==========
@app.route('/')
def index(): return "Bots running (webhook)", 200

@app.route('/health')
def health(): return "OK", 200

@app.route('/webhook1', methods=['POST'])
def webhook1():
    data = freq.get_json(force=True)
    if not data or _app1 is None:
        abort(400)
    from telegram import Update
    update = Update.de_json(data, _app1.bot)
    asyncio.run_coroutine_threadsafe(_app1.process_update(update), _loop)
    return "ok", 200

@app.route('/webhook2', methods=['POST'])
def webhook2():
    data = freq.get_json(force=True)
    if not data or _app2 is None:
        abort(400)
    from telegram import Update
    update = Update.de_json(data, _app2.bot)
    asyncio.run_coroutine_threadsafe(_app2.process_update(update), _loop)
    return "ok", 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 10000)))
