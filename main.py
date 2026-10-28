# ═══════════════════════════════════════════════════════════
#  RubUP — Casino Bot for ShuzaGram (All-in-One)
#  Запуск: python RubUP.py
# ═══════════════════════════════════════════════════════════

import asyncio
import logging
import os
import random
import string
from datetime import datetime, timedelta

import aiosqlite
from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import TelegramAPIServer
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, BotCommand
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

# ─── КОНФИГ ────────────────────────────────────────────────
BOT_TOKEN = os.getenv("BOT_TOKEN", "1780243489:onREfB__lmAU_28s4FXe4hSwEh_bORaCzSJ")
API_BASE = "https://api.shuzagram.com"

ADMIN_ID = 1780243488
ADMIN_USERNAME = "RubUPer"
ADMIN_LINK = "http://sgq.me/RubUPer"

DB_PATH = "rubup.db"
MIN_BET = 1
MIN_WITHDRAW = 50

DICE_FACE = {1: "⚀", 2: "⚁", 3: "⚂", 4: "⚃", 5: "⚄", 6: "⚅"}
PRESET_BETS = [10, 50, 100, 500]
PRESET_TOPUP = [50, 100, 250, 500, 1000]

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("RubUP")

# ─── БАЗА ДАННЫХ ───────────────────────────────────────────
async def db_init():
    async with aiosqlite.connect(DB_PATH) as db:
        # Пользователи
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                balance INTEGER DEFAULT 0,
                total_wagered INTEGER DEFAULT 0,
                reg_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )""")
        # Настройки (шанс выигрыша и т.д.)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )""")
        # Заявки на вывод
        await db.execute("""
            CREATE TABLE IF NOT EXISTS withdrawals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                amount INTEGER,
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )""")
        # Заявки на пополнение (коды)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS topups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                amount INTEGER,
                code TEXT UNIQUE,
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )""")
        # Чеки (промокоды)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS checks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                creator_id INTEGER,
                amount INTEGER,
                code TEXT UNIQUE,
                is_activated INTEGER DEFAULT 0,
                activated_by INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )""")
        
        # Дефолтные настройки
        await db.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('win_rate', '45')")
        await db.commit()

async def get_setting(key: str, default: str = "0") -> str:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT value FROM settings WHERE key=?", (key,)) as cur:
            row = await cur.fetchone()
            return row[0] if row else default

async def set_setting(key: str, value: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))
        await db.commit()

async def ensure_user(uid: int, username: str | None):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO users (user_id, username) VALUES (?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET username=excluded.username",
            (uid, username or "None"),
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

async def add_wagered(uid: int, amount: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET total_wagered = total_wagered + ? WHERE user_id=?", (amount, uid))
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
        ("🎁 Чеки", "checks_menu"),
        ("👤 Профиль", "profile"),
        adjust=(2, 2, 1),
    )

def admin_menu_kb():
    return kb(
        ("📊 Статистика", "adm_stats"),
        ("🎲 Шанс выигрыша", "adm_chance"),
        ("📣 Рассылка", "adm_broadcast"),
        ("📥 Пополнения", "adm_topups"),
        ("📤 Выводы", "adm_withdrawals"),
        ("⬅️ В меню", "menu"),
        adjust=(2, 2, 2),
    )

# ─── СОСТОЯНИЯ ─────────────────────────────────────────────
class AdminStates(StatesGroup):
    broadcast_msg = State()
    set_chance = State()

class UserStates(StatesGroup):
    activate_check = State()

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
        f"🎁 Создавайте и активируйте чеки!",
        reply_markup=main_menu_kb(),
    )

@router.message(Command("admin"))
async def cmd_admin(msg: Message):
    if msg.from_user.id != ADMIN_ID:
        return
    await msg.answer("🛠 <b>Админ-панель</b>\nВыберите действие:", reply_markup=admin_menu_kb())

@router.callback_query(F.data == "menu")
async def cb_menu(call: CallbackQuery):
    bal = await get_balance(call.from_user.id)
    await call.message.edit_text(
        f"🏠 <b>Главное меню</b>\n\nБаланс: <b>{bal} ⭐</b>",
        reply_markup=main_menu_kb(),
    )
    await call.answer()

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

# ═══════════════ ПОПОЛНЕНИЕ (ВРУЧНУЮ) ═══════════════
@router.callback_query(F.data == "topup")
async def cb_topup(call: CallbackQuery):
    buttons = [(f"{s} ⭐", f"topup_{s}") for s in PRESET_TOPUP]
    buttons.append(("⬅️ Назад", "menu"))
    await call.message.edit_text(
        "💳 <b>Пополнение баланса</b>\n\n"
        f"Для пополнения переведите звёзды админу: @{ADMIN_USERNAME}\n"
        "Нажмите на сумму ниже, чтобы получить уникальный код для оплаты.\n\n"
        "Выберите сумму:",
        reply_markup=kb(*buttons, adjust=(3, 2, 1)),
    )
    await call.answer()

@router.callback_query(F.data.startswith("topup_"))
async def cb_topup_amount(call: CallbackQuery):
    amount = int(call.data.split("_")[1])
    code = "TOP" + "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
    
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO topups (user_id, amount, code) VALUES (?, ?, ?)",
            (call.from_user.id, amount, code)
        )
        await db.commit()

    await call.message.edit_text(
        f"🧾 <b>Заявка создана</b>\n\n"
        f"Сумма: <b>{amount} ⭐</b>\n"
        f"Ваш код: <code>{code}</code>\n\n"
        f"1. Переведите {amount} звёзд админу: @{ADMIN_USERNAME}\n"
        f"2. Отправьте админу ваш код: <code>{code}</code>\n"
        f"3. После проверки админ начислит баланс.",
        reply_markup=kb(("⬅️ Назад", "menu")),
    )

    # Уведомление админу
    admin_kb = kb(
        ("✅ Подтвердить", f"adm_topup_ok_{code}"),
        ("❌ Отклонить", f"adm_topup_no_{code}"),
        adjust=(2,)
    )
    await call.bot.send_message(
        ADMIN_ID,
        f"📥 <b>Новая заявка на пополнение</b>\n\n"
        f"Пользователь: <a href='tg://user?id={call.from_user.id}'>{call.from_user.full_name}</a>\n"
        f"ID: <code>{call.from_user.id}</code>\n"
        f"Сумма: <b>{amount} ⭐</b>\n"
        f"Код: <code>{code}</code>",
        reply_markup=admin_kb
    )
    await call.answer()

# ═══════════════ ВЫВОД ═══════════════
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
        f"💸 <b>Вывод средств</b>\n\nБаланс: {bal} ⭐\nМинимум: {MIN_WITHDRAW} ⭐",
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
    
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("INSERT INTO withdrawals (user_id, amount) VALUES (?, ?)", (call.from_user.id, amount))
        req_id = cur.lastrowid
        await db.commit()

    admin_kb = kb(("✅ Одобрить", f"adm_wd_ok_{req_id}"), ("❌ Отклонить", f"adm_wd_no_{req_id}"), adjust=(2,))
    await call.bot.send_message(
        ADMIN_ID,
        f"💸 <b>Заявка на вывод #{req_id}</b>\n\n"
        f"Пользователь: <a href='tg://user?id={call.from_user.id}'>{call.from_user.full_name}</a>\n"
        f"Username: @{call.from_user.username or '—'}\n"
        f"Сумма: <b>{amount} ⭐</b>",
        reply_markup=admin_kb,
    )
    await call.message.edit_text(
        f"✅ Заявка <b>#{req_id}</b> на {amount} ⭐ создана.\n"
        f"Баланс: {new_bal} ⭐\n\nОжидайте подтверждения.",
        reply_markup=main_menu_kb(),
    )
    await call.answer()

# ═══════════════ ЧЕКИ (ПРОМОКОДЫ) ═══════════════
@router.callback_query(F.data == "checks_menu")
async def cb_checks(call: CallbackQuery):
    await call.message.edit_text(
        "🎁 <b>Чеки на звёзды</b>\n\n"
        "Вы можете создать чек на определённую сумму и отправить код другу.\n"
        "Срок действия чека: 24 часа.",
        reply_markup=kb(
            ("➕ Создать чек", "check_create"),
            ("✅ Активировать чек", "check_activate"),
            ("⬅️ Назад", "menu"),
            adjust=(1, 1, 1)
        ),
    )
    await call.answer()

@router.callback_query(F.data == "check_create")
async def cb_check_create(call: CallbackQuery):
    bal = await get_balance(call.from_user.id)
    buttons = [(f"{a} ⭐", f"check_c_{a}") for a in PRESET_BETS if a <= bal]
    buttons.append(("⬅️ Назад", "checks_menu"))
    if len(buttons) == 1:
        await call.answer("Недостаточно средств для создания чека (мин. 10 ⭐)", show_alert=True)
        return
    await call.message.edit_text(
        f"Выберите сумму чека (ваш баланс: {bal} ⭐):",
        reply_markup=kb(*buttons, adjust=(2, 2, 1))
    )
    await call.answer()

@router.callback_query(F.data.startswith("check_c_"))
async def cb_check_create_amount(call: CallbackQuery):
    amount = int(call.data.split("_")[2])
    bal = await get_balance(call.from_user.id)
    if bal < amount:
        await call.answer("Недостаточно средств", show_alert=True)
        return

    await add_balance(call.from_user.id, -amount)
    code = "CHK" + "".join(random.choices(string.ascii_uppercase + string.digits, k=8))
    
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT INTO checks (creator_id, amount, code) VALUES (?, ?, ?)", (call.from_user.id, amount, code))
        await db.commit()

    await call.message.edit_text(
        f"✅ <b>Чек создан на {amount} ⭐</b>\n\n"
        f"Код: <code>{code}</code>\n"
        f"Перешлите этот код получателю. Он введёт его в разделе «Активировать чек».\n"
        f"⏳ Действителен 24 часа.",
        reply_markup=kb(("⬅️ Назад", "checks_menu")),
    )
    await call.answer()

@router.callback_query(F.data == "check_activate")
async def cb_check_activate(call: CallbackQuery, state: FSMContext):
    await state.set_state(UserStates.activate_check)
    await call.message.edit_text(
        "Введите код чека (например, CHK12345678):",
        reply_markup=kb(("⬅️ Отмена", "checks_menu"))
    )
    await call.answer()

@router.message(UserStates.activate_check)
async def process_check_activate(msg: Message, state: FSMContext):
    code = msg.text.strip().upper()
    await state.clear()

    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT id, amount, is_activated, created_at FROM checks WHERE code=?", (code,)) as cur:
            row = await cur.fetchone()
    
    if not row:
        await msg.answer("❌ Чек не найден или неверный код.", reply_markup=main_menu_kb())
        return
    
    chk_id, amount, is_act, created_at = row
    if is_act:
        await msg.answer("❌ Этот чек уже был активирован.", reply_markup=main_menu_kb())
        return

    # Проверка времени (24 часа)
    created_dt = datetime.strptime(created_at, "%Y-%m-%d %H:%M:%S")
    if datetime.now() - created_dt > timedelta(hours=24):
        await msg.answer("❌ Срок действия чека истёк.", reply_markup=main_menu_kb())
        return

    # Активация
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE checks SET is_activated=1, activated_by=? WHERE id=?", (msg.from_user.id, chk_id))
        await db.commit()
    
    new_bal = await add_balance(msg.from_user.id, amount)
    await msg.answer(
        f"🎉 <b>Чек активирован!</b>\nВы получили <b>{amount} ⭐</b>\nБаланс: {new_bal} ⭐",
        reply_markup=main_menu_kb()
    )

# ═══════════════ ИГРЫ ═══════════════
@router.callback_query(F.data == "games")
async def cb_games(call: CallbackQuery):
    await call.message.edit_text(
        "🎮 <b>Выберите игру</b>\n\n",
        reply_markup=kb(
            ("🎲 Кубик", "game_dice"),
            ("🪙 Монетка", "game_coin"),
            ("⬅️ Назад", "menu"),
            adjust=(2, 1),
        ),
    )
    await call.answer()

# ── ЛОГИКА ПОДКРУТКИ ──
async def get_win_chance() -> int:
    return int(await get_setting("win_rate", "45"))

def rigged_coin(user_choice: str) -> str:
    """Возвращает выигрышную или проигрышную сторону в зависимости от шанса"""
    chance = asyncio.run(get_win_chance()) # В реальном проекте лучше await, но для простоты так
    win = random.randint(1, 100) <= chance
    if win:
        return user_choice
    else:
        return "t" if user_choice == "h" else "h"

async def rigged_dice(mode: str, num: int | None) -> int:
    chance = await get_win_chance()
    win = random.randint(1, 100) <= chance
    
    if mode == "n":
        if win: return num
        else: return random.choice([n for n in range(1, 7) if n != num])
    elif mode == "e":
        if win: return random.choice([2, 4, 6])
        else: return random.choice([1, 3, 5])
    elif mode == "o":
        if win: return random.choice([1, 3, 5])
        else: return random.choice([2, 4, 6])
    return random.randint(1, 6)

# ── КУБИК ──
@router.callback_query(F.data == "game_dice")
async def dice_bet(call: CallbackQuery):
    buttons = [(f"{a} ⭐", f"dice_b_{a}") for a in PRESET_BETS]
    buttons.append(("⬅️ Назад", "games"))
    await call.message.edit_text(
        "🎲 <b>Кубик</b>\n\nНа число ×5, на чёт/нечет ×1.9\nВыберите ставку:",
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
        ("Чёт ×1.9", f"dice_p_e_{bet}"),
        ("Нечет ×1.9", f"dice_p_o_{bet}"),
        ("⬅️ Назад", "game_dice"),
    ]
    await call.message.edit_text(
        f"🎲 <b>Кубик</b>\nСтавка: <b>{bet} ⭐</b>\n\nНа что ставите?",
        reply_markup=kb(*buttons, adjust=(3, 3, 1, 1, 1)),
    )
    await call.answer()

@router.callback_query(F.data.startswith("dice_p_"))
async def dice_play(call: CallbackQuery):
    p = call.data.split("_")
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
    await add_wagered(call.from_user.id, bet)
    
    roll = await rigged_dice(mode, num)

    win = 0
    if mode == "n" and roll == num: win = int(bet * 5)
    elif mode == "e" and roll % 2 == 0: win = int(bet * 1.9)
    elif mode == "o" and roll % 2 == 1: win = int(bet * 1.9)

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
        reply_markup=kb(("🔄 Ещё", "game_dice"), ("🏠 Меню", "menu"), adjust=(2,)),
    )
    await call.answer()

# ── МОНЕТКА ──
@router.callback_query(F.data == "game_coin")
async def coin_bet(call: CallbackQuery):
    buttons = [(f"{a} ⭐", f"coin_b_{a}") for a in PRESET_BETS]
    buttons.append(("⬅️ Назад", "games"))
    await call.message.edit_text(
        "🪙 <b>Монетка</b> — выигрыш ×1.9\n\nВыберите ставку:",
        reply_markup=kb(*buttons, adjust=(2, 2, 1)),
    )
    await call.answer()

@router.callback_query(F.data.startswith("coin_b_"))
async def coin_pick(call: CallbackQuery):
    bet = int(call.data.split("_")[2])
    bal = await get_balance(call.from_user.id)
    if bet > bal:
        await call.answer(
