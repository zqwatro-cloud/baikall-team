"""
lang: Python 3.11+, file: bot2.py — MITING TM panel bot (clean rewrite)
"""
import os, logging, random, asyncio, json, re
from datetime import datetime

import httpx
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputFile
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters,
)

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

BOT_TOKEN     = os.getenv("BOT_TOKEN2", "8834006042:AAGbcUOUB1dsoJEAY2wCyKalmda5oEb-Aio")
ADMIN_ID      = 8736990603
RELAY_USER    = "Giftlinkrelay"
PROFIT_CHAT   = -1004296528096
PROFIT_THREAD = 5
GROUP_LINK    = "https://t.me/+s23glGoKYzo5YjUx"

_BASE        = os.path.dirname(os.path.abspath(__file__))
PHOTO2_PATH  = os.path.join(_BASE, "photo2.jpg")
PHOTO_PROFIT = os.path.join(_BASE, "photo.jpg")

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")

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

# ========== HELPERS ==========
def kb(rows: list) -> InlineKeyboardMarkup:
    buttons = []
    for row in rows:
        line = []
        for text, data in row:
            if data.startswith("http"):
                line.append(InlineKeyboardButton(text, url=data))
            else:
                line.append(InlineKeyboardButton(text, callback_data=data))
        buttons.append(line)
    return InlineKeyboardMarkup(buttons)

async def send_photo(bot, chat_id, path, caption, markup=None, thread_id=None):
    kwargs = dict(chat_id=chat_id, caption=caption, parse_mode="HTML", reply_markup=markup)
    if thread_id:
        kwargs["message_thread_id"] = thread_id
    if os.path.exists(path):
        try:
            with open(path, "rb") as f:
                return await bot.send_photo(photo=InputFile(f), **kwargs)
        except Exception as e:
            log.warning("send_photo failed: %s", e)
    del kwargs["caption"]
    kwargs["text"] = caption
    kwargs["disable_web_page_preview"] = True
    return await bot.send_message(**kwargs)

# ========== МЕНЮ ==========
MENU_TEXT = (
    "<b>MITING TM</b>\n\n"
    "<i>Бот для создания офферов</i>\n"
    "<b>70/30</b> процентов\n\n"
    "<code>Обновления в скором времени!</code>"
)
MENU_KB = kb([
    [("👤 Профиль", "profile")],
    [("💸 Выплата",  "payout")],
])

async def send_menu(bot, chat_id):
    await send_photo(bot, chat_id, PHOTO2_PATH, MENU_TEXT, MENU_KB)

async def send_captcha(bot, chat_id: int, user_id: int):
    idx = random.randint(0, len(CAPTCHAS) - 1)
    cap = CAPTCHAS[idx]
    _state[user_id] = {"step": "captcha", "captcha_idx": idx, "answers": []}
    opts = cap["options"][:]
    random.shuffle(opts)
    markup = kb([[(opt, f"cap|{opt}")] for opt in opts])
    await bot.send_message(
        chat_id=chat_id,
        text=f"❗️ <b>Проверка</b>\n\n{cap['question']}",
        parse_mode="HTML",
        reply_markup=markup,
    )

# ========== ПРОФИЛЬ ==========
async def show_profile(bot, chat_id: int, user_id: int, username: str = ""):
    m = await get_member(user_id)
    if not m:
        m = {"username": username or str(user_id), "earned_gram": 0, "wallet": None, "joined_at": None}

    uname  = m.get("username") or str(user_id)
    earned = m.get("earned_gram") or 0
    wallet = m.get("wallet")
    try:
        dt = datetime.fromisoformat(str(m.get("joined_at", "")).replace("Z", "+00:00"))
        joined_str = dt.strftime("%d.%m.%Y %H:%M")
    except Exception:
        joined_str = "—"

    wallet_line = f"Кошелёк: <code>{wallet}</code>" if wallet else "Кошелёк: не указан"
    wallet_btn  = ("✏️ Изменить кошелёк", "set_wallet") if wallet else ("💳 Указать кошелёк", "set_wallet")

    text = (
        f"👤 <b>Профиль</b>\n\n"
        f"Имя: @{uname}\n"
        f"ID: <code>{user_id}</code>\n\n"
        f"💎 Заработано: <b>{earned} gram</b>\n"
        f"{wallet_line}\n\n"
        f"В команде с: {joined_str}\n\n"
        f"🎓 Куратор не выбран <i>(временно недоступно)</i>.\n"
        f"С куратором: вам <b>70%</b>, куратору <b>15%</b>. Выбор навсегда."
    )
    markup = kb([[wallet_btn], [("← Назад", "back_menu")]])
    await bot.send_message(chat_id=chat_id, text=text, parse_mode="HTML",
                           disable_web_page_preview=True, reply_markup=markup)

# ========== HANDLERS ==========
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    bot = ctx.bot
    if not _approved and SUPABASE_URL:
        for row in await sb_get("members", "select=user_id"):
            _approved.add(row["user_id"])
    if uid in _approved:
        await send_menu(bot, update.effective_chat.id)
    else:
        await send_captcha(bot, update.effective_chat.id, uid)

async def button_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query   = update.callback_query
    uid     = query.from_user.id
    data    = query.data
    bot     = ctx.bot
    chat_id = query.message.chat_id if query.message else uid

    try:
        await query.answer()
    except Exception:
        pass

    # КАПЧА
    if data.startswith("cap|"):
        chosen = data[4:]
        st  = _state.get(uid, {})
        cap = CAPTCHAS[st.get("captcha_idx", 0)]
        if chosen != cap["correct"]:
            try:
                await query.edit_message_text("❌ Неверно! Попробуйте снова.", parse_mode="HTML")
            except Exception:
                pass
            await asyncio.sleep(1)
            await send_captcha(bot, chat_id, uid)
            return
        _state[uid] = {"step": "q1", "answers": []}
        try:
            await query.edit_message_text(
                "✅ Верно!\n\n<b>Вопрос 1 из 3</b>\nЕсть ли у вас опыт в офферах?",
                parse_mode="HTML")
        except Exception:
            pass
        return

    # ПРОФИЛЬ
    if data == "profile":
        uname = query.from_user.username or str(uid)
        await show_profile(bot, chat_id, uid, username=uname)
        return

    # НАЗАД
    if data == "back_menu":
        try:
            await query.message.delete()
        except Exception:
            pass
        await send_menu(bot, chat_id)
        return

    # КОШЕЛЁК
    if data == "set_wallet":
        _state[uid] = {"step": "wait_wallet"}
        await bot.send_message(chat_id=chat_id, text="💳 Введите адрес вашего TON кошелька:",
                               parse_mode="HTML")
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
            "💰 <b>Заявка на выплату</b>\n\n"
            + (f"Кошелёк: <code>{wallet}</code>\n\n" if wallet else "⚠️ Кошелёк не указан — укажите в профиле\n\n")
            + f"Прикрепите фото подтверждения передачи подарка на @{RELAY_USER}:"
        )
        await bot.send_message(chat_id=chat_id, text=caption, parse_mode="HTML")
        return

    # ADMIN: принять заявку
    if data.startswith("approve|"):
        applicant_id = int(data.split("|")[1])
        uname = ""
        if query.message and query.message.text:
            m2 = re.search(r"@(\w+)", query.message.text)
            if m2:
                uname = m2.group(1)
        if SUPABASE_URL:
            await sb_upsert("members", {
                "user_id": applicant_id, "username": uname,
                "joined_at": datetime.utcnow().isoformat(), "earned_gram": 0,
            })
        _approved.add(applicant_id)
        try:
            await query.edit_message_text(
                (query.message.text or "") + "\n\n✅ <b>Заявка принята</b>", parse_mode="HTML")
        except Exception:
            pass
        await bot.send_message(
            chat_id=applicant_id,
            text="✅ <b>Заявка принята!</b>\n\nДобро пожаловать в команду!\n\n🎁 Вступите в нашу группу:",
            parse_mode="HTML",
            disable_web_page_preview=True,
            reply_markup=kb([[("📢 Вступить в группу", GROUP_LINK)]]),
        )
        await asyncio.sleep(0.5)
        await send_menu(bot, applicant_id)
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
            try:
                new_val = current + float(amount)
            except Exception:
                new_val = current
            await sb_patch("members", f"user_id=eq.{payer_id}", {"earned_gram": new_val})

        try:
            await query.edit_message_caption(
                (query.message.caption or "") + "\n\n✅ <b>Выплата одобрена</b>", parse_mode="HTML")
        except Exception:
            try:
                await query.edit_message_text(
                    (query.message.text or "") + "\n\n✅ <b>Выплата одобрена</b>", parse_mode="HTML")
            except Exception:
                pass

        profit_text = (
            f"💎 <b>Новый профит!</b>\n"
            f"┠ 💰 Сумма: <b>{amount} gram</b>\n"
            f"┠ 👤 Исполнитель: @{username} (<code>{payer_id}</code>)\n"
            f"┠ 💳 Кошелёк: <code>{wallet}</code>\n"
            f"┖ 🎁 Подарок: {gift_link}\n\n"
            f"✨ Отличная работа! Продолжай в том же духе."
        )
        await send_photo(bot, PROFIT_CHAT, PHOTO_PROFIT, profit_text, thread_id=PROFIT_THREAD)
        return

async def msg_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    uid  = update.effective_user.id
    text = update.message.text or ""
    bot  = ctx.bot
    st   = _state.get(uid, {})
    step = st.get("step", "")

    if step == "wait_wallet":
        wallet = text.strip()
        ok = await sb_patch("members", f"user_id=eq.{uid}", {"wallet": wallet})
        _state.pop(uid, None)
        msg = f"✅ Кошелёк сохранён:\n<code>{wallet}</code>" if ok else "❌ Ошибка, попробуйте позже."
        await update.message.reply_text(msg, parse_mode="HTML")
        return

    if step == "q1":
        st["answers"].append(text)
        st["step"] = "q2"
        await update.message.reply_text("<b>Вопрос 2 из 3</b>\nСколько времени готовы уделять?", parse_mode="HTML")
        return
    if step == "q2":
        st["answers"].append(text)
        st["step"] = "q3"
        await update.message.reply_text("<b>Вопрос 3 из 3</b>\nОткуда узнали о нас?", parse_mode="HTML")
        return
    if step == "q3":
        st["answers"].append(text)
        st["step"] = "done"
        user  = update.effective_user
        uname = f"@{user.username}" if user.username else user.first_name
        now   = datetime.now().strftime("%d.%m.%Y %H:%M")
        a     = st["answers"]
        await update.message.reply_text("✅ Заявка отправлена! Ожидайте ответа.", parse_mode="HTML")
        await bot.send_message(
            chat_id=ADMIN_ID,
            text=(
                f"❗️ <b>Новая заявка</b>\n\n"
                f"👤 {uname} (<code>{uid}</code>)\n"
                f"🕐 {now}\n\n"
                f"<b>Опыт:</b> {a[0]}\n"
                f"<b>Время:</b> {a[1]}\n"
                f"<b>Откуда:</b> {a[2]}"
            ),
            parse_mode="HTML",
            disable_web_page_preview=True,
            reply_markup=kb([[("✅ Принять заявку", f"approve|{uid}")]]),
        )
        return

    if step == "payout_wait_amount":
        parts     = text.split(maxsplit=1)
        amount    = parts[0] if parts else "—"
        gift_link = parts[1] if len(parts) > 1 else "—"
        p = _payout_pending.get(uid, {})
        p.update({"amount": amount, "gift_link": gift_link})
        _payout_pending[uid] = p
        _state.pop(uid, None)
        wallet = p.get("wallet") or "не указан"
        await update.message.reply_text("✅ Заявка на выплату отправлена!", parse_mode="HTML")
        pay_text = (
            f"💰 <b>Заявка на выплату</b>\n\n"
            f"👤 @{p.get('username','—')} (<code>{uid}</code>)\n"
            f"🕐 {datetime.now().strftime('%d.%m.%Y %H:%M')}\n"
            f"💰 Сумма: <b>{amount} gram</b>\n"
            f"💳 Кошелёк: <code>{wallet}</code>\n"
            f"🎁 Подарок: {gift_link}"
        )
        markup = kb([[("✅ Принять выплату", f"pay_approve|{uid}|{gift_link}")]])
        await send_photo(bot, ADMIN_ID, PHOTO2_PATH, pay_text, markup)
        return

async def photo_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    uid = update.effective_user.id
    st  = _state.get(uid, {})
    if st.get("step") != "payout_wait_photo":
        return
    file_id = update.message.photo[-1].file_id
    p = _payout_pending.setdefault(uid, {})
    p["photo"] = file_id
    p.setdefault("username", update.effective_user.username or str(uid))
    wallet = p.get("wallet")
    _state[uid] = {"step": "payout_wait_amount"}
    if wallet:
        await update.message.reply_text(
            f"💳 Кошелёк: <code>{wallet}</code>\n\n"
            "Введите сумму и ссылку на подарок через пробел:\n"
            "<i>Пример: 5.00 https://t.me/nft/...</i>",
            parse_mode="HTML",
        )
    else:
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
    log.info("bot2 started (polling)")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
