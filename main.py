import telebot
from telebot import types, apihelper
import sqlite3
import random
import string
import time

# --- SHUZAGRAM ---
apihelper.API_URL = "https://api.shuzagram.com/bot{0}/{1}"
TOKEN = "1780243441:qnHVWd0YLEYxOn20Av9O-QnlSdkTmRq9z33"
ADMIN_ID = 17802434833
SUPPORT = "@MusorchikSupport"
ADMIN_U = "@Musorchik"
BOT_U = "@MusorchikBot"
DB = "casino.db"

bot = telebot.TeleBot(TOKEN)

# --- БД ---
def db_init():
    with sqlite3.connect(DB) as c:
        cur = c.cursor()
        cur.execute("""CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY, username TEXT, balance INTEGER DEFAULT 0,
            total_bet INTEGER DEFAULT 0, total_won INTEGER DEFAULT 0)""")
        cur.execute("""CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)""")
        cur.execute("""CREATE TABLE IF NOT EXISTS payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER,
            charge_id TEXT UNIQUE, amount INTEGER, is_withdrawn INTEGER DEFAULT 0)""")
        cur.execute("""CREATE TABLE IF NOT EXISTS withdrawals (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, amount INTEGER,
            status TEXT DEFAULT 'pending')""")
        cur.execute("""CREATE TABLE IF NOT EXISTS history (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, game TEXT,
            bet INTEGER, win INTEGER, ts TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
        cur.execute("INSERT OR IGNORE INTO settings VALUES ('win_rate', '45')")
        cur.execute("INSERT OR IGNORE INTO settings VALUES ('min_bet', '10')")
        cur.execute("INSERT OR IGNORE INTO settings VALUES ('min_wd', '100')")
        c.commit()

def get_set(key, default="0"):
    with sqlite3.connect(DB) as c:
        r = c.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return r[0] if r else default

def set_set(key, val):
    with sqlite3.connect(DB) as c:
        c.execute("INSERT OR REPLACE INTO settings VALUES (?, ?)", (key, str(val)))
        c.commit()

def get_user(uid):
    with sqlite3.connect(DB) as c:
        return c.execute("SELECT * FROM users WHERE user_id=?", (uid,)).fetchone()

def ensure_user(uid, un):
    with sqlite3.connect(DB) as c:
        c.execute("INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)", (uid, un or "None"))
        c.execute("UPDATE users SET username=? WHERE user_id=?", (un or "None", uid))
        c.commit()

def get_bal(uid):
    with sqlite3.connect(DB) as c:
        r = c.execute("SELECT balance FROM users WHERE user_id=?", (uid,)).fetchone()
        return r[0] if r else 0

def add_bal(uid, amt):
    with sqlite3.connect(DB) as c:
        c.execute("INSERT INTO users (user_id, balance) VALUES (?, ?) ON CONFLICT(user_id) DO UPDATE SET balance=balance+excluded.balance", (uid, amt))
        c.commit()
        r = c.execute("SELECT balance FROM users WHERE user_id=?", (uid,)).fetchone()
        return r[0] if r else 0

def add_stat(uid, bet, win):
    with sqlite3.connect(DB) as c:
        c.execute("UPDATE users SET total_bet=total_bet+?, total_won=total_won+? WHERE user_id=?", (bet, win, uid))
        c.commit()

def log_game(uid, game, bet, win):
    with sqlite3.connect(DB) as c:
        c.execute("INSERT INTO history (user_id, game, bet, win) VALUES (?, ?, ?, ?)", (uid, game, bet, win))
        c.commit()

# --- КЛАВИАТУРЫ ---
def main_kb():
    m = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    m.add(
        types.KeyboardButton("🎮 Играть"), types.KeyboardButton("💳 Пополнить"),
        types.KeyboardButton("💸 Вывести"), types.KeyboardButton("👤 Профиль"),
        types.KeyboardButton("📜 История"), types.KeyboardButton("ℹ️ Помощь")
    )
    return m

def games_kb():
    m = types.InlineKeyboardMarkup(row_width=2)
    m.add(
        types.InlineKeyboardButton("🎲 Кубик", callback_data="g_dice"),
        types.InlineKeyboardButton("🪙 Монетка", callback_data="g_coin"),
        types.InlineKeyboardButton("💣 Мины", callback_data="g_mines"),
        types.InlineKeyboardButton("🎰 Слоты", callback_data="g_slots"),
        types.InlineKeyboardButton("🎯 Рулетка", callback_data="g_roul")
    )
    return m

def admin_kb():
    m = types.InlineKeyboardMarkup(row_width=1)
    m.add(
        types.InlineKeyboardButton("📊 Статистика", callback_data="a_stats"),
        types.InlineKeyboardButton("🎲 Шанс выигрыша", callback_data="a_rate"),
        types.InlineKeyboardButton("📥 Заявки на вывод", callback_data="a_wds")
    )
    return m

# --- СТАРТ ---
@bot.message_handler(commands=["start"])
def start(m):
    ensure_user(m.from_user.id, m.from_user.username)
    bot.send_message(m.chat.id, f"👋 <b>Казино</b>\nБаланс: <b>{get_bal(m.from_user.id)} ⭐</b>\n\nПоддержка: {SUPPORT}\nАдмин: {ADMIN_U}", reply_markup=main_kb(), parse_mode="HTML")

# --- ПРОФИЛЬ ---
@bot.message_handler(func=lambda m: m.text == "👤 Профиль")
def profile(m):
    u = get_user(m.from_user.id)
    if not u: return
    bot.send_message(m.chat.id, f"👤 <b>Профиль</b>\n\nID: <code>{u[0]}</code>\nБаланс: <b>{u[2]} ⭐</b>\nВсего ставок: {u[3]}\nВсего выиграно: {u[4]}", reply_markup=main_kb(), parse_mode="HTML")

# --- ПОПОЛНЕНИЕ (sendInvoice) ---
@bot.message_handler(func=lambda m: m.text == "💳 Пополнить")
def topup_menu(m):
    mk = types.InlineKeyboardMarkup(row_width=2)
    for amt in [50, 100, 250, 500, 1000]:
        mk.add(types.InlineKeyboardButton(f"{amt} ⭐", callback_data=f"top_{amt}"))
    bot.send_message(m.chat.id, "Выберите сумму:", reply_markup=mk)

@bot.callback_query_handler(func=lambda c: c.data.startswith("top_"))
def topup_invoice(c):
    amount = int(c.data.split("_")[1])
    payload = f"topup|{c.from_user.id}|{amount}"
    try:
        bot.send_invoice(
            chat_id=c.message.chat.id,
            title="Пополнение",
            description=f"Пополнение на {amount} ⭐",
            invoice_payload=payload,
            provider_token="",
            currency="XTR",
            prices=[types.LabeledPrice(label="Пополнение", amount=amount)],
            start_parameter="topup"
        )
    except Exception as e:
        bot.answer_callback_query(c.id, f"Ошибка: {e}", show_alert=True)
    bot.answer_callback_query(c.id)

@bot.pre_checkout_query_handler(func=lambda q: True)
def pre_checkout(q):
    bot.answer_pre_checkout_query(q.id, ok=True)

@bot.message_handler(content_types=['successful_payment'])
def on_paid(m):
    payload = m.successful_payment.invoice_payload
    parts = payload.split("|")
    if parts[0] == "topup":
        uid, amount = int(parts[1]), int(parts[2])
        add_bal(uid, amount)
        bot.send_message(m.chat.id, f"✅ Пополнено на {amount} ⭐")

# --- ВЫВОД ЧЕРЕЗ NFT-ПОДАРКИ (sendGift) ---
@bot.message_handler(func=lambda m: m.text == "💸 Вывести")
def withdraw_start(m):
    bal = get_bal(m.from_user.id)
    min_wd = int(get_set("min_wd"))
    if bal < min_wd:
        return bot.send_message(m.chat.id, f"❌ Минимум для вывода: {min_wd} ⭐", reply_markup=main_kb())
    msg = bot.send_message(m.chat.id, f"Введите сумму для вывода (доступно {bal} ⭐):", reply_markup=types.ReplyKeyboardRemove())
    bot.register_next_step_handler(msg, withdraw_amount)

def withdraw_amount(m):
    try:
        amount = int(m.text)
    except:
        return bot.send_message(m.chat.id, "❌ Неверная сумма.", reply_markup=main_kb())
    uid = m.from_user.id
    bal = get_bal(uid)
    if amount <= 0 or amount > bal:
        return bot.send_message(m.chat.id, "❌ Ошибка суммы.", reply_markup=main_kb())
    
    # Списываем баланс и создаём заявку
    add_bal(uid, -amount)
    with sqlite3.connect(DB) as c:
        cur = c.cursor()
        cur.execute("INSERT INTO withdrawals (user_id, amount) VALUES (?, ?)", (uid, amount))
        req_id = cur.lastrowid
        c.commit()
    
    bot.send_message(m.chat.id, f"✅ Заявка #{req_id} на {amount} ⭐ создана. Ожидайте NFT-подарок.", reply_markup=main_kb())
    # Уведомление админу
    try:
        mk = types.InlineKeyboardMarkup()
        mk.add(types.InlineKeyboardButton("✅ Отправить NFT", callback_data=f"send_nft_{req_id}"))
        bot.send_message(ADMIN_ID, f"📥 Заявка на вывод #{req_id}\nПользователь: {uid}\nСумма: {amount} ⭐", reply_markup=mk)
    except: pass

# --- ОТПРАВКА NFT-ПОДАРКА (АДМИН) ---
@bot.callback_query_handler(func=lambda c: c.data.startswith("send_nft_"))
def send_nft(c):
    if c.from_user.id != ADMIN_ID: return
    req_id = int(c.data.split("_")[2])
    with sqlite3.connect(DB) as conn:
        cur = conn.cursor()
        cur.execute("SELECT user_id, amount FROM withdrawals WHERE id=? AND status='pending'", (req_id,))
        row = cur.fetchone()
        if not row:
            return bot.answer_callback_query(c.id, "Заявка не найдена", show_alert=True)
        uid, amount = row
        
        # Получаем доступные подарки
        try:
            gifts = bot.get_available_gifts()
        except Exception as e:
            return bot.send_message(c.message.chat.id, f"⚠️ Ошибка получения подарков: {e}")
        
        # Выбираем первый доступный подарок (можно выбрать самый дешёвый)
        gift_id = None
        for g in gifts.gifts:
            if g.star_count <= amount:  # Ищем подарок, который укладывается в сумму
                gift_id = g.id
                break
        
        if not gift_id:
            # Если нет подходящего, берем первый
            gift_id = gifts.gifts[0].id if gifts.gifts else None
        
        if not gift_id:
            return bot.send_message(c.message.chat.id, "❌ Нет доступных подарков.")
        
        try:
            # Отправляем NFT-подарок
            bot.send_gift(
                user_id=uid,
                gift_id=gift_id,
                text=f"Вывод {amount} ⭐ из казино",
                pay_for_upgrade=True  # Оплачиваем апгрейд, чтобы получатель не платил
            )
            cur.execute("UPDATE withdrawals SET status='approved' WHERE id=?", (req_id,))
            conn.commit()
            bot.send_message(c.message.chat.id, f"✅ NFT-подарок отправлен пользователю {uid}.")
            try:
                bot.send_message(uid, f"🎁 Вам отправлен NFT-подарок на сумму {amount} ⭐!")
            except: pass
        except Exception as e:
            bot.send_message(c.message.chat.id, f"⚠️ Ошибка sendGift: {e}")
    bot.answer_callback_query(c.id)

# --- ИГРЫ ---
@bot.message_handler(func=lambda m: m.text == "🎮 Играть")
def play(m):
    bot.send_message(m.chat.id, "Выберите игру:", reply_markup=games_kb())

# Кубик
@bot.callback_query_handler(func=lambda c: c.data == "g_dice")
def dice_bet(c):
    msg = bot.send_message(c.message.chat.id, "Введите ставку:", reply_markup=types.ReplyKeyboardRemove())
    bot.register_next_step_handler(msg, dice_roll)

def dice_roll(m):
    try: bet = int(m.text)
    except: return bot.send_message(m.chat.id, "❌ Неверная ставка.", reply_markup=main_kb())
    uid = m.from_user.id
    if bet < int(get_set("min_bet")) or bet > get_bal(uid):
        return bot.send_message(m.chat.id, "❌ Ошибка ставки.", reply_markup=main_kb())
    
    add_bal(uid, -bet)
    win = random.randint(1, 6) % 2 == 0  # Чет/нечет
    rate = int(get_set("win_rate"))
    win = random.randint(1, 100) <= rate
    
    if win:
        payout = bet * 2
        add_bal(uid, payout)
        add_stat(uid, bet, payout)
        log_game(uid, "dice", bet, payout)
        bot.send_message(m.chat.id, f"🎲 Победа! +{payout} ⭐", reply_markup=main_kb())
    else:
        add_stat(uid, bet, 0)
        log_game(uid, "dice", bet, 0)
        bot.send_message(m.chat.id, f"🎲 Проигрыш. -{bet} ⭐", reply_markup=main_kb())

# Монетка
@bot.callback_query_handler(func=lambda c: c.data == "g_coin")
def coin_bet(c):
    msg = bot.send_message(c.message.chat.id, "Введите ставку:", reply_markup=types.ReplyKeyboardRemove())
    bot.register_next_step_handler(msg, coin_flip)

def coin_flip(m):
    try: bet = int(m.text)
    except: return bot.send_message(m.chat.id, "❌ Неверная ставка.", reply_markup=main_kb())
    uid = m.from_user.id
    if bet < int(get_set("min_bet")) or bet > get_bal(uid):
        return bot.send_message(m.chat.id, "❌ Ошибка ставки.", reply_markup=main_kb())
    
    add_bal(uid, -bet)
    rate = int(get_set("win_rate"))
    win = random.randint(1, 100) <= rate
    
    if win:
        payout = bet * 2
        add_bal(uid, payout)
        add_stat(uid, bet, payout)
        log_game(uid, "coin", bet, payout)
        bot.send_message(m.chat.id, f"🪙 Орёл! Победа! +{payout} ⭐", reply_markup=main_kb())
    else:
        add_stat(uid, bet, 0)
        log_game(uid, "coin", bet, 0)
        bot.send_message(m.chat.id, f"🪙 Решка. Проигрыш. -{bet} ⭐", reply_markup=main_kb())

# Мины (упрощённо)
@bot.callback_query_handler(func=lambda c: c.data == "g_mines")
def mines_bet(c):
    msg = bot.send_message(c.message.chat.id, "Введите ставку:", reply_markup=types.ReplyKeyboardRemove())
    bot.register_next_step_handler(msg, mines_start)

def mines_start(m):
    try: bet = int(m.text)
    except: return bot.send_message(m.chat.id, "❌ Неверная ставка.", reply_markup=main_kb())
    uid = m.from_user.id
    if bet < int(get_set("min_bet")) or bet > get_bal(uid):
        return bot.send_message(m.chat.id, "❌ Ошибка ставки.", reply_markup=main_kb())
    
    add_bal(uid, -bet)
    # Простая логика: 3 мины на 9 клеток
    mines = set(random.sample(range(9), 3))
    kb = types.InlineKeyboardMarkup(row_width=3)
    for i in range(9):
        kb.add(types.InlineKeyboardButton("⬜", callback_data=f"mine_{i}_{bet}"))
    bot.send_message(m.chat.id, "💣 Выберите клетку (3 мины из 9):", reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data.startswith("mine_"))
def mine_click(c):
    _, idx, bet = c.data.split("_")
    idx, bet = int(idx), int(bet)
    uid = c.from_user.id
    # Упрощённо: 30% шанс победы
    rate = int(get_set("win_rate"))
    win = random.randint(1, 100) <= rate
    if win:
        payout = bet * 2
        add_bal(uid, payout)
        add_stat(uid, bet, payout)
        log_game(uid, "mines", bet, payout)
        bot.edit_message_text(f"💣 Победа! +{payout} ⭐", c.message.chat.id, c.message.message_id)
    else:
        add_stat(uid, bet, 0)
        log_game(uid, "mines", bet, 0)
        bot.edit_message_text(f"💣 Мина! Проигрыш. -{bet} ⭐", c.message.chat.id, c.message.message_id)
    bot.answer_callback_query(c.id)

# Слоты
@bot.callback_query_handler(func=lambda c: c.data == "g_slots")
def slots_bet(c):
    msg = bot.send_message(c.message.chat.id, "Введите ставку:", reply_markup=types.ReplyKeyboardRemove())
    bot.register_next_step_handler(msg, slots_play)

def slots_play(m):
    try: bet = int(m.text)
    except: return bot.send_message(m.chat.id, "❌ Неверная ставка.", reply_markup=main_kb())
    uid = m.from_user.id
    if bet < int(get_set("min_bet")) or bet > get_bal(uid):
        return bot.send_message(m.chat.id, "❌ Ошибка ставки.", reply_markup=main_kb())
    
    add_bal(uid, -bet)
    rate = int(get_set("win_rate"))
    win = random.randint(1, 100) <= rate
    if win:
        payout = bet * 5
        add_bal(uid, payout)
        add_stat(uid, bet, payout)
        log_game(uid, "slots", bet, payout)
        bot.send_message(m.chat.id, f"🎰 Джекпот! +{payout} ⭐", reply_markup=main_kb())
    else:
        add_stat(uid, bet, 0)
        log_game(uid, "slots", bet, 0)
        bot.send_message(m.chat.id, f"🎰 Проигрыш. -{bet} ⭐", reply_markup=main_kb())

# Рулетка
@bot.callback_query_handler(func=lambda c: c.data == "g_roul")
def roul_bet(c):
    msg = bot.send_message(c.message.chat.id, "Введите ставку:", reply_markup=types.ReplyKeyboardRemove())
    bot.register_next_step_handler(msg, roul_play)

def roul_play(m):
    try: bet = int(m.text)
    except: return bot.send_message(m.chat.id, "❌ Неверная ставка.", reply_markup=main_kb())
    uid = m.from_user.id
    if bet < int(get_set("min_bet")) or bet > get_bal(uid):
        return bot.send_message(m.chat.id, "❌ Ошибка ставки.", reply_markup=main_kb())
    
    add_bal(uid, -bet)
    rate = int(get_set("win_rate"))
    win = random.randint(1, 100) <= rate
    if win:
        payout = bet * 3
        add_bal(uid, payout)
        add_stat(uid, bet, payout)
        log_game(uid, "roulette", bet, payout)
        bot.send_message(m.chat.id, f"🎯 Победа! +{payout} ⭐", reply_markup=main_kb())
    else:
        add_stat(uid, bet, 0)
        log_game(uid, "roulette", bet, 0)
        bot.send_message(m.chat.id, f"🎯 Проигрыш. -{bet} ⭐", reply_markup=main_kb())

# --- ИСТОРИЯ ---
@bot.message_handler(func=lambda m: m.text == "📜 История")
def hist(m):
    with sqlite3.connect(DB) as c:
        rows = c.execute("SELECT game, bet, win, ts FROM history WHERE user_id=? ORDER BY id DESC LIMIT 10", (m.from_user.id,)).fetchall()
    if not rows:
        return bot.send_message(m.chat.id, "История пуста.", reply_markup=main_kb())
    text = "📜 <b>Последние игры:</b>\n\n"
    for g, b, w, ts in rows:
        text += f"{g}: ставка {b}, выигрыш {w} ({ts})\n"
    bot.send_message(m.chat.id, text, reply_markup=main_kb(), parse_mode="HTML")

# --- ПОМОЩЬ ---
@bot.message_handler(func=lambda m: m.text == "ℹ️ Помощь")
def help_cmd(m):
    bot.send_message(m.chat.id, f"ℹ️ <b>Помощь</b>\n\n🎮 Игры: Кубик, Монетка, Мины, Слоты, Рулетка\n💳 Пополнение через звёзды\n💸 Вывод через NFT-подарки\n\nПоддержка: {SUPPORT}\nАдмин: {ADMIN_U}\nБот: {BOT_U}", reply_markup=main_kb(), parse_mode="HTML")

# --- АДМИН ---
@bot.message_handler(commands=["admin"])
def admin_panel(m):
    if m.from_user.id != ADMIN_ID: return
    bot.send_message(m.chat.id, "🛠 <b>Админ-панель</b>", reply_markup=admin_kb(), parse_mode="HTML")

@bot.callback_query_handler(func=lambda c: c.data.startswith("a_"))
def admin_cb(c):
    if c.from_user.id != ADMIN_ID: return
    if c.data == "a_stats":
        with sqlite3.connect(DB) as conn:
            u = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
            t = conn.execute("SELECT COUNT(*) FROM history").fetchone()[0]
        bot.send_message(c.message.chat.id, f"📊 Юзеров: {u}\nИгр: {t}")
    elif c.data == "a_rate":
        msg = bot.send_message(c.message.chat.id, f"Текущий шанс: {get_set('win_rate')}%\nВведите новый (0-100):")
        bot.register_next_step_handler(msg, set_rate)
    elif c.data == "a_wds":
        with sqlite3.connect(DB) as conn:
            rows = conn.execute("SELECT id, user_id, amount FROM withdrawals WHERE status='pending'").fetchall()
        if not rows: return bot.answer_callback_query(c.id, "Нет заявок", show_alert=True)
        text = "📥 <b>Заявки:</b>\n\n"
        mk = types.InlineKeyboardMarkup(row_width=1)
        for rid, uid, amt in rows:
            text += f"#{rid}: {uid} — {amt} ⭐\n"
            mk.add(types.InlineKeyboardButton(f"Отправить NFT #{rid}", callback_data=f"send_nft_{rid}"))
        bot.send_message(c.message.chat.id, text, reply_markup=mk, parse_mode="HTML")
    bot.answer_callback_query(c.id)

def set_rate(m):
    try:
        rate = int(m.text)
        if 0 <= rate <= 100:
            set_set("win_rate", rate)
            bot.send_message(m.chat.id, f"✅ Шанс установлен: {rate}%", reply_markup=main_kb())
    except: bot.send_message(m.chat.id, "❌ Ошибка.")

# --- ЗАПУСК ---
db_init()
print("Казино-бот запущен!")
bot.infinity_polling()
