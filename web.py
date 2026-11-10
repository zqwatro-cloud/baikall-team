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

@app.errorhandler(400)
def _on_400(e):
    try:
        raw = freq.get_data(cache=False)
    except Exception as ex:
        raw = f"<get_data failed: {ex}>".encode()
    logger.error(
        "400 on %s %s | CT=%r CL=%r | raw[:300]=%r",
        freq.method, freq.path,
        freq.headers.get("Content-Type"), freq.headers.get("Content-Length"),
        raw[:300],
    )
    return "bad request logged", 400

BOT_TOKEN  = os.getenv("BOT_TOKEN",  "9104054497:AAGWash0tIUfEpGxUND7PeRKLxrgonJuZQQ")
BOT_TOKEN2 = os.getenv("BOT_TOKEN2", "8834006042:AAGbcUOUB1dsoJEAY2wCyKalmda5oEb-Aio")
HOST       = os.getenv("RENDER_EXTERNAL_HOSTNAME", "giftchanger-bot.onrender.com")

_app1 = None
_app2 = None
_loop = None
_ready = threading.Event()

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
    logger.info("🗑 Old webhooks deleted")

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

    async def on_error1(update, ctx):
        logger.error("app1 error: %s", ctx.error, exc_info=ctx.error)
    _app1.add_error_handler(on_error1)

    await _app1.initialize()
    await _app1.start()

    try:
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

        async def on_error2(update, ctx):
            logger.error("app2 error: %s", ctx.error, exc_info=ctx.error)
        _app2.add_error_handler(on_error2)

        await _app2.initialize()
        await _app2.start()
        logger.info("✅ app2 started OK")
    except Exception as e:
        import traceback
        logger.error("❌ app2 FAILED: %s\n%s", e, traceback.format_exc())

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
    _ready.set()

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

# ========== ROUTES ==========
@app.route('/')
def index(): return "Bots running (webhook)", 200

@app.route('/health')
def health(): return "OK", 200

def _parse_update():
    try:
        raw = freq.get_data()
        return json.loads(raw)
    except Exception as e:
        logger.error("Bad webhook body: %r", e)
        return None

@app.route('/webhook1', methods=['POST'])
def webhook1():
    _ready.wait(timeout=30)  # ждём инициализации максимум 30с
    if not _ready.is_set():
        logger.warning("webhook1: not ready after 30s")
        return "starting", 200
    data = _parse_update()
    if not data or _app1 is None:
        abort(400)
    logger.info("webhook1 update type: %s", list(data.keys()))
    from telegram import Update
    update = Update.de_json(data, _app1.bot)
    asyncio.run_coroutine_threadsafe(_app1.process_update(update), _loop)
    return "ok", 200

@app.route('/webhook2', methods=['POST'])
def webhook2():
    _ready.wait(timeout=30)
    if not _ready.is_set():
        logger.warning("webhook2: not ready after 30s")
        return "starting", 200
    data = _parse_update()
    if not data or _app2 is None:
        abort(400)
    logger.info("webhook2 update type: %s", list(data.keys()))
    from telegram import Update
    update = Update.de_json(data, _app2.bot)
    asyncio.run_coroutine_threadsafe(_app2.process_update(update), _loop)
    return "ok", 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 10000)))
