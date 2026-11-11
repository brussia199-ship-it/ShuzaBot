import telebot
from telebot import types, apihelper
import sqlite3
import random

apihelper.API_URL = "https://api.shuzagram.com/bot{0}/{1}"
TOKEN = "1780243441:qnHVWd0YLEYxOn20Av9O-QnlSdkTmRq9z33"
ADMIN_ID = 1780243433
DB = "casino.db"

bot = telebot.TeleBot(TOKEN, parse_mode="HTML")

def db_init():
    with sqlite3.connect(DB) as c:
        c.execute("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, bal INTEGER DEFAULT 0)")
        c.execute("CREATE TABLE IF NOT EXISTS settings (k TEXT PRIMARY KEY, v TEXT)")
        c.execute("INSERT OR IGNORE INTO settings VALUES ('rate', '45')")
        c.commit()

def get_bal(uid):
    with sqlite3.connect(DB) as c:
        r = c.execute("SELECT bal FROM users WHERE id=?", (uid,)).fetchone()
        return r[0] if r else 0

def add_bal(uid, amt):
    with sqlite3.connect(DB) as c:
        c.execute("INSERT INTO users(id, bal) VALUES(?, ?) ON CONFLICT(id) DO UPDATE SET bal=bal+?", (uid, amt, amt))
        c.commit()
        return get_bal(uid)

def get_rate():
    with sqlite3.connect(DB) as c:
        r = c.execute("SELECT v FROM settings WHERE k='rate'").fetchone()
        return int(r[0]) if r else 45

def set_rate(v):
    with sqlite3.connect(DB) as c:
        c.execute("UPDATE settings SET v=? WHERE k='rate'", (str(v),))
        c.commit()

db_init()

# --- АДМИНКА ---
@bot.message_handler(commands=['admin'])
def admin_cmd(m):
    bot.clear_step_handler_by_chat_id(m.chat.id)
    if m.from_user.id != ADMIN_ID:
        return bot.send_message(m.chat.id, f"⛔ Нет доступа.\nТвой ID: {m.from_user.id}")
    kb = types.InlineKeyboardMarkup(row_width=1)
    kb.add(
        types.InlineKeyboardButton(f"🎲 Шанс: {get_rate()}%", callback_data="adm_rate"),
        types.InlineKeyboardButton("💰 Выдать/Забрать", callback_data="adm_bal"),
        types.InlineKeyboardButton("📊 Статистика", callback_data="adm_stats")
    )
    bot.send_message(m.chat.id, "🛠 <b>Админ-панель</b>", reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data == "adm_stats")
def adm_stats(c):
    if c.from_user.id != ADMIN_ID: return
    with sqlite3.connect(DB) as db:
        u = db.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        total = db.execute("SELECT SUM(bal) FROM users").fetchone()[0] or 0
    bot.answer_callback_query(c.id, f"Юзеров: {u}\nОбщий баланс: {total} ⭐", show_alert=True)

@bot.callback_query_handler(func=lambda c: c.data == "adm_rate")
def adm_rate(c):
    if c.from_user.id != ADMIN_ID: return
    kb = types.InlineKeyboardMarkup(row_width=3)
    for r in [0, 20, 40, 50, 70, 100]:
        kb.add(types.InlineKeyboardButton(f"{r}%", callback_data=f"setr_{r}"))
    bot.edit_message_text("Шанс победы игрока:", c.message.chat.id, c.message.message_id, reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data.startswith("setr_"))
def setr(c):
    if c.from_user.id != ADMIN_ID: return
    r = int(c.data.split("_")[1])
    set_rate(r)
    bot.answer_callback_query(c.id, f"✅ Шанс: {r}%")
    bot.edit_message_text(f"✅ Шанс победы: {r}%\nНажми /admin для возврата.", c.message.chat.id, c.message.message_id)

@bot.callback_query_handler(func=lambda c: c.data == "adm_bal")
def adm_bal(c):
    if c.from_user.id != ADMIN_ID: return
    msg = bot.send_message(c.message.chat.id, "Введи: <code>ID сумма</code> (например: <code>123456 500</code>):")
    bot.register_next_step_handler(msg, adm_bal_process)

def adm_bal_process(m):
    if m.from_user.id != ADMIN_ID: return
    try:
        uid, amt = map(int, m.text.split())
        new = add_bal(uid, amt)
        bot.send_message(m.chat.id, f"✅ Юзеру {uid} изменен баланс на {amt}.\nТекущий: {new} ⭐")
    except:
        bot.send_message(m.chat.id, "❌ Ошибка формата.")

# --- МЕНЮ ---
def main_menu():
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("🎮 Игры", callback_data="menu_games"),
        types.InlineKeyboardButton("💳 Пополнить", callback_data="menu_topup"),
        types.InlineKeyboardButton("💸 Вывести", callback_data="menu_withdraw"),
        types.InlineKeyboardButton("👤 Профиль", callback_data="menu_prof")
    )
    return kb

@bot.message_handler(commands=['start'])
def start(m):
    bot.clear_step_handler_by_chat_id(m.chat.id)
    add_bal(m.from_user.id, 0)
    bot.send_message(m.chat.id, f"👋 <b>Казино</b>\nБаланс: <b>{get_bal(m.from_user.id)} ⭐</b>", reply_markup=main_menu())

@bot.callback_query_handler(func=lambda c: c.data == "menu_prof")
def prof(c):
    bot.answer_callback_query(c.id, f"Твой баланс: {get_bal(c.from_user.id)} ⭐", show_alert=True)

@bot.callback_query_handler(func=lambda c: c.data == "menu_back")
def back(c):
    bot.edit_message_text(f"👋 <b>Казино</b>\nБаланс: <b>{get_bal(c.from_user.id)} ⭐</b>", c.message.chat.id, c.message.message_id, reply_markup=main_menu())

# --- ПОПОЛНЕНИЕ ---
@bot.callback_query_handler(func=lambda c: c.data == "menu_topup")
def topup(c):
    kb = types.InlineKeyboardMarkup(row_width=3)
    for amt in [50, 100, 250, 500, 1000]:
        kb.add(types.InlineKeyboardButton(f"{amt} ⭐", callback_data=f"inv_{amt}"))
    kb.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="menu_back"))
    bot.edit_message_text("Выбери сумму пополнения:", c.message.chat.id, c.message.message_id, reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data.startswith("inv_"))
def inv(c):
    amt = int(c.data.split("_")[1])
    try:
        bot.send_invoice(c.message.chat.id, f"Пополнение", f"Плюс {amt} звезд", f"top|{c.from_user.id}|{amt}", "", "XTR", [types.LabeledPrice("Пополнение", amt)])
    except Exception as e:
        bot.send_message(c.message.chat.id, f"⚠️ Ошибка API: {e}")

@bot.pre_checkout_query_handler(func=lambda q: True)
def pre(q): 
    bot.answer_pre_checkout_query(q.id, ok=True)

@bot.message_handler(content_types=['successful_payment'])
def paid(m):
    _, uid, amt = m.successful_payment.invoice_payload.split("|")
    add_bal(int(uid), int(amt))
    bot.send_message(m.chat.id, f"✅ Баланс пополнен на {amt} ⭐")

# --- ВЫВОД NFT ---
@bot.callback_query_handler(func=lambda c: c.data == "menu_withdraw")
def wd(c):
    msg = bot.send_message(c.message.chat.id, f"Введи сумму вывода (доступно {get_bal(c.from_user.id)} ⭐, мин 15):")
    bot.register_next_step_handler(msg, wd_proc)

def wd_proc(m):
    try: amt = int(m.text)
    except: return bot.send_message(m.chat.id, "❌ Ошибка. Введи число.")
    
    if amt < 15: return bot.send_message(m.chat.id, "❌ Минимум 15 ⭐.")
    if amt > get_bal(m.from_user.id): return bot.send_message(m.chat.id, "❌ Мало средств.")

    bot.send_message(m.chat.id, "⏳ Отправляю NFT...")
    try:
        gifts = bot.get_available_gifts()
        valid = sorted([g for g in gifts.gifts if g.star_count <= amt], key=lambda x: x.star_count)
        if not valid: return bot.send_message(m.chat.id, f"❌ Нет подарков на сумму {amt} ⭐.")
        
        bot.send_gift(user_id=m.from_user.id, gift_id=valid[-1].id, text="Вывод из казино", pay_for_upgrade=True)
        add_bal(m.from_user.id, -amt)
        bot.send_message(m.chat.id, f"🎁 Выведено {amt} ⭐!", reply_markup=main_menu())
    except Exception as e:
        bot.send_message(m.chat.id, f"⚠️ Ошибка: {e}", reply_markup=main_menu())

# --- ИГРЫ ---
@bot.callback_query_handler(func=lambda c: c.data == "menu_games")
def games(c):
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("🎲 Кубик", callback_data="game_dice"),
        types.InlineKeyboardButton("🪙 Монетка", callback_data="game_coin"),
        types.InlineKeyboardButton("💣 Мины", callback_data="game_mines"),
        types.InlineKeyboardButton("⬅️ Назад", callback_data="menu_back")
    )
    bot.edit_message_text("Выбери игру:", c.message.chat.id, c.message.message_id, reply_markup=kb)

def get_bet_kb(game):
    kb = types.InlineKeyboardMarkup(row_width=2)
    for amt in [10, 50, 100, 500]:
        kb.add(types.InlineKeyboardButton(f"{amt} ⭐", callback_data=f"bet_{game}_{amt}"))
    kb.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="menu_games"))
    return kb

@bot.callback_query_handler(func=lambda c: c.data.startswith("game_"))
def g_menu(c):
    bot.edit_message_text("Выбери ставку:", c.message.chat.id, c.message.message_id, reply_markup=get_bet_kb(c.data))

@bot.callback_query_handler(func=lambda c: c.data.startswith("bet_"))
def play(c):
    _, game, amt = c.data.split("_")
    amt = int(amt)
    uid = c.from_user.id
    if get_bal(uid) < amt: return bot.answer_callback_query(c.id, "❌ Мало средств!", show_alert=True)
    
    win = random.randint(1, 100) <= get_rate()
    add_bal(uid, -amt)
    
    if game == "game_dice": res, mult = ("🎲 Выпало: 6\n", 2) if win else ("🎲 Выпало: 1\n", 0)
    elif game == "game_coin": res, mult = ("🪙 Орёл!\n", 2) if win else ("🪙 Решка!\n", 0)
    else: res, mult = ("💣 Ты выжил!\n", 3) if win else ("💣 Взрыв!\n", 0)
        
    if win:
        win_amt = amt * mult
        add_bal(uid, win_amt)
        txt = f"{res}🎉 Победа! +{win_amt} ⭐"
    else:
        txt = f"{res}😢 Проигрыш. -{amt} ⭐"
        
    bot.edit_message_text(f"{txt}\n\nБаланс: {get_bal(uid)} ⭐", c.message.chat.id, c.message.message_id, reply_markup=types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("🏠 В меню", callback_data="menu_back")))

if __name__ == '__main__':
    print("Бот запущен!")
    bot.infinity_polling(skip_pending=True)
