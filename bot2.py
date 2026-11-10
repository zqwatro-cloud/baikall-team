"""
lang: Python 3.11+, file: bot2.py — главный бот тимы MITING TM
"""
import os, logging, random, asyncio, httpx
from datetime import datetime
from telegram import Update
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters,
)
from telegram.error import TimedOut, RetryAfter

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

BOT_TOKEN    = os.getenv("BOT_TOKEN2", "8834006042:AAGbcUOUB1dsoJEAY2wCyKalmda5oEb-Aio")
ADMIN_ID     = 8736990603
RELAY_USER   = "Giftlinkrelay"
PROFIT_CHAT  = -1004296528096
PROFIT_THREAD = 5
GROUP_LINK   = "https://t.me/+s23glGoKYzo5YjUx"
# file_id фото photo2.jpg — зададим после первого запуска через /setphoto
# пока используем путь к файлу при sendPhoto
PHOTO2_PATH  = "photo2.jpg"
PHOTO_PROFIT = "photo.jpg"

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
EM_STAR    = E("6028338546736107668", "⭐️")

# ========== СОСТОЯНИЯ ==========
_state: dict[int, dict] = {}
_payout_pending: dict[int, dict] = {}
_approved: set[int] = set()  # кто прошёл анкету и принят

# ========== КАПЧА ==========
CAPTCHAS = [
    {"question": "Выберите <b>огурец</b> 🥒", "correct": "🥒 Огурец",
     "options": ["🍎 Яблоко", "🥒 Огурец", "🍌 Банан", "🍇 Виноград"]},
    {"question": "Выберите <b>арбуз</b> 🍉", "correct": "🍉 Арбуз",
     "options": ["🍓 Клубника", "🍋 Лимон", "🍉 Арбуз", "🥝 Киви"]},
    {"question": "Выберите <b>лимон</b> 🍋", "correct": "🍋 Лимон",
     "options": ["🍋 Лимон", "🍑 Персик", "🍒 Вишня", "🥭 Манго"]},
]

# ========== RAW API ==========
async def _api(method: str, payload: dict, files=None):
    try:
        async with httpx.AsyncClient() as client:
            if files:
                r = await client.post(
                    f"https://api.telegram.org/bot{BOT_TOKEN}/{method}",
                    data=payload, files=files, timeout=30,
                )
            else:
                r = await client.post(
                    f"https://api.telegram.org/bot{BOT_TOKEN}/{method}",
                    json=payload, timeout=20,
                )
            data = r.json()
            if not data.get("ok"):
                log.error("%s: %s", method, data)
            return data.get("result")
    except Exception as e:
        log.error("%s: %s", method, e)

async def send_photo_file(chat_id, path, caption, rows=None, thread_id=None):
    """Отправка фото из файла через multipart."""
    try:
        with open(path, "rb") as f:
            payload = {"chat_id": str(chat_id), "parse_mode": "HTML"}
            if caption: payload["caption"] = caption
            if thread_id: payload["message_thread_id"] = str(thread_id)
            if rows: payload["reply_markup"] = str({"inline_keyboard": rows})
            # используем file_id если уже есть, иначе загружаем
            files = {"photo": f}
            # reply_markup нужно как json string
            import json
            if rows: payload["reply_markup"] = json.dumps({"inline_keyboard": rows})
            return await _api("sendPhoto", payload, files=files)
    except FileNotFoundError:
        # файл не найден — шлём только текст
        await _api("sendMessage", {
            "chat_id": chat_id, "text": caption, "parse_mode": "HTML",
            **({"reply_markup": {"inline_keyboard": rows}} if rows else {}),
            **({"message_thread_id": thread_id} if thread_id else {}),
        })

# ========== ТЕКСТЫ ==========
MENU_CAPTION = (
    f"<b>MITING TM</b>\n\n"
    f"<i>Бот для создания офферов</i>\n"
    f"<b>70/30</b> процентов\n\n"
    f"<code>Обновления в скором времени!</code>"
)

MENU_ROWS = [[
    {"text": "💸 Выплата", "callback_data": "payout", "style": "success"}
]]

async def send_menu(chat_id):
    """Отправляет главное меню с фото photo2.jpg."""
    await send_photo_file(chat_id, PHOTO2_PATH, MENU_CAPTION, MENU_ROWS)

async def send_captcha(chat_id: int, user_id: int):
    idx = random.randint(0, len(CAPTCHAS) - 1)
    cap = CAPTCHAS[idx]
    _state[user_id] = {"step": "captcha", "answers": [], "captcha_idx": idx}
    opts = cap["options"][:]
    random.shuffle(opts)
    rows = [[{"text": opt, "callback_data": f"cap|{opt}"}] for opt in opts]
    await _api("sendMessage", {
        "chat_id": chat_id,
        "text": f"{EM_WARN} <b>Проверка</b>\n\n{cap['question']}",
        "parse_mode": "HTML",
        "reply_markup": {"inline_keyboard": rows},
    })

# ========== HANDLERS ==========
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid in _approved:
        # уже одобрен — сразу меню
        await send_menu(update.effective_chat.id)
    else:
        await send_captcha(update.effective_chat.id, uid)

async def button_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    uid   = query.from_user.id
    data  = query.data
    try: await query.answer()
    except: pass

    # --- КАПЧА ---
    if data.startswith("cap|"):
        chosen = data[4:]
        st  = _state.get(uid, {})
        cap = CAPTCHAS[st.get("captcha_idx", 0)]
        if chosen != cap["correct"]:
            try:
                await query.edit_message_text(
                    f"{EM_CROSS} Неверно! Попробуйте снова.", parse_mode="HTML",
                )
            except: pass
            await asyncio.sleep(1)
            await send_captcha(uid, uid)
            return
        _state[uid] = {"step": "q1", "answers": []}
        try:
            await query.edit_message_text(
                f"{EM_OK} Верно!\n\n<b>Вопрос 1 из 3</b>\nЕсть ли у вас опыт в офферах?",
                parse_mode="HTML",
            )
        except: pass
        return

    # --- ВЫПЛАТА ---
    if data == "payout":
        _state[uid] = {"step": "payout_wait_photo"}
        try:
            await query.edit_message_caption(
                f"{EM_MONEY} <b>Заявка на выплату</b>\n\n"
                f"Прикрепите фото подтверждения передачи подарка на @{RELAY_USER}:",
                parse_mode="HTML",
            )
        except:
            await _api("sendMessage", {
                "chat_id": uid,
                "text": f"{EM_MONEY} <b>Заявка на выплату</b>\n\nПрикрепите фото подтверждения передачи подарка на @{RELAY_USER}:",
                "parse_mode": "HTML",
            })
        return

    # --- ADMIN: принять заявку ---
    if data.startswith("approve|"):
        applicant_id = int(data.split("|")[1])
        _approved.add(applicant_id)
        try:
            await query.edit_message_text(
                (query.message.text or "") + "\n\n✅ <b>Заявка принята</b>",
                parse_mode="HTML",
            )
        except: pass
        # отправляем пользователю ссылку на группу + меню
        await _api("sendMessage", {
            "chat_id": applicant_id,
            "text": f"{EM_OK} <b>Заявка принята!</b>\n\nДобро пожаловать в команду!\n\n{EM_GIFT} Вступите в нашу группу:",
            "parse_mode": "HTML",
            "reply_markup": {"inline_keyboard": [[
                {"text": "📢 Вступить в группу", "url": GROUP_LINK, "style": "primary"}
            ]]},
        })
        await asyncio.sleep(0.5)
        await send_menu(applicant_id)
        return

    # --- ADMIN: принять выплату ---
    if data.startswith("pay_approve|"):
        parts = data.split("|")
        payer_id  = int(parts[1])
        gift_link = parts[2] if len(parts) > 2 else "—"
        p = _payout_pending.get(payer_id, {})
        username    = p.get("username", "—")
        amount_ton  = p.get("amount", "—")
        buyer_share = p.get("buyer_share", "70")

        try:
            await query.edit_message_caption(
                (query.message.caption or "") + "\n\n✅ <b>Выплата одобрена</b>",
                parse_mode="HTML",
            )
        except:
            try:
                await query.edit_message_text(
                    (query.message.text or "") + "\n\n✅ <b>Выплата одобрена</b>",
                    parse_mode="HTML",
                )
            except: pass

        profit_text = (
            f"{EM_DIAMOND} <b>Новый профит!</b>\n"
            f"┠ {EM_MONEY} Сумма: <b>{amount_ton} TON</b>\n"
            f"┠ {EM_PERSON} Покупатель: @{username} (<code>{payer_id}</code>)\n"
            f"┠ {EM_MONEY} Доля покупателя: <b>{buyer_share}%</b>\n"
            f"┖ {EM_GIFT} Подарок: {gift_link}\n\n"
            f"{EM_SPARK} Отличная работа! Продолжай в том же духе."
        )
        await send_photo_file(PROFIT_CHAT, PHOTO_PROFIT, profit_text, thread_id=PROFIT_THREAD)
        return


async def msg_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    uid  = update.effective_user.id
    text = (update.message.text or "")
    st   = _state.get(uid, {})
    step = st.get("step", "")

    if step == "q1":
        st["answers"].append(text)
        st["step"] = "q2"
        await update.message.reply_text(
            "<b>Вопрос 2 из 3</b>\nСколько времени готовы уделять?", parse_mode="HTML",
        )
        return

    if step == "q2":
        st["answers"].append(text)
        st["step"] = "q3"
        await update.message.reply_text(
            "<b>Вопрос 3 из 3</b>\nОткуда узнали о нас?", parse_mode="HTML",
        )
        return

    if step == "q3":
        st["answers"].append(text)
        st["step"] = "done"
        user  = update.effective_user
        uname = f"@{user.username}" if user.username else user.first_name
        now   = datetime.now().strftime("%d.%m.%Y %H:%M")
        a     = st["answers"]
        await update.message.reply_text(
            f"{EM_OK} Заявка отправлена! Ожидайте ответа.", parse_mode="HTML",
        )
        await _api("sendMessage", {
            "chat_id": ADMIN_ID,
            "text": (
                f"{EM_WARN} <b>Новая заявка</b>\n\n"
                f"👤 {uname} (<code>{uid}</code>)\n"
                f"🕐 {now}\n\n"
                f"<b>Опыт:</b> {a[0]}\n"
                f"<b>Время:</b> {a[1]}\n"
                f"<b>Откуда:</b> {a[2]}"
            ),
            "parse_mode": "HTML",
            "reply_markup": {"inline_keyboard": [[
                {"text": "✅ Принять заявку", "callback_data": f"approve|{uid}", "style": "primary"}
            ]]},
        })
        return

    # фото для выплаты обрабатывается в photo_handler
    if step == "payout_wait_amount":
        parts     = text.split(maxsplit=1)
        amount    = parts[0] if parts else "—"
        gift_link = parts[1] if len(parts) > 1 else "—"
        now       = datetime.now().strftime("%d.%m.%Y %H:%M")
        user      = update.effective_user
        uname     = f"@{user.username}" if user.username else user.first_name
        p = _payout_pending.get(uid, {})
        p.update({"amount": amount, "gift_link": gift_link, "buyer_share": "70"})
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
        import json
        try:
            with open("photo2.jpg", "rb") as f:
                await _api("sendPhoto", {
                    "chat_id": str(ADMIN_ID),
                    "caption": pay_text,
                    "parse_mode": "HTML",
                    "reply_markup": json.dumps({"inline_keyboard": [[
                        {"text": "✅ Принять выплату",
                         "callback_data": f"pay_approve|{uid}|{gift_link}",
                         "style": "success"}
                    ]]}),
                }, files={"photo": f})
        except FileNotFoundError:
            # если нет photo2.jpg — шлём скрин пользователя
            await _api("sendPhoto", {
                "chat_id": ADMIN_ID,
                "photo": p["photo"],
                "caption": pay_text,
                "parse_mode": "HTML",
                "reply_markup": {"inline_keyboard": [[
                    {"text": "✅ Принять выплату",
                     "callback_data": f"pay_approve|{uid}|{gift_link}",
                     "style": "success"}
                ]]},
            })
        return


async def photo_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    uid  = update.effective_user.id
    st   = _state.get(uid, {})
    step = st.get("step", "")
    if step == "payout_wait_photo":
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
