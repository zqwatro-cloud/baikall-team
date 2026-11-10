from flask import Flask
import threading, os, time, requests, logging, asyncio, sys
from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
app = Flask(__name__)

@app.route('/')
def index(): return "MitingWork Bot is running!", 200
@app.route('/health')
def health(): return "OK", 200

def run_bot():
    async def _run():
        from bot2 import main
        # bot2.main() calls app.run_polling — run it differently
        from bot2 import BOT_TOKEN, cmd_start, button_handler, msg_handler, photo_handler
        from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters
        application = Application.builder().token(BOT_TOKEN).build()
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
    url = f"https://{os.environ.get('RENDER_EXTERNAL_HOSTNAME', 'mitingwork-bot.onrender.com')}/"
    while True:
        time.sleep(300)
        try: requests.get(url, timeout=5)
        except: pass

_started = False
def _start():
    global _started
    if _started: return
    _started = True
    threading.Thread(target=run_bot, daemon=True).start()
    threading.Thread(target=keep_alive, daemon=True).start()
_start()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 10000)))
