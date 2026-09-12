import asyncio
import logging
import sqlite3
import random
from datetime import datetime

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

# ================= НАСТРОЙКИ =================
BOT_TOKEN = "8893559516:AAHCoN4o1Ha_pVcn0qE2beuLNFleuMVdsLA"
DB_PATH = "ranked.db"

MAPS_5v5 = ["Prison", "Hanami", "Rust", "Dune", "Breeze", "Province", "Sandstone"]
MAPS_2v2 = ["Prison", "Hanami", "Rust", "Dune", "Breeze", "Province", "Sandstone"]

# ================= БАЗА =================
def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS players (
            telegram_id INTEGER PRIMARY KEY,
            game_id TEXT UNIQUE,
            nickname TEXT,
            elo INTEGER DEFAULT 0,
            kills INTEGER DEFAULT 0,
            deaths INTEGER DEFAULT 0,
            assists INTEGER DEFAULT 0,
            wins INTEGER DEFAULT 0,
            losses INTEGER DEFAULT 0,
            matches INTEGER DEFAULT 0
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS parties (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_id INTEGER,
            message_id INTEGER,
            chat_id INTEGER,
            status TEXT DEFAULT 'open',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS party_members (
            party_id INTEGER,
            player_id INTEGER,
            PRIMARY KEY (party_id, player_id)
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS party_invites (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            party_id INTEGER,
            inviter_id INTEGER,
            invitee_id INTEGER,
            status TEXT DEFAULT 'pending',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS lobbies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT UNIQUE,
            owner_id INTEGER,
            mode TEXT,
            status TEXT DEFAULT 'banning',
            message_id INTEGER,
            chat_id INTEGER,
            banned_maps TEXT DEFAULT '',
            final_map TEXT,
            score TEXT,
            winner_team INTEGER,
            cancel_reason TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS lobby_players (
            lobby_id INTEGER,
            player_id INTEGER,
            team INTEGER,
            captain INTEGER DEFAULT 0,
            ready INTEGER DEFAULT 0,
            kills INTEGER DEFAULT 0,
            deaths INTEGER DEFAULT 0,
            assists INTEGER DEFAULT 0,
            screenshot TEXT,
            forgot_screenshot INTEGER DEFAULT 0,
            PRIMARY KEY (lobby_id, player_id)
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS match_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            lobby_code TEXT,
            mode TEXT,
            map TEXT,
            score TEXT,
            winner_team INTEGER,
            played_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()

# ================= ХЕЛПЕРЫ =================
def get_player(tg_id):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT * FROM players WHERE telegram_id = ?", (tg_id,))
    row = cur.fetchone()
    conn.close()
    return row

def get_player_by_game_id(game_id):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT * FROM players WHERE game_id = ?", (game_id,))
    row = cur.fetchone()
    conn.close()
    return row

def register_player(tg_id, game_id, nickname):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    try:
        cur.execute("INSERT INTO players (telegram_id, game_id, nickname) VALUES (?, ?, ?)",
                    (tg_id, game_id, nickname))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()

def update_stats(tg_id, new_elo, won, kills=0, deaths=0, assists=0):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    if won:
        cur.execute("""UPDATE players SET elo=?, wins=wins+1, matches=matches+1,
                       kills=kills+?, deaths=deaths+?, assists=assists+?
                       WHERE telegram_id=?""",
                    (new_elo, kills, deaths, assists, tg_id))
    else:
        cur.execute("""UPDATE players SET elo=?, losses=losses+1, matches=matches+1,
                       kills=kills+?, deaths=deaths+?, assists=assists+?
                       WHERE telegram_id=?""",
                    (new_elo, kills, deaths, assists, tg_id))
    conn.commit()
    conn.close()

def get_rank(elo):
    if elo < 100: return "🥉 Bronze"
    if elo < 300: return "🥈 Silver"
    if elo < 600: return "🥇 Gold"
    if elo < 1000: return "💎 Platinum"
    if elo < 1500: return "💠 Diamond"
    if elo < 2000: return "👑 Master"
    return "🔥 Legend"

# ================= ПАТИ =================
def create_party(owner_id, message_id, chat_id):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("INSERT INTO parties (owner_id, message_id, chat_id) VALUES (?, ?, ?)",
                (owner_id, message_id, chat_id))
    party_id = cur.lastrowid
    cur.execute("INSERT INTO party_members (party_id, player_id) VALUES (?, ?)", (party_id, owner_id))
    conn.commit()
    conn.close()
    return party_id

def get_party(party_id):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT * FROM parties WHERE id = ?", (party_id,))
    row = cur.fetchone()
    conn.close()
    return row

def get_party_members(party_id):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""SELECT p.telegram_id, p.nickname, p.elo
                   FROM players p JOIN party_members pm ON p.telegram_id = pm.player_id
                   WHERE pm.party_id = ? ORDER BY p.elo DESC""", (party_id,))
    rows = cur.fetchall()
    conn.close()
    return rows

def get_player_party(tg_id):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""SELECT p.* FROM parties p JOIN party_members pm ON p.id = pm.party_id
                   WHERE pm.player_id = ? AND p.status = 'open'""", (tg_id,))
    row = cur.fetchone()
    conn.close()
    return row

def add_to_party(party_id, player_id):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    try:
        cur.execute("INSERT INTO party_members (party_id, player_id) VALUES (?, ?)",
                    (party_id, player_id))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()

def remove_from_party(party_id, player_id):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("DELETE FROM party_members WHERE party_id = ? AND player_id = ?",
                (party_id, player_id))
    conn.commit()
    conn.close()

# ================= БАН КАРТ =================
def get_banned_maps(lobby_id):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT banned_maps FROM lobbies WHERE id = ?", (lobby_id,))
    row = cur.fetchone()
    conn.close()
    if row and row[0]:
        return row[0].split(",") if row[0] else []
    return []

def ban_map(lobby_id, map_name):
    banned = get_banned_maps(lobby_id)
    banned.append(map_name)
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("UPDATE lobbies SET banned_maps = ? WHERE id = ?", (",".join(banned), lobby_id))
    conn.commit()
    conn.close()
    return banned

def get_remaining_maps(lobby_id, mode):
    banned = get_banned_maps(lobby_id)
    all_maps = MAPS_2v2 if mode == "2v2" else MAPS_5v5
    return [m for m in all_maps if m not in banned]

# ================= СОСТОЯНИЯ =================
class Reg(StatesGroup):
    waiting_game_id = State()
    waiting_nickname = State()

class PartyInvite(StatesGroup):
    waiting_game_id = State()

class CancelMatch(StatesGroup):
    waiting_reason = State()

class ResultInput(StatesGroup):
    waiting_score = State()
    waiting_screenshot = State()
    waiting_kda = State()

# ================= БОТ =================
logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# ================= КЛАВИАТУРЫ =================
def main_menu():
    kb = [
        [InlineKeyboardButton(text="👥 Создать пати", callback_data="party_create")],
        [InlineKeyboardButton(text="➕ Создать лобби", callback_data="create_lobby")],
        [InlineKeyboardButton(text="🔍 Найти игру", callback_data="find_game")],
        [InlineKeyboardButton(text="👤 Профиль", callback_data="profile"),
         InlineKeyboardButton(text="🏆 Топ", callback_data="top")],
        [InlineKeyboardButton(text="📜 История", callback_data="history"),
         InlineKeyboardButton(text="📖 Помощь", callback_data="help")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)

def party_menu(party_id, is_owner=False):
    kb = [
        [InlineKeyboardButton(text="📨 Пригласить по ID", callback_data=f"party_invite_{party_id}")],
        [InlineKeyboardButton(text="🎮 Играть", callback_data=f"party_play_{party_id}")],
    ]
    if is_owner:
        kb.append([InlineKeyboardButton(text="❌ Распустить", callback_data=f"party_disband_{party_id}")])
    else:
        kb.append([InlineKeyboardButton(text="🚪 Выйти", callback_data=f"party_leave_{party_id}")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

def invite_accept_menu(invite_id):
    kb = [
        [InlineKeyboardButton(text="✅ Принять", callback_data=f"inv_accept_{invite_id}")],
        [InlineKeyboardButton(text="❌ Отклонить", callback_data=f"inv_decline_{invite_id}")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)

def mode_menu(party_id=None):
    data_suffix = f"_{party_id}" if party_id else ""
    kb = [
        [InlineKeyboardButton(text="⚔️ 2 на 2", callback_data=f"mode_2v2{data_suffix}")],
        [InlineKeyboardButton(text="⚔️ 5 на 5", callback_data=f"mode_5v5{data_suffix}")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="back_main")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)

def ban_menu(lobby_id, mode):
    remaining = get_remaining_maps(lobby_id, mode)
    kb = []
    for m in remaining:
        kb.append([InlineKeyboardButton(text=f"🚫 {m}", callback_data=f"ban_{lobby_id}_{m}")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

def lobby_menu(lobby_id, is_owner=False):
    kb = [
        [InlineKeyboardButton(text="✅ Занять слот", callback_data=f"join_{lobby_id}")],
        [InlineKeyboardButton(text="🚪 Покинуть", callback_data=f"leave_{lobby_id}")],
    ]
    if is_owner:
        kb.append([InlineKeyboardButton(text="❌ Удалить лобби", callback_data=f"cancel_{lobby_id}")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

def ready_menu(lobby_id):
    kb = [[InlineKeyboardButton(text="✅ Я ГОТОВ", callback_data=f"ready_{lobby_id}")]]
    return InlineKeyboardMarkup(inline_keyboard=kb)

def captain_result_menu(lobby_id):
    kb = [
        [InlineKeyboardButton(text="📸 Загрузить скрин", callback_data=f"result_screenshot_{lobby_id}")],
        [InlineKeyboardButton(text="🤷 Забыл заскринить (-10 ELO)", callback_data=f"result_forgot_{lobby_id}")],
        [InlineKeyboardButton(text="❌ Отменить матч", callback_data=f"cancel_match_{lobby_id}")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)

# ================= ХЭНДЛЕРЫ =================
@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    player = get_player(message.from_user.id)
    if player:
        rank = get_rank(player[3])
        await message.answer(
            f"👋 С возвращением, <b>{player[2]}</b>!\n"
            f"📊 ELO: <b>{player[3]}</b> | {rank}\n"
            f"🔫 K/D/A: {player[4]}/{player[5]}/{player[6]}",
            reply_markup=main_menu(), parse_mode="HTML")
    else:
        await message.answer("🎮 Добро пожаловать в <b>Ranked</b>!\n\nВведи свой <b>игровой ID</b>:",
                             parse_mode="HTML")
        await state.set_state(Reg.waiting_game_id)

@dp.message(Reg.waiting_game_id)
async def reg_game_id(message: types.Message, state: FSMContext):
    gid = message.text.strip()
    if len(gid) < 3:
        await message.answer("❌ Слишком короткий:")
        return
    await state.update_data(game_id=gid)
    await message.answer("✅ ID принят. Теперь введи <b>никнейм</b>:", parse_mode="HTML")
    await state.set_state(Reg.waiting_nickname)

@dp.message(Reg.waiting_nickname)
async def reg_nick(message: types.Message, state: FSMContext):
    nick = message.text.strip()
    if len(nick) < 2:
        await message.answer("❌ Слишком короткий:")
        return
    data = await state.get_data()
    if register_player(message.from_user.id, data["game_id"], nick):
        await message.answer(
            f"🎉 Готово!\n👤 {nick}\n🆔 {data['game_id']}\n📊 ELO: 0\n🥉 Bronze",
            reply_markup=main_menu())
    else:
        await message.answer("❌ ID занят. Введи другой:")
        await state.set_state(Reg.waiting_game_id)
        return
    await state.clear()

@dp.callback_query(F.data == "back_main")
async def cb_back_main(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("🏠 Главное меню", reply_markup=main_menu())
    await callback.answer()

@dp.callback_query(F.data == "profile")
async def cb_profile(callback: types.CallbackQuery):
    p = get_player(callback.from_user.id)
    if not p:
        await callback.answer("Сначала /start", show_alert=True)
        return
    wr = round(p[7] / p[10] * 100, 1) if p[10] > 0 else 0
    kd = round(p[4] / p[5], 2) if p[5] > 0 else p[4]
    await callback.message.edit_text(
        f"👤 <b>Профиль</b>\n\n"
        f"🆔 <code>{p[1]}</code>\n"
        f"🏷 <b>{p[2]}</b>\n"
        f"{get_rank(p[3])}\n"
        f"📊 ELO: <b>{p[3]}</b>\n"
        f"🔫 K/D/A: {p[4]}/{p[5]}/{p[6]}\n"
        f"📈 K/D: {kd}\n"
        f"🏆 {p[7]} | 💀 {p[8]} | 🎮 {p[10]}\n"
        f"📊 Винрейт: {wr}%",
        reply_markup=main_menu(), parse_mode="HTML")
    await callback.answer()

@dp.callback_query(F.data == "top")
async def cb_top(callback: types.CallbackQuery):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT nickname, elo, kills, deaths FROM players ORDER BY elo DESC LIMIT 10")
    rows = cur.fetchall()
    conn.close()
    if not rows:
        await callback.answer("Пусто", show_alert=True)
        return
    text = "🏆 <b>Топ-10</b>\n\n"
    for i, (n, e, k, d) in enumerate(rows, 1):
        medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"{i}."
        text += f"{medal} <b>{n}</b> — {e} {get_rank(e)} ({k}/{d})\n"
    await callback.message.edit_text(text, reply_markup=main_menu(), parse_mode="HTML")
    await callback.answer()

@dp.callback_query(F.data == "history")
async def cb_history(callback: types.CallbackQuery):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT lobby_code, mode, map, score FROM match_history ORDER BY id DESC LIMIT 10")
    rows = cur.fetchall()
    conn.close()
    if not rows:
        await callback.answer("Матчей не было", show_alert=True)
        return
    text = "📜 <b>Последние матчи</b>\n\n"
    for code, mode, mp, score in rows:
        text += f"🎮 {mode} • 🗺 {mp} • {score} • <code>{code}</code>\n"
    await callback.message.edit_text(text, reply_markup=main_menu(), parse_mode="HTML")
    await callback.answer()

@dp.callback_query(F.data == "help")
async def cb_help(callback: types.CallbackQuery):
    await callback.message.edit_text(
        "📖 <b>Помощь</b>\n\n"
        "👥 <b>Пати</b> — собери друзей. Приглашай по ID.\n"
        "➕ <b>Лобби</b> — для одиночной игры.\n"
        "🔍 <b>Найти игру</b> — открытые лобби.\n"
        "👤 <b>Профиль</b> — ELO, K/D/A.\n\n"
        "Капитан = игрок с наибольшим ELO.\n"
        "Бан карт: капитаны банят по очереди.\n\n"
        "Когда все зашли — 20 сек на подготовку, потом 30 сек на Я ГОТОВ.\n\n"
        "После матча капитан грузит скрин + K/D/A.\n"
        "Забыл скрин — −10 ELO.",
        reply_markup=main_menu(), parse_mode="HTML")
    await callback.answer()

# ================ ПАТИ ================
@dp.callback_query(F.data == "party_create")
async def cb_party_create(callback: types.CallbackQuery):
    p = get_player(callback.from_user.id)
    if not p:
        await callback.answer("Сначала /start", show_alert=True)
        return
    if get_player_party(callback.from_user.id):
        await callback.answer("Ты уже в пати!", show_alert=True)
        return
    party_id = create_party(callback.from_user.id, callback.message.message_id, callback.message.chat.id)
    await refresh_party_message(party_id)
    await callback.answer()

async def refresh_party_message(party_id):
    party = get_party(party_id)
    if not party:
        return
    members = get_party_members(party_id)
    owner_id = party[1]
    text = f"👥 <b>Пати</b>\n\n"
    text += f"Участники ({len(members)}/5):\n"
    for m in members:
        cap = " 👑" if m[0] == owner_id else ""
        text += f"  • {m[1]} ({m[2]} ELO){cap}\n"
    owner = get_player(owner_id)
    text += f"\n👑 Хост: {owner[2] if owner else '?'}"
    try:
        await bot.edit_message_text(chat_id=party[3], message_id=party[2],
            text=text, reply_markup=party_menu(party_id, is_owner=(owner_id == party[1])), parse_mode="HTML")
    except Exception as e:
        print(f"Party edit failed: {e}")
        try:
            await bot.send_message(party[3], text,
                reply_markup=party_menu(party_id, is_owner=(owner_id == party[1])), parse_mode="HTML")
        except:
            pass

@dp.callback_query(F.data.startswith("party_invite_"))
async def cb_party_invite(callback: types.CallbackQuery, state: FSMContext):
    party_id = int(callback.data.split("_")[2])
    party = get_party(party_id)
    if not party or party[1] != callback.from_user.id:
        await callback.answer("Только хост", show_alert=True)
        return
    await callback.message.answer("📨 Введи <b>игровой ID</b> того, кого хочешь пригласить:", parse_mode="HTML")
    await state.update_data(party_id=party_id)
    await state.set_state(PartyInvite.waiting_game_id)
    await callback.answer()

@dp.message(PartyInvite.waiting_game_id)
async def process_party_invite(message: types.Message, state: FSMContext):
    data = await state.get_data()
    party_id = data["party_id"]
    gid = message.text.strip()
    target = get_player_by_game_id(gid)
    if not target:
        await message.answer("❌ Игрок не найден")
        return
    if target[0] == message.from_user.id:
        await message.answer("❌ Нельзя себя")
        return
    if get_player_party(target[0]):
        await message.answer("❌ Уже в пати")
        return
    members = get_party_members(party_id)
    if len(members) >= 5:
        await message.answer("❌ Пати заполнено")
        return
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("INSERT INTO party_invites (party_id, inviter_id, invitee_id) VALUES (?, ?, ?)",
                (party_id, message.from_user.id, target[0]))
    invite_id = cur.lastrowid
    conn.commit()
    conn.close()
    inviter = get_player(message.from_user.id)
    try:
        await bot.send_message(target[0],
            f"📨 <b>{inviter[2]}</b> приглашает тебя в пати!",
            reply_markup=invite_accept_menu(invite_id), parse_mode="HTML")
        await message.answer(f"✅ Отправлено <b>{target[2]}</b>", parse_mode="HTML")
    except:
        await message.answer("❌ Не удалось")
    await state.clear()

@dp.callback_query(F.data.startswith("inv_accept_"))
async def cb_inv_accept(callback: types.CallbackQuery):
    invite_id = int(callback.data.split("_")[2])
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT * FROM party_invites WHERE id = ?", (invite_id,))
    inv = cur.fetchone()
    conn.close()
    if not inv or inv[4] != 'pending':
        await callback.answer("Неактивно", show_alert=True)
        return
    if add_to_party(inv[1], callback.from_user.id):
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("UPDATE party_invites SET status='accepted' WHERE id=?", (invite_id,))
        conn.commit()
        conn.close()
        await callback.message.edit_text("✅ Ты в пати!")
        await refresh_party_message(inv[1])
    await callback.answer()

@dp.callback_query(F.data.startswith("inv_decline_"))
async def cb_inv_decline(callback: types.CallbackQuery):
    invite_id = int(callback.data.split("_")[2])
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("UPDATE party_invites SET status='declined' WHERE id=?", (invite_id,))
    conn.commit()
    conn.close()
    await callback.message.edit_text("❌ Отклонено.")
    await callback.answer()

@dp.callback_query(F.data.startswith("party_join_"))
async def cb_party_join(callback: types.CallbackQuery):
    party_id = int(callback.data.split("_")[2])
    p = get_player(callback.from_user.id)
    if not p:
        await callback.answer("Сначала /start", show_alert=True)
        return
    if add_to_party(party_id, callback.from_user.id):
        await callback.answer("✅ Ты в пати!")
        await refresh_party_message(party_id)
    else:
        await callback.answer("Уже в пати")

@dp.callback_query(F.data.startswith("party_play_"))
async def cb_party_play(callback: types.CallbackQuery):
    party_id = int(callback.data.split("_")[2])
    party = get_party(party_id)
    if not party or party[1] != callback.from_user.id:
        await callback.answer("Только хост", show_alert=True)
        return
    members = get_party_members(party_id)
    if len(members) < 2:
        await callback.answer("Минимум 2", show_alert=True)
        return
    await callback.message.edit_text(f"🎯 Режим ({len(members)} чел):", reply_markup=mode_menu(party_id))
    await callback.answer()

@dp.callback_query(F.data.startswith("party_leave_"))
async def cb_party_leave(callback: types.CallbackQuery):
    party_id = int(callback.data.split("_")[2])
    remove_from_party(party_id, callback.from_user.id)
    await callback.message.edit_text("🚪 Вышел.", reply_markup=main_menu())
    await refresh_party_message(party_id)
    await callback.answer()

@dp.callback_query(F.data.startswith("party_disband_"))
async def cb_party_disband(callback: types.CallbackQuery):
    party_id = int(callback.data.split("_")[2])
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("UPDATE parties SET status='disbanded' WHERE id=?", (party_id,))
    cur.execute("DELETE FROM party_members WHERE party_id=?", (party_id,))
    conn.commit()
    conn.close()
    await callback.message.edit_text("❌ Распущено.", reply_markup=main_menu())
    await callback.answer()

# ================ ЛОББИ ================
@dp.callback_query(F.data == "create_lobby")
async def cb_create_lobby(callback: types.CallbackQuery):
    p = get_player(callback.from_user.id)
    if not p:
        await callback.answer("Сначала /start", show_alert=True)
        return
    if get_player_party(callback.from_user.id):
        await callback.answer("Выйди из пати", show_alert=True)
        return
    await callback.message.edit_text("🎯 Режим:", reply_markup=mode_menu())
    await callback.answer()

@dp.callback_query(F.data.startswith("mode_"))
async def cb_mode(callback: types.CallbackQuery):
    parts = callback.data.split("_")
    mode = parts[1]
    party_id = int(parts[2]) if len(parts) > 2 else None
    if party_id:
        party = get_party(party_id)
        if party:
            members = get_party_members(party_id)
            await create_lobby_from_party(callback, mode, party, members)
            return
    await create_lobby_single(callback, mode)
    await callback.answer()

async def create_lobby_single(callback, mode):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    code = None
    for _ in range(20):
        c = str(random.randint(1000, 9999))
        cur.execute("SELECT id FROM lobbies WHERE code = ? AND status = 'banning'", (c,))
        if not cur.fetchone():
            code = c
            break
    if not code:
        await callback.answer("Ошибка", show_alert=True)
        conn.close()
        return
    cur.execute("""INSERT INTO lobbies (code, owner_id, mode, status, message_id, chat_id)
                   VALUES (?, ?, ?, 'banning', ?, ?)""",
                (code, callback.from_user.id, mode, callback.message.message_id, callback.message.chat.id))
    lobby_id = cur.lastrowid
    cur.execute("INSERT INTO lobby_players (lobby_id, player_id, team) VALUES (?, ?, 1)",
                (lobby_id, callback.from_user.id))
    conn.commit()
    conn.close()
    await refresh_lobby_message(lobby_id)

async def create_lobby_from_party(callback, mode, party, members):
    max_players = 4 if mode == "2v2" else 10
    if len(members) > max_players:
        await callback.answer(f"Много для {mode}", show_alert=True)
        return
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    code = str(random.randint(1000, 9999))
    cur.execute("""INSERT INTO lobbies (code, owner_id, mode, status, message_id, chat_id)
                   VALUES (?, ?, ?, 'banning', ?, ?)""",
                (code, party[1], mode, callback.message.message_id, callback.message.chat.id))
    lobby_id = cur.lastrowid
    team_switch = 1
    for m in members:
        cur.execute("INSERT INTO lobby_players (lobby_id, player_id, team) VALUES (?, ?, ?)",
                    (lobby_id, m[0], team_switch))
        team_switch = 2 if team_switch == 1 else 1
    conn.commit()
    conn.close()
    await refresh_lobby_message(lobby_id)

@dp.callback_query(F.data.startswith("join_"))
async def cb_join(callback: types.CallbackQuery):
    lobby_id = int(callback.data.split("_")[1])
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT code, mode, status FROM lobbies WHERE id = ?", (lobby_id,))
    row = cur.fetchone()
    if not row:
        await callback.answer("Не найдено", show_alert=True)
        conn.close()
        return
    if row[2] != 'banning':
        await callback.answer("Уже не в наборе", show_alert=True)
        conn.close()
        return
    p = get_player(callback.from_user.id)
    if not p:
        await callback.answer("Сначала /start", show_alert=True)
        conn.close()
        return
    max_players = 4 if row[1] == "2v2" else 10
    cur.execute("SELECT COUNT(*) FROM lobby_players WHERE lobby_id = ?", (lobby_id,))
    if cur.fetchone()[0] >= max_players:
        await callback.answer("Заполнено", show_alert=True)
        conn.close()
        return
    cur.execute("SELECT team FROM lobby_players WHERE lobby_id = ?", (lobby_id,))
    teams = [t[0] for t in cur.fetchall()]
    new_team = 1 if teams.count(1) <= teams.count(2) else 2
    cur.execute("INSERT OR IGNORE INTO lobby_players (lobby_id, player_id, team) VALUES (?, ?, ?)",
                (lobby_id, callback.from_user.id, new_team))
    conn.commit()
    conn.close()
    await refresh_lobby_message(lobby_id)
    await callback.answer("✅ В лобби!")

# ================ ИСПРАВЛЕННАЯ ФУНКЦИЯ ОБНОВЛЕНИЯ ЛОББИ ================
async def refresh_lobby_message(lobby_id):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT code, mode, status, message_id, chat_id, owner_id, banned_maps, final_map FROM lobbies WHERE id = ?", (lobby_id,))
    row = cur.fetchone()
    if not row:
        conn.close()
        return
    code, mode, status, message_id, chat_id, owner_id, banned_maps, final_map = row
    cur.execute("""SELECT p.telegram_id, p.nickname, p.elo, lp.team
                   FROM players p JOIN lobby_players lp ON p.telegram_id = lp.player_id
                   WHERE lp.lobby_id = ? ORDER BY lp.team, p.elo DESC""", (lobby_id,))
    players = cur.fetchall()
    conn.close()

    max_players = 4 if mode == "2v2" else 10
    count = len(players)
    mode_label = "2×2" if mode == "2v2" else "5×5"

    text = f"🎮 <b>Лобби {code}</b>\n🎯 {mode_label} • 👥 {count}/{max_players}\n\n"
    team1 = [p for p in players if p[3] == 1]
    team2 = [p for p in players if p[3] == 2]
    text += "🔵 <b>Команда 1</b>\n"
    for p in team1:
        text += f"  • {p[1]} ({p[2]} ELO)\n"
    if team2:
        text += "\n🔴 <b>Команда 2</b>\n"
        for p in team2:
            text += f"  • {p[1]} ({p[2]} ELO)\n"
    if banned_maps:
        text += f"\n🚫 {banned_maps}\n"

    kb = None
    if count < max_players:
        kb = lobby_menu(lobby_id, is_owner=(owner_id == (players[0][0] if players else 0)))
        text += f"\n⏳ Ждём... /join {code}"
    else:
        text += f"\n✅ Все на месте!"

    # Пробуем обновить старое
    edited = False
    try:
        await bot.edit_message_text(chat_id=chat_id, message_id=message_id,
            text=text, reply_markup=kb, parse_mode="HTML")
        edited = True
    except Exception as e:
        print(f"[lobby {lobby_id}] edit failed: {e}")

    # Если не получилось — шлём всем игрокам новое
    if not edited:
        for p in players:
            try:
                await bot.send_message(p[0], text, reply_markup=kb, parse_mode="HTML")
            except Exception as e:
                print(f"[lobby {lobby_id}] send to {p[0]} failed: {e}")

    if count >= max_players and status == 'banning':
        await start_ban_phase_ui(lobby_id)

# ================ БАН КАРТ ================
async def start_ban_phase_ui(lobby_id):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT mode FROM lobbies WHERE id = ?", (lobby_id,))
    row = cur.fetchone()
    if not row:
        conn.close()
        return
    mode = row[0]
    cur.execute("""SELECT lp.player_id, lp.team, p.elo
                   FROM lobby_players lp JOIN players p ON lp.player_id=p.telegram_id
                   WHERE lp.lobby_id=? ORDER BY lp.team, p.elo DESC""", (lobby_id,))
    players = cur.fetchall()
    conn.close()
    team1 = [p for p in players if p[1] == 1]
    team2 = [p for p in players if p[1] == 2]
    cap1 = team1[0][0] if team1 else None
    cap2 = team2[0][0] if team2 else None
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("UPDATE lobby_players SET captain=0 WHERE lobby_id=?", (lobby_id,))
    if cap1:
        cur.execute("UPDATE lobby_players SET captain=1 WHERE lobby_id=? AND player_id=?", (lobby_id, cap1))
    if cap2:
        cur.execute("UPDATE lobby_players SET captain=1 WHERE lobby_id=? AND player_id=?", (lobby_id, cap2))
    conn.commit()
    conn.close()
    remaining = get_remaining_maps(lobby_id, mode)
    for cap in [cap1, cap2]:
        if not cap:
            continue
        try:
            await bot.send_message(cap,
                f"🎯 <b>Фаза бана</b>\nОсталось: {len(remaining)}",
                reply_markup=ban_menu(lobby_id, mode), parse_mode="HTML")
        except:
            pass

@dp.callback_query(F.data.startswith("ban_"))
async def cb_ban(callback: types.CallbackQuery):
    parts = callback.data.split("_")
    lobby_id = int(parts[1])
    map_name = parts[2]
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT mode, status FROM lobbies WHERE id = ?", (lobby_id,))
    row = cur.fetchone()
    if not row or row[1] != 'banning':
        await callback.answer("Фаза завершена", show_alert=True)
        conn.close()
        return
    mode = row[0]
    ban_map(lobby_id, map_name)
    remaining = get_remaining_maps(lobby_id, mode)
    conn.close()
    await callback.message.edit_text(f"🚫 {map_name}\nОсталось: {len(remaining)}", parse_mode="HTML")
    if len(remaining) == 1:
        await start_ready_phase(lobby_id, remaining[0])
    else:
        await send_ban_to_next_captain(lobby_id, mode)

async def send_ban_to_next_captain(lobby_id, mode):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT player_id FROM lobby_players WHERE lobby_id=? AND captain=1", (lobby_id,))
    caps = cur.fetchall()
    conn.close()
    remaining = get_remaining_maps(lobby_id, mode)
    for cap in caps:
        try:
            await bot.send_message(cap[0],
                f"🎯 Твой ход. Осталось: {len(remaining)}",
                reply_markup=ban_menu(lobby_id, mode), parse_mode="HTML")
        except:
            pass

# ================ ГОТОВНОСТЬ ================
async def start_ready_phase(lobby_id, final_map):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("UPDATE lobbies SET final_map=? WHERE id=?", (final_map, lobby_id))
    cur.execute("UPDATE lobby_players SET ready=0 WHERE lobby_id=?", (lobby_id,))
    cur.execute("""SELECT p.telegram_id, p.nickname, lp.team
                   FROM players p JOIN lobby_players lp ON p.telegram_id = lp.player_id
                   WHERE lp.lobby_id = ?""", (lobby_id,))
    players = cur.fetchall()
    conn.commit()
    conn.close()

    for p in players:
        try:
            await bot.send_message(p[0],
                f"⏳ <b>20 секунд</b> на подготовку!\n🗺 Карта: <b>{final_map}</b>",
                parse_mode="HTML")
        except:
            pass
    await asyncio.sleep(20)
    for p in players:
        try:
            await bot.send_message(p[0],
                f"✅ <b>Нажми Я ГОТОВ</b> (30 секунд)!",
                reply_markup=ready_menu(lobby_id), parse_mode="HTML")
        except:
            pass
    await asyncio.sleep(30)
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT player_id FROM lobby_players WHERE lobby_id=? AND ready=1", (lobby_id,))
    ready = [r[0] for r in cur.fetchall()]
    conn.close()
    if len(ready) == len(players):
        await start_match(lobby_id, final_map)
    else:
        not_ready = [p for p in players if p[0] not in ready]
        names = ", ".join([n[1] for n in not_ready])
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("UPDATE lobbies SET status='cancelled', cancel_reason=? WHERE id=?",
                    (f"Не готовы: {names}", lobby_id))
        conn.commit()
        conn.close()
        for p in players:
            try:
                await bot.send_message(p[0], f"❌ Матч отменён. Не готовы: {names}", parse_mode="HTML")
            except:
                pass

@dp.callback_query(F.data.startswith("ready_"))
async def cb_ready(callback: types.CallbackQuery):
    lobby_id = int(callback.data.split("_")[1])
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("UPDATE lobby_players SET ready=1 WHERE lobby_id=? AND player_id=?",
                (lobby_id, callback.from_user.id))
    conn.commit()
    cur.execute("SELECT COUNT(*) FROM lobby_players WHERE lobby_id=? AND ready=1", (lobby_id,))
    rc = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM lobby_players WHERE lobby_id=?", (lobby_id,))
    total = cur.fetchone()[0]
    conn.close()
    await callback.message.edit_text(f"✅ Готов! ({rc}/{total})")
    await callback.answer()

# ================ МАТЧ ================
async def start_match(lobby_id, final_map):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT code, mode FROM lobbies WHERE id=?", (lobby_id,))
    row = cur.fetchone()
    if not row:
        conn.close()
        return
    code, mode = row
    cur.execute("UPDATE lobbies SET status='playing' WHERE id=?", (lobby_id,))
    cur.execute("""SELECT p.telegram_id, p.nickname, p.elo, lp.team
                   FROM players p JOIN lobby_players lp ON p.telegram_id = lp.player_id
                   WHERE lp.lobby_id = ? ORDER BY lp.team DESC, p.elo DESC""", (lobby_id,))
    players = cur.fetchall()
    conn.commit()
    conn.close()
    team1 = [p for p in players if p[3] == 1]
    team2 = [p for p in players if p[3] == 2]
    text = f"🎮 <b>МАТЧ НАЧАЛСЯ!</b>\n\n🔑 <code>{code}</code>\n🎯 {mode} • 🗺 <b>{final_map}</b>\n\n"
    text += "🔵 <b>Команда 1</b>\n"
    for p in team1:
        text += f"  • {p[1]} ({p[2]} ELO)\n"
    text += "\n🔴 <b>Команда 2</b>\n"
    for p in team2:
        text += f"  • {p[1]} ({p[2]} ELO)\n"
    text += f"\n🏁 /result {code} <счёт>"
    for p in players:
        try:
            await bot.send_message(p[0], text, parse_mode="HTML")
        except:
            pass
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT player_id FROM lobby_players WHERE lobby_id=? AND captain=1", (lobby_id,))
    caps = cur.fetchall()
    conn.close()
    for cap in caps:
        try:
            await bot.send_message(cap[0],
                f"👑 Ты капитан. После матча:",
                reply_markup=captain_result_menu(lobby_id), parse_mode="HTML")
        except:
            pass

# ================ ОТМЕНА ================
@dp.callback_query(F.data.startswith("cancel_match_"))
async def cb_cancel_match(callback: types.CallbackQuery, state: FSMContext):
    lobby_id = int(callback.data.split("_")[2])
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT captain FROM lobby_players WHERE lobby_id=? AND player_id=?",
                (lobby_id, callback.from_user.id))
    row = cur.fetchone()
    conn.close()
    if not row or not row[0]:
        await callback.answer("Только капитан", show_alert=True)
        return
    await callback.message.answer("📝 Причина отмены:")
    await state.update_data(cancel_lobby=lobby_id)
    await state.set_state(CancelMatch.waiting_reason)
    await callback.answer()

@dp.message(CancelMatch.waiting_reason)
async def process_cancel_reason(message: types.Message, state: FSMContext):
    data = await state.get_data()
    lobby_id = data["cancel_lobby"]
    reason = message.text.strip()
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("UPDATE lobbies SET status='cancelled', cancel_reason=? WHERE id=?", (reason, lobby_id))
    cur.execute("""SELECT p.telegram_id FROM players p
                   JOIN lobby_players lp ON p.telegram_id = lp.player_id
                   WHERE lp.lobby_id=?""", (lobby_id,))
    players = cur.fetchall()
    conn.commit()
    conn.close()
    for p in players:
        try:
            await bot.send_message(p[0], f"❌ <b>Матч отменён</b>\n📝 Причина: {reason}", parse_mode="HTML")
        except:
            pass
    await message.answer("✅ Отменено.")
    await state.clear()

# ================ РЕЗУЛЬТАТ ================
@dp.callback_query(F.data.startswith("result_screenshot_"))
async def cb_result_screenshot(callback: types.CallbackQuery, state: FSMContext):
    lobby_id = int(callback.data.split("_")[2])
    await callback.message.answer("📸 Загрузи скрин результатов (одним фото):")
    await state.update_data(lobby_id=lobby_id, forgot=0)
    await state.set_state(ResultInput.waiting_screenshot)
    await callback.answer()

@dp.callback_query(F.data.startswith("result_forgot_"))
async def cb_result_forgot(callback: types.CallbackQuery, state: FSMContext):
    lobby_id = int(callback.data.split("_")[2])
    await callback.message.answer("🤷 Без скрина, <b>−10 ELO</b>.\n\nСчёт в формате <code>10-7</code>:", parse_mode="HTML")
    await state.update_data(lobby_id=lobby_id, forgot=1)
    await state.set_state(ResultInput.waiting_score)
    await callback.answer()

@dp.message(ResultInput.waiting_screenshot)
async def process_screenshot(message: types.Message, state: FSMContext):
    if not message.photo:
        await message.answer("❌ Отправь фото")
        return
    file_id = message.photo[-1].file_id
    await state.update_data(screenshot=file_id)
    await message.answer("✅ Скрин сохранён.\nСчёт <code>10-7</code>:", parse_mode="HTML")
    await state.set_state(ResultInput.waiting_score)

@dp.message(ResultInput.waiting_score)
async def process_score(message: types.Message, state: FSMContext):
    data = await state.get_data()
    lobby_id = data["lobby_id"]
    score = message.text.strip()
    if "-" not in score:
        await message.answer("❌ Формат: 10-7")
        return
    try:
        s1, s2 = map(int, score.split("-"))
    except:
        await message.answer("❌ Неверный формат")
        return
    await state.update_data(score=score, s1=s1, s2=s2)
    await message.answer(
        "✅ Счёт принят.\n\nK/D/A каждого игрока (ник kills deaths assists) — с новой строки:\n"
        "<code>Player1 15 8 3\nPlayer2 10 12 5</code>", parse_mode="HTML")
    await state.set_state(ResultInput.waiting_kda)

@dp.message(ResultInput.waiting_kda)
async def process_kda(message: types.Message, state: FSMContext):
    data = await state.get_data()
    lobby_id = data["lobby_id"]
    score = data["score"]
    s1 = data["s1"]
    s2 = data["s2"]
    forgot = data.get("forgot", 0)
    screenshot = data.get("screenshot", None)
    lines = message.text.strip().split("\n")
    kda_data = {}
    for line in lines:
        parts = line.strip().split()
        if len(parts) == 4:
            try:
                kda_data[parts[0].lower()] = (int(parts[1]), int(parts[2]), int(parts[3]))
            except:
                pass
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT code, mode, final_map FROM lobbies WHERE id=?", (lobby_id,))
    row = cur.fetchone()
    if not row:
        conn.close()
        await message.answer("❌ Лобби не найдено")
        return
    code, mode, final_map = row
    cur.execute("""SELECT p.telegram_id, p.nickname, p.elo, lp.team
                   FROM players p JOIN lobby_players lp ON p.telegram_id = lp.player_id
                   WHERE lp.lobby_id = ?""", (lobby_id,))
    players = cur.fetchall()
    winner_team = 1 if s1 > s2 else 2
    K = 32
    for p in players:
        tg_id, nick, elo, team = p
        kda = kda_data.get(nick.lower(), (0, 0, 0))
        kills, deaths, assists = kda
        opp = [x for x in players if x[3] != team]
        opp_avg = sum(x[2] for x in opp) / len(opp) if opp else 0
        expected = 1 / (1 + 10 ** ((opp_avg - elo) / 400))
        actual = 1 if team == winner_team else 0
        kda_bonus = (kills + assists / 2 - deaths) / 10
        new_elo = max(0, int(elo + K * (actual - expected) + kda_bonus))
        if forgot and tg_id == message.from_user.id:
            new_elo = max(0, new_elo - 10)
        update_stats(tg_id, new_elo, won=(team == winner_team),
                     kills=kills, deaths=deaths, assists=assists)
        cur.execute("""UPDATE lobby_players SET kills=?, deaths=?, assists=?,
                       screenshot=?, forgot_screenshot=?
                       WHERE lobby_id=? AND player_id=?""",
                    (kills, deaths, assists, screenshot, forgot, lobby_id, tg_id))
        try:
            await bot.send_message(tg_id,
                f"📊 Матч <code>{code}</code>\n🎯 {score} • 🗺 {final_map}\n"
                f"🔫 K/D/A: {kills}/{deaths}/{assists}\n"
                f"📈 ELO: <b>{new_elo}</b>\n{get_rank(new_elo)}",
                parse_mode="HTML")
        except:
            pass
    cur.execute("UPDATE lobbies SET status='finished', score=? WHERE id=?", (score, lobby_id))
    cur.execute("""INSERT INTO match_history (lobby_code, mode, map, score, winner_team)
                   VALUES (?, ?, ?, ?, ?)""", (code, mode, final_map, score, winner_team))
    conn.commit()
    conn.close()
    await message.answer(f"✅ Записано: {score}\nПобедила команда {winner_team}")
    await state.clear()

# ================ ПОИСК ================
@dp.callback_query(F.data == "find_game")
async def cb_find(callback: types.CallbackQuery):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""SELECT id, code, mode, 
                   (SELECT COUNT(*) FROM lobby_players WHERE lobby_id = lobbies.id)
                   FROM lobbies WHERE status='banning' ORDER BY created_at DESC LIMIT 10""")
    rows = cur.fetchall()
    conn.close()
    if not rows:
        await callback.answer("Нет открытых", show_alert=True)
        return
    kb = []
    for lid, code, mode, cnt in rows:
        maxp = 4 if mode == "2v2" else 10
        kb.append([InlineKeyboardButton(text=f"{mode} • {cnt}/{maxp} | {code}",
                                        callback_data=f"join_{lid}")])
    kb.append([InlineKeyboardButton(text="◀️ Назад", callback_data="back_main")])
    await callback.message.edit_text("🔍 <b>Открытые:</b>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="HTML")
    await callback.answer()

# ================ ВЫХОД ================
@dp.callback_query(F.data.startswith("leave_"))
async def cb_leave(callback: types.CallbackQuery):
    lobby_id = int(callback.data.split("_")[1])
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("DELETE FROM lobby_players WHERE lobby_id = ? AND player_id = ?",
                (lobby_id, callback.from_user.id))
    conn.commit()
    conn.close()
    await callback.message.edit_text("🚪 Покинул.", reply_markup=main_menu())
    await refresh_lobby_message(lobby_id)
    await callback.answer()

@dp.callback_query(F.data.startswith("cancel_"))
async def cb_cancel(callback: types.CallbackQuery):
    lobby_id = int(callback.data.split("_")[1])
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("UPDATE lobbies SET status='cancelled' WHERE id=?", (lobby_id,))
    conn.commit()
    conn.close()
    await callback.message.edit_text("❌ Удалено.", reply_markup=main_menu())
    await callback.answer()

# ================ ЗАПУСК ================
async def main():
    init_db()
    print("🤖 Ranked бот запущен...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())