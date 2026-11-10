"""
web.py — webhook mode
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

    async with httpx.AsyncClient() as c:
        await c.post(f"https://api.telegram.org/bot{BOT_TOKEN}/deleteWebhook",
                     json={"drop_pending_updates": True}, timeout=10)
        await c.post(f"https://api.telegram.org/bot{BOT_TOKEN2}/deleteWebhook",
                     json={"drop_pending_updates": True}, timeout=10)

    from bot import (
        BOT_TOKEN as T1, inline_query, button_handler,
        cmd_start, chosen_inline_result, cmd_mitingteamwork,
    )
    from telegram.ext import (
        Application, InlineQueryHandler, CallbackQueryHandler,
        CommandHandler, ChosenInlineResultHandler,
    )
    a1 = Application.builder().token(T1).updater(None).build()
    a1.add_handler(CommandHandler("start", cmd_start))
    a1.add_handler(CommandHandler("mitingteamwork", cmd_mitingteamwork))
    a1.add_handler(InlineQueryHandler(inline_query))
    a1.add_handler(ChosenInlineResultHandler(chosen_inline_result))
    a1.add_handler(CallbackQueryHandler(button_handler))
    async def on_error1(u, ctx): logger.error("app1: %s", ctx.error, exc_info=ctx.error)
    a1.add_error_handler(on_error1)
    await a1.initialize()
    await a1.start()
    global _app1
    _app1 = a1
    logger.info("✅ app1 ready")

    try:
        from bot2 import (
            BOT_TOKEN as T2, cmd_start as cs2, button_handler as bh2,
            msg_handler, photo_handler,
        )
        from telegram.ext import MessageHandler, filters
        a2 = Application.builder().token(T2).updater(None).build()
        a2.add_handler(CommandHandler("start", cs2))
        a2.add_handler(CallbackQueryHandler(bh2))
        a2.add_handler(MessageHandler(filters.PHOTO, photo_handler))
        a2.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, msg_handler))
        async def on_error2(u, ctx): logger.error("app2: %s", ctx.error, exc_info=ctx.error)
        a2.add_error_handler(on_error2)
        await a2.initialize()
        await a2.start()
        global _app2
        _app2 = a2
        logger.info("✅ app2 ready")
    except Exception as e:
        logger.error("❌ app2 failed: %s", e)

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
    logger.info("wh1: %s | wh2: %s", r1.json().get("description"), r2.json().get("description"))

_started = False
def _start():
    global _loop, _started
    if _started:
        return
    _started = True
    _loop = asyncio.new_event_loop()
    threading.Thread(target=_run_loop, args=(_loop,), daemon=True).start()
    asyncio.run_coroutine_threadsafe(_setup(), _loop)

_start()

@app.route('/')
def index(): return "OK", 200

@app.route('/health')
def health(): return "OK", 200

def _parse_update():
    try:
        return json.loads(freq.get_data())
    except Exception as e:
        logger.error("parse: %s", e)
        return None

@app.route('/webhook1', methods=['POST'])
def webhook1():
    if _app1 is None:
        return "starting", 200
    data = _parse_update()
    if not data:
        return "ok", 200
    logger.info("wh1: %s", list(data.keys()))
    from telegram import Update
    update = Update.de_json(data, _app1.bot)
    asyncio.run_coroutine_threadsafe(_app1.process_update(update), _loop)
    return "ok", 200

@app.route('/webhook2', methods=['POST'])
def webhook2():
    if _app2 is None:
        return "starting", 200
    data = _parse_update()
    if not data:
        return "ok", 200
    logger.info("wh2: %s", list(data.keys()))
    from telegram import Update
    update = Update.de_json(data, _app2.bot)
    asyncio.run_coroutine_threadsafe(_app2.process_update(update), _loop)
    return "ok", 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 10000)))
