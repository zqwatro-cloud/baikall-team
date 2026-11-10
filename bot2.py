"""
lang: Python 3.11+, file: bot2.py — главный бот тимы MITING TM
"""
import os, logging, random, asyncio, httpx, json, re
from datetime import datetime
from telegram import Update
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters,
)
from telegram.error import TimedOut, RetryAfter

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

BOT_TOKEN     = os.getenv("BOT_TOKEN2", "8834006042:AAGbcUOUB1dsoJEAY2wCyKalmda5oEb-Aio")
ADMIN_ID      = 8736990603
RELAY_USER    = "Giftlinkrelay"
PROFIT_CHAT   = -1004296528096
PROFIT_THREAD = 5
GROUP_LINK    = "https://t.me/+s23glGoKYzo5YjUx"
PHOTO2_PATH   = "photo2.jpg"
PHOTO_PROFIT  = "photo.jpg"

SUPABASE_URL  = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY  = os.getenv("SUPABASE_KEY", "")

# ========== SUPABASE ==========
async def sb_get(table: str, qs: str = "") -> list:
    if not SUPABASE_URL:
        return []
    async with httpx.AsyncClient() as c:
        r = await c.get(
            f"{SUPABASE_URL}/rest/v1/{table}?{qs}",
            headers={"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"},
            timeout=10,
        )
    return r.json() if r.status_code == 200 else []

async def sb_upsert(table: str, data: dict) -> bool:
    if not SUPABASE_URL:
        return False
    async with httpx.AsyncClient() as c:
        r = await c.post(
            f"{SUPABASE_URL}/rest/v1/{table}",
            headers={
                "apikey": SUPABASE_KEY,
                "Authorization": f"Bearer {SUPABASE_KEY}",
                "Content-Type": "application/json",
                "Prefer": "resolution=merge-duplicates",
            },
            content=json.dumps(data), timeout=10,
        )
    return r.status_code in (200, 201)

async def sb_patch(table: str, qs: str, data: dict) -> bool:
    if not SUPABASE_URL:
        return False
    async with httpx.AsyncClient() as c:
        r = await c.patch(
            f"{SUPABASE_URL}/rest/v1/{table}?{qs}",
            headers={
                "apikey": SUPABASE_KEY,
                "Authorization": f"Bearer {SUPABASE_KEY}",
                "Content-Type": "application/json",
            },
            content=json.dumps(data), timeout=10,
        )
    return r.status_code in (200, 204)

async def get_member(user_id: int) -> dict | None:
    rows = await sb_get("members", f"user_id=eq.{user_id}")
    return rows[0] if rows else None

# ========== ЭМОДЗИ ==========
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
_approved: set[int] = set()

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
    try:
        with open(path, "rb") as f:
            payload = {"chat_id": str(chat_id), "parse_mode": "HTML"}
            if caption:   payload["caption"] = caption
            if thread_id: payload["message_thread_id"] = str(thread_id)
            if rows:      payload["reply_markup"] = json.dumps({"inline_keyboard": rows})
            return await _api("sendPhoto", payload, files={"photo": f})
    except FileNotFoundError:
        await _api("sendMessage", {
            "chat_id": chat_id, "text": caption, "parse_mode": "HTML",
            **({"reply_markup": {"inline_keyboard": rows}} if rows else {}),
            **({"message_thread_id": thread_id} if thread_id else {}),
        })

# ========== МЕНЮ ==========
MENU_CAPTION = (
    f"<b>MITING TM</b>\n\n"
    f"<i>Бот для создания офферов</i>\n"
    f"<b>70/30</b> процентов\n\n"
    f"<code>Обновления в скором времени!</code>"
)

MENU_ROWS = [
    [{"text": "👤 Профиль", "callback_data": "profile",  "style": "primary"}],
    [{"text": "💸 Выплата",  "callback_data": "payout",   "style": "success"}],
]

async def send_menu(chat_id):
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

# ========== ПРОФИЛЬ ==========
async def show_profile(chat_id: int, user_id: int):
    m = await get_member(user_id)
    if not m:
        await _api("sendMessage", {"chat_id": chat_id,
            "text": f"{EM_CROSS} Профиль не найден.", "parse_mode": "HTML"})
        return

    username = m.get("username") or str(user_id)
    earned   = m.get("earned_gram") or 0
    wallet   = m.get("wallet")
    try:
        dt = datetime.fromisoformat(str(m.get("joined_at", "")).replace("Z", "+00:00"))
        joined_str = dt.strftime("%d.%m.%Y %H:%M")
    except Exception:
        joined_str = "—"

    wallet_line = f"Кошелёк: <code>{wallet}</code>" if wallet else "Кошелёк: не указан"
    wallet_btn  = "✏️ Изменить кошелёк" if wallet else "💳 Указать кошелёк"

    text = (
        f"{EM_PERSON} <b>Профиль</b>\n\n"
        f"Имя: @{username}\n"
        f"ID: <code>{user_id}</code>\n\n"
        f"{EM_DIAMOND} Заработано: <b>{earned} gram</b>\n"
        f"{wallet_line}\n\n"
        f"В команде с: {joined_str}\n\n"
        f"🎓 Куратор не выбран <i>(временно недоступно)</i>. Он поможет с обучением и вопросами.\n"
        f"С куратором: вам <b>70%</b>, куратору <b>15%</b> от полного профита. Выбор навсегда."
    )
    rows = [
        [{"text": wallet_btn, "callback_data": "set_wallet"}],
        [{"text": "← Назад",  "callback_data": "back_menu"}],
    ]
    await _api("sendMessage", {
        "chat_id": chat_id, "text": text, "parse_mode": "HTML",
        "link_preview_options": {"is_disabled": True},
        "reply_markup": {"inline_keyboard": rows},
    })

# ========== HANDLERS ==========
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not _approved:
        for row in await sb_get("members", "select=user_id"):
            _approved.add(row["user_id"])
    if uid in _approved:
        await send_menu(update.effective_chat.id)
    else:
        await send_captcha(update.effective_chat.id, uid)

async def button_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    uid   = query.from_user.id
    data  = query.data
    try: await query.answer()
    except: pass
    chat_id = query.message.chat_id if query.message else uid

    # КАПЧА
    if data.startswith("cap|"):
        chosen = data[4:]
        st  = _state.get(uid, {})
        cap = CAPTCHAS[st.get("captcha_idx", 0)]
        if chosen != cap["correct"]:
            try: await query.edit_message_text(f"{EM_CROSS} Неверно! Попробуйте снова.", parse_mode="HTML")
            except: pass
            await asyncio.sleep(1)
            await send_captcha(uid, uid)
            return
        _state[uid] = {"step": "q1", "answers": []}
        try:
            await query.edit_message_text(
                f"{EM_OK} Верно!\n\n<b>Вопрос 1 из 3</b>\nЕсть ли у вас опыт в офферах?",
                parse_mode="HTML")
        except: pass
        return

    # ПРОФИЛЬ
    if data == "profile":
        await show_profile(chat_id, uid)
        return

    # НАЗАД В МЕНЮ
    if data == "back_menu":
        try: await query.message.delete()
        except: pass
        await send_menu(chat_id)
        return

    # УКАЗАТЬ КОШЕЛЁК
    if data == "set_wallet":
        _state[uid] = {"step": "wait_wallet"}
        await _api("sendMessage", {"chat_id": chat_id,
            "text": "💳 Введите адрес вашего TON кошелька:", "parse_mode": "HTML"})
        return

    # ВЫПЛАТА
    if data == "payout":
        m = await get_member(uid)
        wallet = m.get("wallet") if m else None
        _payout_pending[uid] = {
            "username": query.from_user.username or str(uid),
            "wallet": wallet,
        }
        _state[uid] = {"step": "payout_wait_photo"}
        caption = (
            f"{EM_MONEY} <b>Заявка на выплату</b>\n\n"
            + (f"Кошелёк: <code>{wallet}</code>\n\n" if wallet else "")
            + f"Прикрепите фото подтверждения передачи подарка на @{RELAY_USER}:"
        )
        try: await query.edit_message_caption(caption, parse_mode="HTML")
        except:
            await _api("sendMessage", {"chat_id": uid, "text": caption, "parse_mode": "HTML",
                "link_preview_options": {"is_disabled": True}})
        return

    # ADMIN: принять заявку
    if data.startswith("approve|"):
        applicant_id = int(data.split("|")[1])
        uname = ""
        if query.message and query.message.text:
            m2 = re.search(r"@(\w+)", query.message.text)
            if m2: uname = m2.group(1)
        await sb_upsert("members", {
            "user_id": applicant_id, "username": uname,
            "joined_at": datetime.utcnow().isoformat(), "earned_gram": 0,
        })
        _approved.add(applicant_id)
        try:
            await query.edit_message_text(
                (query.message.text or "") + "\n\n✅ <b>Заявка принята</b>", parse_mode="HTML")
        except: pass
        await _api("sendMessage", {
            "chat_id": applicant_id,
            "text": f"{EM_OK} <b>Заявка принята!</b>\n\nДобро пожаловать в команду!\n\n{EM_GIFT} Вступите в нашу группу:",
            "parse_mode": "HTML",
            "link_preview_options": {"is_disabled": True},
            "reply_markup": {"inline_keyboard": [[
                {"text": "📢 Вступить в группу", "url": GROUP_LINK, "style": "primary"}
            ]]},
        })
        await asyncio.sleep(0.5)
        await send_menu(applicant_id)
        return

    # ADMIN: принять выплату
    if data.startswith("pay_approve|"):
        parts     = data.split("|")
        payer_id  = int(parts[1])
        gift_link = parts[2] if len(parts) > 2 else "—"
        p         = _payout_pending.get(payer_id, {})
        username  = p.get("username", "—")
        amount    = p.get("amount", "—")
        wallet    = p.get("wallet") or "не указан"

        mem = await get_member(payer_id)
        if mem:
            current = float(mem.get("earned_gram") or 0)
            try: new_val = current + float(amount)
            except: new_val = current
            await sb_patch("members", f"user_id=eq.{payer_id}", {"earned_gram": new_val})

        try: await query.edit_message_caption(
            (query.message.caption or "") + "\n\n✅ <b>Выплата одобрена</b>", parse_mode="HTML")
        except:
            try: await query.edit_message_text(
                (query.message.text or "") + "\n\n✅ <b>Выплата одобрена</b>", parse_mode="HTML")
            except: pass

        profit_text = (
            f"{EM_DIAMOND} <b>Новый профит!</b>\n"
            f"┠ {EM_MONEY} Сумма: <b>{amount} gram</b>\n"
            f"┠ {EM_PERSON} Исполнитель: @{username} (<code>{payer_id}</code>)\n"
            f"┠ 💳 Кошелёк: <code>{wallet}</code>\n"
            f"┖ {EM_GIFT} Подарок: {gift_link}\n\n"
            f"{EM_SPARK} Отличная работа! Продолжай в том же духе."
        )
        await send_photo_file(PROFIT_CHAT, PHOTO_PROFIT, profit_text, thread_id=PROFIT_THREAD)
        return


async def msg_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    uid  = update.effective_user.id
    text = update.message.text or ""
    st   = _state.get(uid, {})
    step = st.get("step", "")

    # КОШЕЛЁК
    if step == "wait_wallet":
        wallet = text.strip()
        ok = await sb_patch("members", f"user_id=eq.{uid}", {"wallet": wallet})
        _state.pop(uid, None)
        msg = f"{EM_OK} Кошелёк сохранён:\n<code>{wallet}</code>" if ok else f"{EM_CROSS} Ошибка, попробуйте позже."
        await update.message.reply_text(msg, parse_mode="HTML")
        return

    # АНКЕТА
    if step == "q1":
        st["answers"].append(text); st["step"] = "q2"
        await update.message.reply_text("<b>Вопрос 2 из 3</b>\nСколько времени готовы уделять?", parse_mode="HTML")
        return
    if step == "q2":
        st["answers"].append(text); st["step"] = "q3"
        await update.message.reply_text("<b>Вопрос 3 из 3</b>\nОткуда узнали о нас?", parse_mode="HTML")
        return
    if step == "q3":
        st["answers"].append(text); st["step"] = "done"
        user  = update.effective_user
        uname = f"@{user.username}" if user.username else user.first_name
        now   = datetime.now().strftime("%d.%m.%Y %H:%M")
        a     = st["answers"]
        await update.message.reply_text(f"{EM_OK} Заявка отправлена! Ожидайте ответа.", parse_mode="HTML")
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
            "link_preview_options": {"is_disabled": True},
            "reply_markup": {"inline_keyboard": [[
                {"text": "✅ Принять заявку", "callback_data": f"approve|{uid}", "style": "primary"}
            ]]},
        })
        return

    # СУММА + ССЫЛКА ДЛЯ ВЫПЛАТЫ
    if step == "payout_wait_amount":
        parts     = text.split(maxsplit=1)
        amount    = parts[0] if parts else "—"
        gift_link = parts[1] if len(parts) > 1 else "—"
        p = _payout_pending.get(uid, {})
        p.update({"amount": amount, "gift_link": gift_link})
        _payout_pending[uid] = p
        _state.pop(uid, None)
        wallet = p.get("wallet") or "не указан"
        await update.message.reply_text(f"{EM_OK} Заявка на выплату отправлена!", parse_mode="HTML")
        pay_text = (
            f"{EM_MONEY} <b>Заявка на выплату</b>\n\n"
            f"👤 @{p.get('username','—')} (<code>{uid}</code>)\n"
            f"🕐 {datetime.now().strftime('%d.%m.%Y %H:%M')}\n"
            f"💰 Сумма: <b>{amount} gram</b>\n"
            f"💳 Кошелёк: <code>{wallet}</code>\n"
            f"🎁 Подарок: {gift_link}"
        )
        rows = [[{"text": "✅ Принять выплату",
                  "callback_data": f"pay_approve|{uid}|{gift_link}", "style": "success"}]]
        try:
            with open(PHOTO2_PATH, "rb") as f:
                await _api("sendPhoto", {
                    "chat_id": str(ADMIN_ID), "caption": pay_text,
                    "parse_mode": "HTML", "reply_markup": json.dumps({"inline_keyboard": rows}),
                }, files={"photo": f})
        except FileNotFoundError:
            await _api("sendMessage", {"chat_id": ADMIN_ID, "text": pay_text,
                "parse_mode": "HTML", "link_preview_options": {"is_disabled": True},
                "reply_markup": {"inline_keyboard": rows}})
        return


async def photo_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    uid  = update.effective_user.id
    st   = _state.get(uid, {})
    if st.get("step") != "payout_wait_photo":
        return
    file_id = update.message.photo[-1].file_id
    p = _payout_pending.setdefault(uid, {})
    p["photo"] = file_id
    p.setdefault("username", update.effective_user.username or str(uid))
    wallet = p.get("wallet")

    if wallet:
        # кошелёк уже есть — сразу просим сумму+ссылку
        _state[uid] = {"step": "payout_wait_amount"}
        await update.message.reply_text(
            f"💳 Кошелёк: <code>{wallet}</code>\n\n"
            "Введите сумму и ссылку на подарок через пробел:\n"
            "<i>Пример: 5.00 https://t.me/nft/...</i>",
            parse_mode="HTML",
        )
    else:
        _state[uid] = {"step": "payout_wait_amount"}
        await update.message.reply_text(
            "Введите сумму в gram и ссылку на подарок через пробел:\n"
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
