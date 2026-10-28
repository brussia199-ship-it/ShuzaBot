# ═══════════════════════════════════════════════════════════
#  RubUP — Telegram Casino Bot (dice + coinflip)
#  Один файл. Запуск: python RubUP.py
#  Переменные окружения: BOT_TOKEN, ADMIN_IDS (через запятую)
# ═══════════════════════════════════════════════════════════

import asyncio
import logging
import os
import random

import aiosqlite
from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import TelegramAPIServer
from aiogram.filters import Command
from aiogram.types import (
    Message,
    CallbackQuery,
    LabeledPrice,
    PreCheckoutQuery,
    InlineKeyboardMarkup,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

# ─── КОНФИГ ────────────────────────────────────────────────
BOT_TOKEN = os.getenv("BOT_TOKEN", "1780243489:onREfB__lmAU_28s4FXe4hSwEh_bORaCzSJ")
API_BASE = "https://api.shuzagram.com"
ADMIN_IDS = [int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()]
ADMIN_LINK = "http://sgq.me/RubUPer"
ADMIN_USERNAME = "RubUPer"

DB_PATH = "rubup.db"
MIN_BET = 1
MIN_WITHDRAW = 50

DICE_PAYOUT_EXACT = 5
DICE_PAYOUT_PARITY = 1.9
COIN_PAYOUT = 1.9

PRESET_BETS = [10, 50, 100, 500]
PRESET_TOPUP = [50, 100, 250, 500, 1000]

DICE_FACE = {1: "⚀", 2: "⚁", 3: "⚂", 4: "⚃", 5: "⚄", 6: "⚅"}

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("RubUP")

# ─── БД ────────────────────────────────────────────────────
async def db_init():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id    INTEGER PRIMARY KEY,
                username   TEXT,
                balance    INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )""")
        await db.execute("""
            CREATE TABLE IF NOT EXISTS withdrawals (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id    INTEGER,
                amount     INTEGER,
                status     TEXT DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )""")
        await db.commit()


async def ensure_user(uid: int, username: str | None):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO users (user_id, username) VALUES (?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET username=excluded.username",
            (uid, username),
        )
        await db.commit()


async def get_balance(uid: int) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT balance FROM users WHERE user_id=?", (uid,)) as cur:
            row = await cur.fetchone()
            return row[0] if row else 0


async def add_balance(uid: int, amount: int) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO users (user_id, balance) VALUES (?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET balance = balance + excluded.balance",
            (uid, amount),
        )
        await db.commit()
        async with db.execute("SELECT balance FROM users WHERE user_id=?", (uid,)) as cur:
            return (await cur.fetchone())[0]


async def create_withdrawal(uid: int, amount: int) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "INSERT INTO withdrawals (user_id, amount) VALUES (?, ?)", (uid, amount)
        )
        await db.commit()
        return cur.lastrowid


async def get_withdrawal(req_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT user_id, amount, status FROM withdrawals WHERE id=?", (req_id,)
        ) as cur:
            return await cur.fetchone()


async def set_wd_status(req_id: int, status: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE withdrawals SET status=? WHERE id=?", (status, req_id))
        await db.commit()


# ─── КЛАВИАТУРЫ ────────────────────────────────────────────
def kb(*buttons, adjust=None) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for text, data in buttons:
        b.button(text=text, callback_data=data)
    if adjust:
        b.adjust(*adjust)
    return b.as_markup()


def main_menu_kb():
    return kb(
        ("🎮 Играть", "games"),
        ("💳 Пополнить", "topup"),
        ("💸 Вывести", "withdraw"),
        ("👤 Профиль", "profile"),
        adjust=(2, 2),
    )


# ─── РОУТЕР ────────────────────────────────────────────────
router = Router()


@router.message(Command("start"))
async def cmd_start(msg: Message):
    await ensure_user(msg.from_user.id, msg.from_user.username)
    bal = await get_balance(msg.from_user.id)
    await msg.answer(
        f"👋 Добро пожаловать в <b>RubUP</b>!\n\n"
        f"Ваш баланс: <b>{bal} ⭐</b>\n\n"
        f"🎲 Кубик · 🪙 Монетка\n"
        f"Пополнение через Telegram Stars.",
        reply_markup=main_menu_kb(),
    )


@router.callback_query(F.data == "menu")
async def cb_menu(call: CallbackQuery):
    bal = await get_balance(call.from_user.id)
    await call.message.edit_text(
        f"🏠 <b>Главное меню</b>\n\nБаланс: <b>{bal} ⭐</b>",
        reply_markup=main_menu_kb(),
    )
    await call.answer()


# ─── ПРОФИЛЬ ───────────────────────────────────────────────
@router.callback_query(F.data == "profile")
async def cb_profile(call: CallbackQuery):
    bal = await get_balance(call.from_user.id)
    await call.message.edit_text(
        f"👤 <b>Профиль</b>\n\n"
        f"ID: <code>{call.from_user.id}</code>\n"
        f"Имя: {call.from_user.full_name}\n"
        f"Баланс: <b>{bal} ⭐</b>",
        reply_markup=kb(("⬅️ Назад", "menu")),
    )
    await call.answer()


# ─── ПОПОЛНЕНИЕ ────────────────────────────────────────────
@router.callback_query(F.data == "topup")
async def cb_topup(call: CallbackQuery):
    buttons = [(f"{s} ⭐", f"topup_{s}") for s in PRESET_TOPUP]
    buttons.append(("⬅️ Назад", "menu"))
    await call.message.edit_text(
        "💳 <b>Пополнение баланса</b>\n\n"
        "Оплата через Telegram Stars.\n"
        "1 звезда = 1 ⭐ на балансе.\n\n"
        "Выберите сумму:",
        reply_markup=kb(*buttons, adjust=(3, 2, 1)),
    )
    await call.answer()


@router.callback_query(F.data.startswith("topup_"))
async def cb_topup_amount(call: CallbackQuery):
    stars = int(call.data.split("_")[1])
    await call.message.answer_invoice(
        title=f"Пополнение на {stars} ⭐",
        description=f"Зачисление {stars} звёзд на баланс RubUP",
        payload=f"topup:{call.from_user.id}:{stars}",
        currency="XTR",
        prices=[LabeledPrice(label=f"{stars} ⭐", amount=stars)],
        provider_token="",
    )
    await call.answer()


@router.pre_checkout_query()
async def on_pre_checkout(q: PreCheckoutQuery):
    await q.answer(ok=True)


@router.message(F.successful_payment)
async def on_paid(msg: Message):
    p = msg.successful_payment.invoice_payload.split(":")
    if p[0] == "topup" and len(p) == 3:
        uid, stars = int(p[1]), int(p[2])
        new_bal = await add_balance(uid, stars)
        await msg.answer(
            f"✅ Пополнено на <b>{stars} ⭐</b>\nБаланс: <b>{new_bal} ⭐</b>",
            reply_markup=main_menu_kb(),
        )


# ─── ВЫВОД ─────────────────────────────────────────────────
@router.callback_query(F.data == "withdraw")
async def cb_withdraw(call: CallbackQuery):
    bal = await get_balance(call.from_user.id)
    if bal < MIN_WITHDRAW:
        await call.answer(f"Минимум для вывода: {MIN_WITHDRAW} ⭐", show_alert=True)
        return
    opts = [a for a in (50, 100, 250, 500) if a <= bal]
    buttons = [(f"{a} ⭐", f"wd_{a}") for a in opts]
    buttons.append((f"Всё ({bal} ⭐)", f"wd_{bal}"))
    buttons.append(("⬅️ Назад", "menu"))
    await call.message.edit_text(
        f"💸 <b>Вывод средств</b>\n\n"
        f"Баланс: {bal} ⭐\nМинимум: {MIN_WITHDRAW} ⭐\n\n"
        f"Заявка уйдёт администратору.",
        reply_markup=kb(*buttons, adjust=(3, 1, 1, 1)),
    )
    await call.answer()


@router.callback_query(F.data.startswith("wd_"))
async def cb_withdraw_confirm(call: CallbackQuery):
    amount = int(call.data.split("_")[1])
    bal = await get_balance(call.from_user.id)
    if amount < MIN_WITHDRAW or amount > bal:
        await call.answer("Некорректная сумма", show_alert=True)
        return
    new_bal = await add_balance(call.from_user.id, -amount)
    req_id = await create_withdrawal(call.from_user.id, amount)

    admin_kb = kb(
        ("✅ Одобрить", f"wapprove_{req_id}"),
        ("❌ Отклонить", f"wreject_{req_id}"),
        adjust=(2,),
    )
    sent_any = False
    for aid in ADMIN_IDS:
        try:
            await call.bot.send_message(
                aid,
                f"💸 <b>Заявка на вывод #{req_id}</b>\n\n"
                f"Пользователь: <a href='tg://user?id={call.from_user.id}'>"
                f"{call.from_user.full_name}</a>\n"
                f"ID: <code>{call.from_user.id}</code>\n"
                f"Username: @{call.from_user.username or '—'}\n"
                f"Сумма: <b>{amount} ⭐</b>",
                reply_markup=admin_kb,
            )
            sent_any = True
        except Exception as e:
            log.warning("admin send fail %s: %s", aid, e)

    tail = (
        "Администратор обработает заявку в ближайшее время."
        if sent_any else
        f"Свяжитесь с админом: {ADMIN_LINK}"
    )
    await call.message.edit_text(
        f"✅ Заявка <b>#{req_id}</b> на {amount} ⭐ создана.\n"
        f"Баланс: {new_bal} ⭐\n\n{tail}",
        reply_markup=main_menu_kb(),
    )
    await call.answer()


@router.callback_query(F.data.startswith("wapprove_"))
async def admin_approve(call: CallbackQuery):
    if call.from_user.id not in ADMIN_IDS:
        await call.answer("Нет прав", show_alert=True)
        return
    rid = int(call.data.split("_")[1])
    row = await get_withdrawal(rid)
    if not row or row[2] != "pending":
        await call.answer("Уже обработана", show_alert=True)
        return
    uid, amount, _ = row
    await set_wd_status(rid, "approved")
    try:
        await call.bot.send_message(
            uid,
            f"✅ Заявка #{rid} одобрена.\n{amount} ⭐ будут выплачены.\n"
            f"Связь: {ADMIN_LINK}",
        )
    except Exception:
        pass
    await call.message.edit_text(f"Заявка #{rid} ✅ одобрена ({amount} ⭐)")


@router.callback_query(F.data.startswith("wreject_"))
async def admin_reject(call: CallbackQuery):
    if call.from_user.id not in ADMIN_IDS:
        await call.answer("Нет прав", show_alert=True)
        return
    rid = int(call.data.split("_")[1])
    row = await get_withdrawal(rid)
    if not row or row[2] != "pending":
        await call.answer("Уже обработана", show_alert=True)
        return
    uid, amount, _ = row
    await add_balance(uid, amount)
    await set_wd_status(rid, "rejected")
    try:
        await call.bot.send_message(
            uid,
            f"❌ Заявка #{rid} отклонена.\n{amount} ⭐ возвращены на баланс.",
        )
    except Exception:
        pass
    await call.message.edit_text(f"Заявка #{rid} ❌ отклонена (возврат {amount} ⭐)")


# ─── ИГРЫ ──────────────────────────────────────────────────
@router.callback_query(F.data == "games")
async def cb_games(call: CallbackQuery):
    await call.message.edit_text(
        "🎮 <b>Выберите игру</b>\n\n"
        f"🎲 <b>Кубик</b> — число ×{DICE_PAYOUT_EXACT} / чёт-нечет ×{DICE_PAYOUT_PARITY}\n"
        f"🪙 <b>Монетка</b> — ×{COIN_PAYOUT}",
        reply_markup=kb(
            ("🎲 Кубик", "game_dice"),
            ("🪙 Монетка", "game_coin"),
            ("⬅️ Назад", "menu"),
            adjust=(2, 1),
        ),
    )
    await call.answer()


# ── КУБИК ──
@router.callback_query(F.data == "game_dice")
async def dice_bet(call: CallbackQuery):
    buttons = [(f"{a} ⭐", f"dice_b_{a}") for a in PRESET_BETS]
    buttons.append(("⬅️ Назад", "games"))
    await call.message.edit_text(
        "🎲 <b>Кубик</b>\n\n"
        f"• на число → ×{DICE_PAYOUT_EXACT}\n"
        f"• чёт / нечет → ×{DICE_PAYOUT_PARITY}\n\n"
        "Выберите ставку:",
        reply_markup=kb(*buttons, adjust=(2, 2, 1)),
    )
    await call.answer()


@router.callback_query(F.data.startswith("dice_b_"))
async def dice_pick(call: CallbackQuery):
    bet = int(call.data.split("_")[2])
    bal = await get_balance(call.from_user.id)
    if bet > bal:
        await call.answer(f"Недостаточно. Баланс: {bal} ⭐", show_alert=True)
        return
    buttons = [(f"{DICE_FACE[n]} {n}", f"dice_p_n_{n}_{bet}") for n in range(1, 7)]
    buttons += [
        (f"Чёт ×{DICE_PAYOUT_PARITY}", f"dice_p_e_{bet}"),
        (f"Нечет ×{DICE_PAYOUT_PARITY}", f"dice_p_o_{bet}"),
        ("⬅️ Назад", "game_dice"),
    ]
    await call.message.edit_text(
        f"🎲 <b>Кубик</b>\nСтавка: <b>{bet} ⭐</b>\n\nНа что ставите?",
        reply_markup=kb(*buttons, adjust=(3, 3, 1, 1, 1)),
    )
    await call.answer()


@router.callback_query(F.data.startswith("dice_p_"))
async def dice_play(call: CallbackQuery):
    p = call.data.split("_")  # dice_p_{n|e|o}_...
    mode = p[2]
    if mode == "n":
        num, bet = int(p[3]), int(p[4])
        choice = f"число {num}"
    else:
        num, bet = None, int(p[3])
        choice = "чёт" if mode == "e" else "нечет"

    bal = await get_balance(call.from_user.id)
    if bet > bal:
        await call.answer("Недостаточно средств", show_alert=True)
        return

    await add_balance(call.from_user.id, -bet)
    roll = random.randint(1, 6)

    win = 0
    if mode == "n" and roll == num:
        win = int(bet * DICE_PAYOUT_EXACT)
    elif mode == "e" and roll % 2 == 0:
        win = int(bet * DICE_PAYOUT_PARITY)
    elif mode == "o" and roll % 2 == 1:
        win = int(bet * DICE_PAYOUT_PARITY)

    if win:
        new_bal = await add_balance(call.from_user.id, win)
        result = f"🎉 <b>Выигрыш +{win} ⭐</b>"
    else:
        new_bal = await get_balance(call.from_user.id)
        result = f"😢 <b>Проигрыш -{bet} ⭐</b>"

    await call.message.edit_text(
        f"🎲 Выпало: <b>{DICE_FACE[roll]} {roll}</b>\n"
        f"Ваша ставка: {choice} ({bet} ⭐)\n\n"
        f"{result}\nБаланс: <b>{new_bal} ⭐</b>",
        reply_markup=kb(
            ("🔄 Ещё", "game_dice"),
            ("🏠 Меню", "menu"),
            adjust=(2,),
        ),
    )
    await call.answer()


# ── МОНЕТКА ──
@router.callback_query(F.data == "game_coin")
async def coin_bet(call: CallbackQuery):
    buttons = [(f"{a} ⭐", f"coin_b_{a}") for a in PRESET_BETS]
    buttons.append(("⬅️ Назад", "games"))
    await call.message.edit_text(
        f"🪙 <b>Монетка</b> — выигрыш ×{COIN_PAYOUT}\n\nВыберите ставку:",
        reply_markup=kb(*buttons, adjust=(2, 2, 1)),
    )
    await call.answer()


@router.callback_query(F.data.startswith("coin_b_"))
async def coin_pick(call: CallbackQuery):
    bet = int(call.data.split("_")[2])
    bal = await get_balance(call.from_user.id)
    if bet > bal:
        await call.answer(f"Недостаточно. Баланс: {bal} ⭐", show_alert=True)
        return
    await call.message.edit_text(
        f"🪙 <b>Монетка</b>\nСтавка: <b>{bet} ⭐</b>\n\nОрёл или решка?",
        reply_markup=kb(
            ("🦅 Орёл", f"coin_p_h_{bet}"),
            ("🌰 Решка", f"coin_p_t_{bet}"),
            ("⬅️ Назад", "game_coin"),
            adjust=(2, 1),
        ),
    )
    await call.answer()


@router.callback_query(F.data.startswith("coin_p_"))
async def coin_play(call: CallbackQuery):
    _, _, side, bet_s = call.data.split("_")
    bet = int(bet_s)
    bal = await get_balance(call.from_user.id)
    if bet > bal:
        await call.answer("Недостаточно средств", show_alert=True)
        return

    await add_balance(call.from_user.id, -bet)
    result_side = random.choice(["h", "t"])
    win = result_side == side

    emoji = "🦅 Орёл" if result_side == "h" else "🌰 Решка"
    if win:
        payout = int(bet * COIN_PAYOUT)
        new_bal = await add_balance(call.from_user.id, payout)
        text_res = f"🎉 <b>Победа! +{payout} ⭐</b>"
    else:
        new_bal = await get_balance(call.from_user.id)
        text_res = f"😢 <b>Проигрыш -{bet} ⭐</b>"

    await call.message.edit_text(
        f"🪙 Выпало: <b>{emoji}</b>\n\n{text_res}\nБаланс: <b>{new_bal} ⭐</b>",
        reply_markup=kb(
            ("🔄 Ещё", "game_coin"),
            ("🏠 Меню", "menu"),
            adjust=(2,),
        ),
    )
    await call.answer()


# ─── ЗАПУСК ────────────────────────────────────────────────
async def main():
    await db_init()

    session = AiohttpSession(api=TelegramAPIServer.from_base(API_BASE))
    bot = Bot(token=BOT_TOKEN, session=session)
    dp = Dispatcher()
    dp.include_router(router)

    me = await bot.get_me()
    log.info("Started as @%s", me.username)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
