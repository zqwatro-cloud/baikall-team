"""
lang: Python 3.11+, file: bot2.py — главный бот тимы
"""
import os
import logging
import random
import asyncio
import httpx
from datetime import datetime
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters,
)
from telegram.error import TimedOut, RetryAfter

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

BOT_TOKEN  = os.getenv("BOT_TOKEN2", "8834006042:AAGbcUOUB1dsoJEAY2wCyKalmda5oEb-Aio")
ADMIN_ID   = 8736990603
RELAY_USER = "Giftlinkrelay"
PROFIT_CHAT = -1004296528096  # https://t.me/c/4296528096/5
PROFIT_THREAD = 5

# ========== ПРЕМИУМ ЭМОДЗИ ==========
def E(eid, fb): return f"<tg-emoji emoji-id='{eid}'>{fb}</tg-emoji>"
EM_DIAMOND = E("5451882949326409223", "💎")
EM_MONEY   = E("5445884630688014079", "💰")
EM_PERSON  = E("5440539497383087970", "👤")
EM_GIFT    = E("6037175527846975726", "🎁")
EM_SPARK   = E("5445284980978621387", "✨")
EM_OK      = E("5774022692642492953", "✅")
EM_CROSS   = E("5774077015388852135", "❌")
EM_WARN    = E("6030563507299160824", "❗️")

# ========== КАПЧА ==========
CAPTCHAS = [
    {
        "question": "Выберите <b>огурец</b> 🥒",
        "correct": "🥒 Огурец",
        "options": ["🍎 Яблоко", "🥒 Огурец", "🍌 Банан", "🍇 Виноград"],
    },
    {
        "question": "Выберите <b>арбуз</b> 🍉",
        "correct": "🍉 Арбуз",
        "options": ["🍓 Клубника", "🍋 Лимон", "🍉 Арбуз", "🥝 Киви"],
    },
    {
        "question": "Выберите <b>лимон</b> 🍋",
        "correct": "🍋 Лимон",
        "options": ["🍋 Лимон", "🍑 Персик", "🍒 Вишня", "🥭 Манго"],
    },
]

# ========== СОСТОЯНИЯ ==========
# user_id -> {"step": str, "answers": list, "captcha_idx": int}
_state: dict[int, dict] = {}

# pending payouts: user_id -> {"photo": file_id, "time": str, "gift_link": str}
_payout_pending: dict[int, dict] = {}

STEPS = ["captcha", "q1", "q2", "q3", "done"]

# ========== RAW API ==========
async def _api(method: str, payload: dict):
    try:
        async with httpx.AsyncClient() as client:
            r = await client.post(
                f"https://api.telegram.org/bot{BOT_TOKEN}/{method}",
                json=payload, timeout=20,
            )
            return r.json().get("result")
    except Exception as e:
        log.error("%s: %s", method, e)

# ========== МЕНЮ ==========
MENU_TEXT = (
    f"{EM_DIAMOND} <b>Главное меню</b>\n\n"
    f"Добро пожаловать в команду! Выберите действие:"
)

def menu_markup():
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("💸 Выплата", callback_data="payout"),
    ]])

async def send_menu(chat_id):
    await _api("sendMessage", {
        "chat_id": chat_id,
        "text": MENU_TEXT,
        "parse_mode": "HTML",
        "reply_markup": {"inline_keyboard": [[
            {"text": "💸 Выплата", "callback_data": "payout",
             "style": "success"}
        ]]},
    })

# ========== КАПЧА ==========
def captcha_markup(options: list):
    rows = [[{"text": opt, "callback_data": f"cap|{opt}"}] for opt in options]
    return rows

async def send_captcha(chat_id: int, user_id: int):
    idx = random.randint(0, len(CAPTCHAS) - 1)
    cap = CAPTCHAS[idx]
    _state[user_id] = {"step": "captcha", "answers": [], "captcha_idx": idx}
    opts = cap["options"][:]
    random.shuffle(opts)
    await _api("sendMessage", {
        "chat_id": chat_id,
        "text": f"{EM_WARN} <b>Проверка</b>\n\n{cap['question']}",
        "parse_mode": "HTML",
        "reply_markup": {"inline_keyboard": captcha_markup(opts)},
    })

# ========== HANDLERS ==========
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await send_captcha(update.effective_chat.id, update.effective_user.id)

async def button_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    uid   = query.from_user.id
    data  = query.data
    try: await query.answer()
    except: pass

    # --- КАПЧА ---
    if data.startswith("cap|"):
        chosen = data[4:]
        st = _state.get(uid, {})
        cap = CAPTCHAS[st.get("captcha_idx", 0)]
        if chosen != cap["correct"]:
            await query.edit_message_text(
                f"{EM_CROSS} Неверно! Попробуйте снова.",
                parse_mode="HTML",
            )
            await asyncio.sleep(1)
            await send_captcha(uid, uid)
            return
        # верно — первый вопрос
        _state[uid] = {"step": "q1", "answers": []}
        await query.edit_message_text(
            f"{EM_OK} Верно!\n\n<b>Вопрос 1 из 3</b>\nЕсть ли у вас опыт в офферах?",
            parse_mode="HTML",
        )
        return

    # --- ВЫПЛАТА ---
    if data == "payout":
        _state[uid] = {"step": "payout_wait_photo"}
        await query.edit_message_text(
            f"{EM_MONEY} <b>Заявка на выплату</b>\n\n"
            f"Прикрепите фото подтверждения передачи подарка на @{RELAY_USER}:",
            parse_mode="HTML",
        )
        return

    # --- ПРИШЛА ФОТКА ДЛЯ ВЫПЛАТЫ (кнопка "отмена") ---
    if data == "payout_cancel":
        _state.pop(uid, None)
        await send_menu(uid)
        return

    # --- ADMIN: принять заявку ---
    if data.startswith("approve|"):
        applicant_id = int(data.split("|")[1])
        await query.edit_message_text(
            query.message.text + "\n\n✅ <b>Заявка принята</b>",
            parse_mode="HTML",
        )
        await send_menu(applicant_id)
        return

    # --- ADMIN: принять выплату ---
    if data.startswith("pay_approve|"):
        parts = data.split("|")
        payer_id = int(parts[1])
        gift_link = parts[2] if len(parts) > 2 else "—"
        p = _payout_pending.get(payer_id, {})
        username = p.get("username", "—")
        amount_ton = p.get("amount", "—")
        buyer_share = p.get("buyer_share", "70")

        await query.edit_message_text(
            query.message.text + "\n\n✅ <b>Выплата одобрена</b>",
            parse_mode="HTML",
        )

        # сообщение в группу
        profit_text = (
            f"{EM_DIAMOND} <b>Новый профит!</b>\n"
            f"┠ {EM_MONEY} Сумма: <b>{amount_ton} TON</b>\n"
            f"┠ {EM_PERSON} Покупатель: @{username} (<code>{payer_id}</code>)\n"
            f"┠ {EM_MONEY} Доля покупателя: <b>{buyer_share}%</b>\n"
            f"┖ {EM_GIFT} Подарок: {gift_link}\n\n"
            f"{EM_SPARK} Отличная работа! Продолжай в том же духе."
        )

        await _api("sendPhoto", {
            "chat_id": PROFIT_CHAT,
            "message_thread_id": PROFIT_THREAD,
            "photo": "photo.jpg",
            "caption": profit_text,
            "parse_mode": "HTML",
        })
        return


async def msg_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid  = update.effective_user.id
    text = update.message.text or ""
    st   = _state.get(uid, {})
    step = st.get("step", "")

    # --- АНКЕТА ---
    if step == "q1":
        st["answers"].append(text)
        st["step"] = "q2"
        await update.message.reply_text(
            "<b>Вопрос 2 из 3</b>\nСколько времени готовы уделять?",
            parse_mode="HTML",
        )
        return

    if step == "q2":
        st["answers"].append(text)
        st["step"] = "q3"
        await update.message.reply_text(
            "<b>Вопрос 3 из 3</b>\nОткуда узнали о нас?",
            parse_mode="HTML",
        )
        return

    if step == "q3":
        st["answers"].append(text)
        st["step"] = "done"
        user = update.effective_user
        uname = f"@{user.username}" if user.username else user.first_name
        now = datetime.now().strftime("%d.%m.%Y %H:%M")
        a = st["answers"]

        await update.message.reply_text(
            f"{EM_OK} Заявка отправлена! Ожидайте ответа.",
            parse_mode="HTML",
        )

        app_text = (
            f"{EM_WARN} <b>Новая заявка</b>\n\n"
            f"👤 {uname} (<code>{uid}</code>)\n"
            f"🕐 {now}\n\n"
            f"<b>Опыт:</b> {a[0]}\n"
            f"<b>Время:</b> {a[1]}\n"
            f"<b>Откуда:</b> {a[2]}"
        )
        await _api("sendMessage", {
            "chat_id": ADMIN_ID,
            "text": app_text,
            "parse_mode": "HTML",
            "reply_markup": {"inline_keyboard": [[
                {"text": "✅ Принять заявку", "callback_data": f"approve|{uid}",
                 "style": "primary"}
            ]]},
        })
        return

    # --- ФОТО ДЛЯ ВЫПЛАТЫ ---
    if step == "payout_wait_photo" and update.message.photo:
        # ждём следующего сообщения с суммой и ссылкой
        file_id = update.message.photo[-1].file_id
        _payout_pending[uid] = {
            "photo": file_id,
            "username": update.effective_user.username or str(uid),
        }
        _state[uid] = {"step": "payout_wait_amount"}
        await update.message.reply_text(
            "Введите сумму в TON и ссылку на подарок через пробел:\n"
            "<i>Пример: 5.00 https://t.me/nft/...</i>",
            parse_mode="HTML",
        )
        return

    if step == "payout_wait_amount":
        parts = text.split(maxsplit=1)
        amount = parts[0] if parts else "—"
        gift_link = parts[1] if len(parts) > 1 else "—"
        now = datetime.now().strftime("%d.%m.%Y %H:%M")
        user = update.effective_user
        uname = f"@{user.username}" if user.username else user.first_name

        p = _payout_pending.get(uid, {})
        p["amount"] = amount
        p["gift_link"] = gift_link
        p["buyer_share"] = "70"
        _payout_pending[uid] = p
        _state.pop(uid, None)

        await update.message.reply_text(f"{EM_OK} Заявка на выплату отправлена!", parse_mode="HTML")

        pay_text = (
            f"{EM_MONEY} <b>Заявка на выплату</b>\n\n"
            f"👤 {uname} (<code>{uid}</code>)\n"
            f"🕐 {now}\n"
            f"💰 Сумма: <b>{amount} TON</b>\n"
            f"🎁 Подарок: {gift_link}"
        )
        await _api("sendPhoto", {
            "chat_id": ADMIN_ID,
            "photo": p["photo"],
            "caption": pay_text,
            "parse_mode": "HTML",
            "reply_markup": {"inline_keyboard": [[
                {"text": "✅ Принять выплату", "callback_data": f"pay_approve|{uid}|{gift_link}",
                 "style": "success"}
            ]]},
        })
        return


async def photo_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Отдельный handler для фото."""
    await msg_handler(update, ctx)


def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.PHOTO, photo_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, msg_handler))
    log.info("bot2 started")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
