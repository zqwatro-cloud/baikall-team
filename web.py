from flask import Flask
import threading, os, time, requests, logging, asyncio
from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
app = Flask(__name__)

@app.route('/')
def index(): return "Bots are running!", 200
@app.route('/health')
def health(): return "OK", 200

def run_bot1():
    async def _run():
        from bot import BOT_TOKEN, inline_query, button_handler, cmd_start, chosen_inline_result, cmd_mitingteamwork
        from telegram.ext import Application, InlineQueryHandler, CallbackQueryHandler, CommandHandler, ChosenInlineResultHandler
        application = Application.builder().token(BOT_TOKEN).build()
        application.add_handler(CommandHandler("start", cmd_start))
        application.add_handler(CommandHandler("mitingteamwork", cmd_mitingteamwork))
        application.add_handler(InlineQueryHandler(inline_query))
        application.add_handler(ChosenInlineResultHandler(chosen_inline_result))
        application.add_handler(CallbackQueryHandler(button_handler))
        logger.info("🚀 Bot1 initializing...")
        await application.initialize()
        await application.start()
        await application.updater.start_polling(drop_pending_updates=True)
        logger.info("✅ Bot1 polling started")
        while True:
            await asyncio.sleep(3600)
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(_run())
    except Exception as e:
        logger.error(f"❌ Bot1 crashed: {e}")
        import traceback; traceback.print_exc()

def run_bot2():
    async def _run():
        from bot2 import BOT_TOKEN as BOT_TOKEN2, cmd_start, button_handler, msg_handler, photo_handler
        from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters
        application = Application.builder().token(BOT_TOKEN2).build()
        application.add_handler(CommandHandler("start", cmd_start))
        application.add_handler(CallbackQueryHandler(button_handler))
        application.add_handler(MessageHandler(filters.PHOTO, photo_handler))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, msg_handler))
        logger.info("🚀 Bot2 initializing...")
        await application.initialize()
        await application.start()
        await application.updater.start_polling(drop_pending_updates=True)
        logger.info("✅ Bot2 polling started")
        while True:
            await asyncio.sleep(3600)
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(_run())
    except Exception as e:
        logger.error(f"❌ Bot2 crashed: {e}")
        import traceback; traceback.print_exc()

def keep_alive():
    url = f"https://{os.environ.get('RENDER_EXTERNAL_HOSTNAME', 'giftchanger-bot.onrender.com')}/"
    while True:
        time.sleep(300)
        try: requests.get(url, timeout=5)
        except: pass

_started = False
def _start():
    global _started
    if _started: return
    _started = True
    logger.info("🔧 Starting background threads...")
    threading.Thread(target=run_bot1, daemon=True).start()
    logger.info("🤖 Bot1 thread started")
    threading.Thread(target=run_bot2, daemon=True).start()
    logger.info("🤖 Bot2 thread started")
    threading.Thread(target=keep_alive, daemon=True).start()
    logger.info("🔄 Keep-alive thread started")
_start()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 10000)))
