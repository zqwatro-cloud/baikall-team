from flask import Flask
import threading
import os
import time
import requests
import logging
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

@app.route('/')
def index():
    return "GiftChanger Bot is running!", 200

@app.route('/health')
def health():
    return "OK", 200


def run_bot():
    import asyncio
    import sys

    async def _run():
        if 'bot' in sys.modules:
            del sys.modules['bot']
        from bot import BOT_TOKEN, inline_query, button_handler, cmd_start, chosen_inline_result
        from telegram.ext import Application, InlineQueryHandler, CallbackQueryHandler, CommandHandler, ChosenInlineResultHandler

        app = Application.builder().token(BOT_TOKEN).build()
        app.add_handler(CommandHandler("start", cmd_start))
        app.add_handler(InlineQueryHandler(inline_query))
        app.add_handler(ChosenInlineResultHandler(chosen_inline_result))
        app.add_handler(CallbackQueryHandler(button_handler))

        logger.info("🚀 Bot initializing...")
        await app.initialize()
        await app.start()
        await app.updater.start_polling(drop_pending_updates=True)
        logger.info("✅ Bot polling started")

        # держим живым пока поток жив
        while True:
            await asyncio.sleep(3600)

    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(_run())
    except Exception as e:
        logger.error(f"❌ Bot crashed: {e}")
        import traceback
        traceback.print_exc()


def keep_alive():
    url = f"https://{os.environ.get('RENDER_EXTERNAL_HOSTNAME', 'giftchanger-bot.onrender.com')}/"
    while True:
        time.sleep(300)
        try:
            requests.get(url, timeout=5)
            logger.info("✅ Keep-alive ping sent")
        except Exception as e:
            logger.error(f"❌ Keep-alive error: {e}")


_bot_started = False

def _start_background_threads():
    global _bot_started
    if _bot_started:
        return
    _bot_started = True
    logger.info("🔧 Starting background threads...")
    threading.Thread(target=run_bot, daemon=True).start()
    logger.info("🤖 Bot thread started")
    threading.Thread(target=keep_alive, daemon=True).start()
    logger.info("🔄 Keep-alive thread started")

_start_background_threads()


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    logger.info(f"🌐 Flask server starting on port {port}")
    app.run(host='0.0.0.0', port=port)
