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
    try:
        logger.info("🚀 Starting bot...")
        import sys
        if 'bot' in sys.modules:
            del sys.modules['bot']
        from bot import main
        main()
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
