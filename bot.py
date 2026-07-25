import asyncio
import logging
import os
import re
import sqlite3
from datetime import datetime

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    Message, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton,
)

logging.basicConfig(level=logging.INFO)

# ============ SOZLAMALAR ============
BOT_TOKEN = os.getenv("BOT_TOKEN")

# Bosh admin (bu ID hech qachon adminlikdan chiqarilmaydi va yagona
# admin qo'sha/o'chira oladigan shaxs). ID ni bilish uchun @userinfobot ga /start bosing
OWNER_ID = 8012700729
# =====================================

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

DB_PATH = os.getenv("DB_PATH", "kino_bot.db")


# ---------------- DATABASE ----------------
def db_init():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        first_name TEXT,
        username TEXT,
        joined_at TEXT
    )""")
    cur.execute("""CREATE TABLE IF NOT EXISTS movies (
        code TEXT PRIMARY KEY,
        file_id TEXT,
        title TEXT
    )""")
    cur.execute("""CREATE TABLE IF NOT EXISTS series (
        code TEXT PRIMARY KEY,
        title TEXT
    )""")
    cur.execute("""CREATE TABLE IF NOT EXISTS episodes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        series_code TEXT,
        season_number INTEGER DEFAULT 1,
        episode_number INTEGER,
        file_id TEXT
    )""")
    try:
        cur.execute("ALTER TABLE episodes ADD COLUMN season_number INTEGER DEFAULT 1")
    except sqlite3.OperationalError:
        pass  # ustun eski bazada allaqachon mavjud bo'lishi mumkin
    try:
        cur.execute("DROP INDEX IF EXISTS idx_episodes_unique")
        cur.execute("""CREATE UNIQUE INDEX IF NOT EXISTS idx_episodes_unique_season
            ON episodes(series_code, season_number, episode_number)""")
    except sqlite3.OperationalError:
        pass  # eski dublikat ma'lumotlar bo'lsa, indexsiz davom etadi
    cur.execute("""CREATE TABLE IF NOT EXISTS channels (
        chat_id TEXT PRIMARY KEY,
        title TEXT
    )""")
    cur.execute("""CREATE TABLE IF NOT EXISTS admins (
        user_id INTEGER PRIMARY KEY,
        added_at TEXT
    )""")
    conn.commit()
    conn.close()


def db_run(query, params=()):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(query, params)
    conn.commit()
    result = cur.fetchall()
    conn.close()
    return result


def add_user(user_id, first_name, username):
    db_run(
        "INSERT OR IGNORE INTO users (user_id, first_name, username, joined_at) VALUES (?, ?, ?, ?)",
        (user_id, first_name, username, datetime.now().isoformat()),
    )


def get_all_user_ids():
    rows = db_run("SELECT user_id FROM users")
    return [r[0] for r in rows]


def get_user_count():
    return db_run("SELECT COUNT(*) FROM users")[0][0]


def add_movie(code, file_id, title):
    db_run("INSERT OR REPLACE INTO movies (code, file_id, title) VALUES (?, ?, ?)", (code, file_id, title))


def get_movie(code):
    rows = db_run("SELECT code, file_id, title FROM movies WHERE code=?", (code,))
    return rows[0] if rows else None


def delete_movie(code):
    db_run("DELETE FROM movies WHERE code=?", (code,))


def get_all_movies():
    return db_run("SELECT code, title FROM movies")


def normalize_text(s: str) -> str:
    """O'zbekcha apostrof variantlari (', ʻ, ʼ, ', `) va katta/kichik harf
    farqini bir xillashtiradi, shunda qidiruv har qanday yozilishda ishlaydi."""
    if not s:
        return ""
    s = s.casefold()
    s = re.sub(r"[\'\u02bb\u02bc\u2018\u2019`´]", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def search_movies_by_title(query, limit=10):
    nq = normalize_text(query)
    if not nq:
        return []
    rows = db_run("SELECT code, title FROM movies")
    matched = [(code, title) for code, title in rows if nq in normalize_text(title)]
    return matched[:limit]


def add_channel(chat_id, title):
    db_run("INSERT OR REPLACE INTO channels (chat_id, title) VALUES (?, ?)", (chat_id, title))


def delete_channel(chat_id):
    db_run("DELETE FROM channels WHERE chat_id=?", (chat_id,))


def get_all_channels():
    return db_run("SELECT chat_id, title FROM channels")


# ---------------- SERIALLAR ----------------
def add_series(code, title):
    db_run("INSERT OR REPLACE INTO series (code, title) VALUES (?, ?)", (code, title))


def get_series(code):
    rows = db_run("SELECT code, title FROM series WHERE code=?", (code,))
    return rows[0] if rows else None


def delete_series(code):
    db_run("DELETE FROM series WHERE code=?", (code,))
    db_run("DELETE FROM episodes WHERE series_code=?", (code,))


def get_all_series():
    return db_run("SELECT code, title FROM series")


def search_series_by_title(query, limit=10):
    nq = normalize_text(query)
    if not nq:
        return []
    rows = db_run("SELECT code, title FROM series")
    matched = [(code, title) for code, title in rows if nq in normalize_text(title)]
    return matched[:limit]


def add_episode(series_code, season_number, episode_number, file_id):
    db_run(
        """INSERT INTO episodes (series_code, season_number, episode_number, file_id) VALUES (?, ?, ?, ?)
           ON CONFLICT(series_code, season_number, episode_number) DO UPDATE SET file_id=excluded.file_id""",
        (series_code, season_number, episode_number, file_id),
    )


def get_seasons(series_code):
    rows = db_run(
        "SELECT DISTINCT season_number FROM episodes WHERE series_code=? ORDER BY season_number",
        (series_code,),
    )
    return [r[0] for r in rows]


def get_episodes(series_code, season_number=None):
    if season_number is None:
        return db_run(
            "SELECT season_number, episode_number, file_id FROM episodes WHERE series_code=? "
            "ORDER BY season_number, episode_number",
            (series_code,),
        )
    return db_run(
        "SELECT episode_number, file_id FROM episodes WHERE series_code=? AND season_number=? "
        "ORDER BY episode_number",
        (series_code, season_number),
    )


def get_episode_count(series_code, season_number=None):
    return len(get_episodes(series_code, season_number))


def get_last_episode_number(series_code, season_number):
    rows = db_run(
        "SELECT MAX(episode_number) FROM episodes WHERE series_code=? AND season_number=?",
        (series_code, season_number),
    )
    return rows[0][0] or 0


def delete_episode(series_code, season_number, episode_number):
    db_run(
        "DELETE FROM episodes WHERE series_code=? AND season_number=? AND episode_number=?",
        (series_code, season_number, episode_number),
    )


def delete_season(series_code, season_number):
    db_run(
        "DELETE FROM episodes WHERE series_code=? AND season_number=?",
        (series_code, season_number),
    )


def parse_episode_number_from_filename(filename):
    """Fayl nomidan raqamni topadi (masalan '3-qism.mp4' -> 3). Topilmasa None.
    Kengaytma (.mp4, .mkv va h.k.) ichidagi raqamlarga chalg'imaslik uchun
    avval kengaytma olib tashlanadi."""
    if not filename:
        return None
    name_without_ext = re.sub(r"\.[a-zA-Z0-9]{2,5}$", "", filename)
    match = re.search(r"(\d+)", name_without_ext)
    return int(match.group(1)) if match else None


def add_admin(user_id):
    db_run("INSERT OR IGNORE INTO admins (user_id, added_at) VALUES (?, ?)", (user_id, datetime.now().isoformat()))


def remove_admin(user_id):
    db_run("DELETE FROM admins WHERE user_id=?", (user_id,))


def get_all_admin_ids():
    rows = db_run("SELECT user_id FROM admins")
    return [r[0] for r in rows]


# ---------------- FSM HOLATLARI ----------------
class AdminStates(StatesGroup):
    broadcast_wait = State()
    movie_code_wait = State()
    movie_title_wait = State()
    movie_file_wait = State()
    movie_delete_wait = State()
    channel_add_wait = State()
    channel_delete_wait = State()
    series_code_wait = State()
    series_title_wait = State()
    series_episode_wait = State()
    series_edit_select_wait = State()
    series_edit_menu = State()
    series_edit_add_season_wait = State()
    series_edit_delete_episode_wait = State()
    series_edit_delete_season_wait = State()
    admin_add_wait = State()
    admin_delete_wait = State()


def is_owner(user_id: int) -> bool:
    return user_id == OWNER_ID


def is_admin(user_id: int) -> bool:
    return user_id == OWNER_ID or user_id in get_all_admin_ids()


# ---------------- KLAVIATURALAR ----------------
def admin_menu_kb(user_id: int) -> ReplyKeyboardMarkup:
    keyboard = [
        [KeyboardButton(text="📊 Statistika"), KeyboardButton(text="✉️ Xabar yuborish")],
        [KeyboardButton(text="🎬 Kinolar"), KeyboardButton(text="🔐 Kanallar")],
    ]
    if is_owner(user_id):
        keyboard.append([KeyboardButton(text="👮 Adminlar")])
    keyboard.append([KeyboardButton(text="⬅️ Chiqish")])
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)


def adminlar_menu_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="➕ Admin qo'shish"), KeyboardButton(text="🗑 Admin o'chirish")],
            [KeyboardButton(text="📋 Adminlar ro'yxati")],
            [KeyboardButton(text="⬅️ Orqaga")],
        ],
        resize_keyboard=True,
    )


def kinolar_menu_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="➕ Kino qo'shish"), KeyboardButton(text="🗑 Kino o'chirish")],
            [KeyboardButton(text="🎞 Serial qo'shish"), KeyboardButton(text="✏️ Serial tahrirlash")],
            [KeyboardButton(text="📋 Kinolar ro'yxati"), KeyboardButton(text="📋 Seriallar ro'yxati")],
            [KeyboardButton(text="⬅️ Orqaga")],
        ],
        resize_keyboard=True,
    )


def episode_add_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🆕 Yangi mavsum")],
            [KeyboardButton(text="✅ Yakunlash")],
        ],
        resize_keyboard=True,
    )


def series_edit_menu_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="➕ Qism qo'shish"), KeyboardButton(text="🆕 Yangi mavsum boshlash")],
            [KeyboardButton(text="🗑 Qism o'chirish"), KeyboardButton(text="🗑 Mavsumni o'chirish")],
            [KeyboardButton(text="🗑 Serialni butunlay o'chirish")],
            [KeyboardButton(text="⬅️ Orqaga")],
        ],
        resize_keyboard=True,
    )


def kanallar_menu_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="➕ Kanal qo'shish"), KeyboardButton(text="🗑 Kanal o'chirish")],
            [KeyboardButton(text="📋 Kanallar ro'yxati")],
            [KeyboardButton(text="⬅️ Orqaga")],
        ],
        resize_keyboard=True,
    )


def channels_subscribe_kb() -> InlineKeyboardMarkup:
    rows = []
    for chat_id, title in get_all_channels():
        url = f"https://t.me/{chat_id.lstrip('@')}"
        rows.append([InlineKeyboardButton(text=f"➕ {title}", url=url)])
    rows.append([InlineKeyboardButton(text="✅ Tekshirish", callback_data="check_sub")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ---------------- OBUNA TEKSHIRISH ----------------
async def is_subscribed(user_id: int) -> bool:
    channels = get_all_channels()
    if not channels:
        return True
    for chat_id, _ in channels:
        try:
            member = await bot.get_chat_member(chat_id=chat_id, user_id=user_id)
            if member.status in ("left", "kicked"):
                return False
        except Exception as e:
            logging.warning(f"Tekshirishda xato ({chat_id}): {e}")
            return False
    return True


# ================= FOYDALANUVCHI QISMI =================
@dp.message(CommandStart())
async def start_handler(message: Message, command: CommandObject, state: FSMContext):
    add_user(message.from_user.id, message.from_user.first_name, message.from_user.username)

    deep_link_code = command.args  # masalan: /start 374 bo'lsa, bu yerda "374" bo'ladi

    if await is_subscribed(message.from_user.id):
        if deep_link_code:
            await send_content_by_code(message, deep_link_code)
        else:
            await message.answer(
                f"🎉 Assalomu alaykum, {message.from_user.first_name}!\n\n🎬 Kino kodini kiriting."
            )
    else:
        # Obuna bo'lmagan bo'lsa, kodni saqlab qo'yamiz — tekshirishdan keyin avtomatik yuboriladi
        if deep_link_code:
            await state.update_data(pending_code=deep_link_code)
        await message.answer(
            "Botdan foydalanish uchun quyidagi kanallarga obuna bo'ling "
            "va Tekshirish tugmasini bosing. 👇",
            reply_markup=channels_subscribe_kb(),
        )


EPISODES_PAGE_SIZE = 10


def seasons_kb(series_code: str, seasons: list) -> InlineKeyboardMarkup:
    buttons = []
    row = []
    for s in seasons:
        row.append(InlineKeyboardButton(text=f"{s}-mavsum", callback_data=f"seapick:{series_code}:{s}"))
        if len(row) == 3:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def episodes_page_kb(series_code: str, season: int, total_episodes: int, page: int = 0) -> InlineKeyboardMarkup:
    start = page * EPISODES_PAGE_SIZE + 1
    end = min(start + EPISODES_PAGE_SIZE - 1, total_episodes)

    buttons = []
    row = []
    for n in range(start, end + 1):
        row.append(InlineKeyboardButton(text=str(n), callback_data=f"eppick:{series_code}:{season}:{n}"))
        if len(row) == 5:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)

    nav_row = []
    if page > 0:
        nav_row.append(InlineKeyboardButton(
            text="« Oldingi", callback_data=f"eppage:{series_code}:{season}:{page - 1}"
        ))
    if end < total_episodes:
        nav_row.append(InlineKeyboardButton(
            text=f"» {end + 1}-{min(end + EPISODES_PAGE_SIZE, total_episodes)}",
            callback_data=f"eppage:{series_code}:{season}:{page + 1}",
        ))
    if nav_row:
        buttons.append(nav_row)

    return InlineKeyboardMarkup(inline_keyboard=buttons)


async def send_episode_list(target, series_code: str, season: int, page: int = 0, edit: bool = False) -> bool:
    """Bitta mavsum ichidagi qismlar ro'yxatini raqamli tugmalar bilan ko'rsatadi."""
    series = get_series(series_code)
    if not series:
        return False
    title = series[1]
    total = get_episode_count(series_code, season)
    if total == 0:
        return False

    seasons = get_seasons(series_code)
    season_label = f" — {season}-mavsum" if len(seasons) > 1 else ""
    kb = episodes_page_kb(series_code, season, total, page)
    text = f"🎞 {title}{season_label}\n\nJami qismlar: {total}\n\n👇 Kerakli qismni tanlang:"

    if edit:
        await target.edit_text(text, reply_markup=kb)
    else:
        await target.answer(text, reply_markup=kb)
    return True


async def send_series_seasons_or_episodes(target, series_code: str, edit: bool = False) -> bool:
    """Agar serialda bitta mavsum bo'lsa qismlarni to'g'ridan-to'g'ri, ko'p bo'lsa
    avval mavsum tanlash tugmalarini ko'rsatadi."""
    series = get_series(series_code)
    if not series:
        return False
    seasons = get_seasons(series_code)
    if not seasons:
        return False

    if len(seasons) == 1:
        return await send_episode_list(target, series_code, seasons[0], page=0, edit=edit)

    title = series[1]
    kb = seasons_kb(series_code, seasons)
    text = f"🎞 {title}\n\n👇 Mavsumni tanlang:"
    if edit:
        await target.edit_text(text, reply_markup=kb)
    else:
        await target.answer(text, reply_markup=kb)
    return True


@dp.callback_query(F.data.startswith("seapick:"))
async def seapick_handler(call: CallbackQuery):
    _, series_code, season_str = call.data.split(":", 2)
    season = int(season_str)
    await call.answer()
    await send_episode_list(call.message, series_code, season, page=0, edit=False)


@dp.callback_query(F.data.startswith("eppick:"))
async def eppick_handler(call: CallbackQuery):
    _, series_code, season_str, ep_num_str = call.data.split(":", 3)
    season = int(season_str)
    ep_num = int(ep_num_str)
    episodes = dict(get_episodes(series_code, season))
    file_id = episodes.get(ep_num)
    series = get_series(series_code)
    title = series[1] if series else series_code

    if file_id:
        seasons = get_seasons(series_code)
        label = f"{title} — {season}-mavsum, {ep_num}-qism" if len(seasons) > 1 else f"{title} — {ep_num}-qism"
        await call.message.answer_video(video=file_id, caption=label)
        await call.answer()
    else:
        await call.answer("❌ Bu qism topilmadi.", show_alert=True)


@dp.callback_query(F.data.startswith("eppage:"))
async def eppage_handler(call: CallbackQuery):
    _, series_code, season_str, page_str = call.data.split(":", 3)
    season = int(season_str)
    page = int(page_str)
    await send_episode_list(call.message, series_code, season, page=page, edit=True)
    await call.answer()


async def send_content_by_code(message: Message, code: str) -> bool:
    """Kod bo'yicha kino yoki serialni topib yuboradi. Topilsa True, topilmasa False qaytaradi."""
    movie = get_movie(code)
    if movie:
        _, file_id, title = movie
        await message.answer_video(video=file_id, caption=f"🎬 {title}")
        return True

    series = get_series(code)
    if series:
        return await send_series_seasons_or_episodes(message, code, edit=False)

    return False


@dp.callback_query(F.data == "check_sub")
async def check_sub_handler(call: CallbackQuery, state: FSMContext):
    if await is_subscribed(call.from_user.id):
        await call.message.edit_text("✅ Obuna tasdiqlandi!")
        data = await state.get_data()
        pending_code = data.get("pending_code")
        if pending_code:
            await state.update_data(pending_code=None)
            found = await send_content_by_code(call.message, pending_code)
            if not found:
                await call.message.answer("🎬 Endi kino kodini kiriting.")
        else:
            await call.message.answer("🎬 Endi kino kodini kiriting.")
    else:
        await call.answer("❌ Hali barcha kanallarga obuna bo'lmadingiz!", show_alert=True)


# ================= ADMIN PANEL =================
@dp.message(F.text == "/admin")
async def admin_entry(message: Message):
    if not is_admin(message.from_user.id):
        return
    await message.answer("👮 Admin paneliga xush kelibsiz!", reply_markup=admin_menu_kb(message.from_user.id))


@dp.message(F.text == "⬅️ Chiqish")
async def admin_exit(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    await state.clear()
    await message.answer("Chiqdingiz.", reply_markup=None)


@dp.message(F.text == "⬅️ Orqaga")
async def back_to_admin_menu(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    await state.clear()
    await message.answer("Admin panel:", reply_markup=admin_menu_kb(message.from_user.id))


# ---- ADMINLAR (faqat bosh admin uchun) ----
@dp.message(F.text == "👮 Adminlar")
async def admins_menu(message: Message):
    if not is_owner(message.from_user.id):
        return
    await message.answer("👮 Adminlar bo'limi:", reply_markup=adminlar_menu_kb())


@dp.message(F.text == "➕ Admin qo'shish")
async def add_admin_start(message: Message, state: FSMContext):
    if not is_owner(message.from_user.id):
        return
    await state.set_state(AdminStates.admin_add_wait)
    await message.answer(
        "Yangi admin qilmoqchi bo'lgan foydalanuvchining Telegram ID raqamini yuboring.\n"
        "(ID ni bilish uchun @userinfobot dan foydalanishingiz mumkin)"
    )


@dp.message(AdminStates.admin_add_wait)
async def add_admin_save(message: Message, state: FSMContext):
    try:
        uid = int(message.text.strip())
    except ValueError:
        await message.answer("❗ Iltimos, faqat raqam (ID) kiriting.")
        return
    add_admin(uid)
    await state.clear()
    await message.answer(f"✅ Yangi admin qo'shildi: {uid}", reply_markup=adminlar_menu_kb())


@dp.message(F.text == "🗑 Admin o'chirish")
async def delete_admin_start(message: Message, state: FSMContext):
    if not is_owner(message.from_user.id):
        return
    admins = get_all_admin_ids()
    if not admins:
        await message.answer("Hozircha qo'shimcha adminlar yo'q.")
        return
    text = "👮 Qo'shimcha adminlar:\n\n" + "\n".join(f"• {uid}" for uid in admins)
    text += "\n\nO'chirmoqchi bo'lgan admin ID sini kiriting:"
    await state.set_state(AdminStates.admin_delete_wait)
    await message.answer(text)


@dp.message(AdminStates.admin_delete_wait)
async def delete_admin_confirm(message: Message, state: FSMContext):
    try:
        uid = int(message.text.strip())
    except ValueError:
        await message.answer("❗ Iltimos, faqat raqam kiriting.")
        return
    if uid == OWNER_ID:
        await message.answer("❌ Bosh adminni o'chirib bo'lmaydi.")
        return
    remove_admin(uid)
    await state.clear()
    await message.answer(f"🗑 Admin o'chirildi: {uid}", reply_markup=adminlar_menu_kb())


@dp.message(F.text == "📋 Adminlar ro'yxati")
async def list_admins(message: Message):
    if not is_owner(message.from_user.id):
        return
    admins = get_all_admin_ids()
    lines = ["👮 Adminlar ro'yxati:\n", f"• {OWNER_ID} (Bosh admin)"]
    for uid in admins:
        lines.append(f"• {uid}")
    await message.answer("\n".join(lines))


# ---- STATISTIKA ----
@dp.message(F.text == "📊 Statistika")
async def stats_handler(message: Message):
    if not is_admin(message.from_user.id):
        return
    count = get_user_count()
    movies_count = len(get_all_movies())
    channels_count = len(get_all_channels())
    await message.answer(
        f"📊 Statistika:\n\n"
        f"👥 Foydalanuvchilar: {count}\n"
        f"🎬 Kinolar soni: {movies_count}\n"
        f"🔐 Majburiy kanallar: {channels_count}"
    )


# ---- XABAR YUBORISH (BROADCAST) ----
@dp.message(F.text == "✉️ Xabar yuborish")
async def broadcast_start(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    await state.set_state(AdminStates.broadcast_wait)
    await message.answer("Yubormoqchi bo'lgan xabaringizni yuboring (matn, rasm, video — barchasi bo'ladi):")


@dp.message(AdminStates.broadcast_wait)
async def broadcast_send(message: Message, state: FSMContext):
    await state.clear()
    user_ids = get_all_user_ids()
    sent, failed = 0, 0
    await message.answer(f"⏳ {len(user_ids)} ta foydalanuvchiga yuborilmoqda...")
    for uid in user_ids:
        try:
            await message.copy_to(chat_id=uid)
            sent += 1
        except Exception:
            failed += 1
        await asyncio.sleep(0.05)  # flood limitga tushmaslik uchun
    await message.answer(f"✅ Yuborildi: {sent}\n❌ Yuborilmadi: {failed}", reply_markup=admin_menu_kb(message.from_user.id))


# ---- KINOLAR ----
@dp.message(F.text == "🎬 Kinolar")
async def kinolar_menu(message: Message):
    if not is_admin(message.from_user.id):
        return
    await message.answer("🎬 Kinolar bo'limi:", reply_markup=kinolar_menu_kb())


@dp.message(F.text == "➕ Kino qo'shish")
async def add_movie_start(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    await state.set_state(AdminStates.movie_code_wait)
    await message.answer("Kino uchun kod kiriting (masalan: 583):")


@dp.message(AdminStates.movie_code_wait)
async def add_movie_code(message: Message, state: FSMContext):
    await state.update_data(code=message.text.strip())
    await state.set_state(AdminStates.movie_title_wait)
    await message.answer("Endi kino nomini yozing (masalan: Matrix 1999):")


@dp.message(AdminStates.movie_title_wait)
async def add_movie_title(message: Message, state: FSMContext):
    await state.update_data(title=message.text.strip())
    await state.set_state(AdminStates.movie_file_wait)
    await message.answer("Endi videoni (kino faylini) yuboring:")


@dp.message(AdminStates.movie_file_wait, F.video)
async def add_movie_file(message: Message, state: FSMContext):
    data = await state.get_data()
    code = data["code"]
    title = data["title"]  # video bilan kelgan captiondan qat'i nazar, aynan shu nom ishlatiladi
    file_id = message.video.file_id
    add_movie(code, file_id, title)
    await state.clear()
    await message.answer(f"✅ Kino saqlandi!\nKod: {code}\nNomi: {title}", reply_markup=kinolar_menu_kb())


@dp.message(AdminStates.movie_file_wait)
async def add_movie_file_invalid(message: Message):
    await message.answer("❗ Iltimos, video fayl yuboring.")


@dp.message(F.text == "🗑 Kino o'chirish")
async def delete_movie_start(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    await state.set_state(AdminStates.movie_delete_wait)
    await message.answer("O'chirmoqchi bo'lgan kino kodini kiriting:")


@dp.message(AdminStates.movie_delete_wait)
async def delete_movie_confirm(message: Message, state: FSMContext):
    code = message.text.strip()
    if get_movie(code):
        delete_movie(code)
        await message.answer(f"🗑 Kod {code} o'chirildi.", reply_markup=kinolar_menu_kb())
    else:
        await message.answer("❌ Bunday kod topilmadi.", reply_markup=kinolar_menu_kb())
    await state.clear()


@dp.message(F.text == "📋 Kinolar ro'yxati")
async def list_movies(message: Message):
    if not is_admin(message.from_user.id):
        return
    movies = get_all_movies()
    if not movies:
        await message.answer("Hozircha kinolar yo'q.")
        return
    text = "🎬 Kinolar ro'yxati:\n\n" + "\n".join(f"• {code} — {title}" for code, title in movies)
    await message.answer(text)


# ---- SERIAL QO'SHISH ----
@dp.message(F.text == "🎞 Serial qo'shish")
async def add_series_start(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    await state.set_state(AdminStates.series_code_wait)
    await message.answer("Serial uchun kod kiriting (masalan: 700):")


@dp.message(AdminStates.series_code_wait)
async def add_series_code(message: Message, state: FSMContext):
    code = message.text.strip()
    if get_series(code) or get_movie(code):
        await message.answer("❗ Bu kod band. Boshqa kod kiriting:")
        return
    await state.update_data(series_code=code)
    await state.set_state(AdminStates.series_title_wait)
    await message.answer("Endi serial nomini yozing (masalan: The Boys):")


@dp.message(AdminStates.series_title_wait)
async def add_series_title(message: Message, state: FSMContext):
    data = await state.get_data()
    code = data["series_code"]
    title = message.text.strip()
    add_series(code, title)
    await state.update_data(return_state="new", season=1)
    await state.set_state(AdminStates.series_episode_wait)
    await message.answer(
        f"✅ Serial yaratildi: {title}\n\n"
        f"1-mavsum, 1-qismni (videoni) yuboring.\n"
        f"Bir nechta videoni birdan (albom sifatida) tanlab yuborsangiz ham bo'ladi — "
        f"bot ularni ketma-ket yoki fayl nomidagi raqamga qarab avtomatik joylashtiradi.",
        reply_markup=episode_add_kb(),
    )


@dp.message(AdminStates.series_episode_wait, F.video)
async def add_series_episode(message: Message, state: FSMContext):
    data = await state.get_data()
    code = data["series_code"]
    season = data.get("season", 1)
    series = get_series(code)
    title = series[1] if series else code

    filename = message.video.file_name
    ep_num = parse_episode_number_from_filename(filename)
    if ep_num is None:
        ep_num = get_last_episode_number(code, season) + 1

    add_episode(code, season, ep_num, message.video.file_id)
    await message.answer(
        f"✅ {season}-mavsum, {ep_num}-qism saqlandi ({title}).\n"
        f"Keyingi qismni yuboring, 🆕 Yangi mavsum boshlang yoki ✅ Yakunlash tugmasini bosing."
    )


@dp.message(AdminStates.series_episode_wait, F.text == "🆕 Yangi mavsum")
async def new_season_during_add(message: Message, state: FSMContext):
    data = await state.get_data()
    new_season = data.get("season", 1) + 1
    await state.update_data(season=new_season)
    await message.answer(f"🆕 {new_season}-mavsum boshlandi. 1-qismni yuboring:")


@dp.message(AdminStates.series_episode_wait, F.text == "✅ Yakunlash")
async def finish_series_episodes(message: Message, state: FSMContext):
    data = await state.get_data()
    code = data["series_code"]
    return_state = data.get("return_state", "new")
    series = get_series(code)
    title = series[1] if series else code
    total = get_episode_count(code)

    if return_state == "edit":
        await state.set_state(AdminStates.series_edit_menu)
        await message.answer(
            f"🏁 Yakunlandi!\n🎞 {title}\nJami qismlar: {total}",
            reply_markup=series_edit_menu_kb(),
        )
    else:
        await state.clear()
        await message.answer(
            f"🏁 Yakunlandi!\n🎞 {title}\nJami qismlar: {total}",
            reply_markup=kinolar_menu_kb(message.from_user.id),
        )


@dp.message(AdminStates.series_episode_wait)
async def add_series_episode_invalid(message: Message):
    await message.answer("❗ Iltimos, video yuboring, 🆕 Yangi mavsum yoki ✅ Yakunlash tugmasini bosing.")


# ---- SERIAL TAHRIRLASH ----
@dp.message(F.text == "✏️ Serial tahrirlash")
async def edit_series_start(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    series_list = get_all_series()
    if not series_list:
        await message.answer("Hozircha seriallar yo'q.")
        return
    text = "🎞 Seriallar:\n\n" + "\n".join(f"• {code} — {title}" for code, title in series_list)
    text += "\n\nTahrirlamoqchi bo'lgan serial kodini kiriting:"
    await state.set_state(AdminStates.series_edit_select_wait)
    await message.answer(text)


@dp.message(AdminStates.series_edit_select_wait)
async def edit_series_select(message: Message, state: FSMContext):
    code = message.text.strip()
    series = get_series(code)
    if not series:
        await message.answer("❌ Bunday serial topilmadi. Qaytadan kiriting:")
        return
    title = series[1]
    count = get_episode_count(code)
    seasons = get_seasons(code)
    seasons_info = (
        "\n".join(f"  🔹 {s}-mavsum: {get_episode_count(code, s)} qism" for s in seasons)
        if seasons else "  Hali qism yo'q"
    )
    await state.update_data(series_code=code)
    await state.set_state(AdminStates.series_edit_menu)
    await message.answer(
        f"🎞 {title}\nJami qismlar: {count}\n{seasons_info}\n\nNima qilmoqchisiz?",
        reply_markup=series_edit_menu_kb(),
    )


@dp.message(AdminStates.series_edit_menu, F.text == "➕ Qism qo'shish")
async def edit_series_add_episode_start(message: Message, state: FSMContext):
    data = await state.get_data()
    code = data["series_code"]
    seasons = get_seasons(code)
    seasons_text = ", ".join(str(s) for s in seasons) if seasons else "hali yo'q"
    await state.set_state(AdminStates.series_edit_add_season_wait)
    await message.answer(f"Mavjud mavsumlar: {seasons_text}\n\nQaysi mavsumga qism qo'shmoqchisiz? Mavsum raqamini kiriting:")


@dp.message(AdminStates.series_edit_add_season_wait)
async def edit_series_add_episode_season(message: Message, state: FSMContext):
    try:
        season = int(message.text.strip())
    except ValueError:
        await message.answer("❗ Iltimos, faqat raqam kiriting.")
        return
    await state.update_data(season=season, return_state="edit")
    await state.set_state(AdminStates.series_episode_wait)
    await message.answer(f"{season}-mavsumga qism qo'shish. Videoni yuboring:", reply_markup=episode_add_kb())


@dp.message(AdminStates.series_edit_menu, F.text == "🆕 Yangi mavsum boshlash")
async def edit_series_new_season(message: Message, state: FSMContext):
    data = await state.get_data()
    code = data["series_code"]
    seasons = get_seasons(code)
    new_season = (max(seasons) if seasons else 0) + 1
    await state.update_data(season=new_season, return_state="edit")
    await state.set_state(AdminStates.series_episode_wait)
    await message.answer(f"🆕 {new_season}-mavsum boshlandi. 1-qismni yuboring:", reply_markup=episode_add_kb())


@dp.message(AdminStates.series_edit_menu, F.text == "🗑 Qism o'chirish")
async def edit_series_delete_episode_start(message: Message, state: FSMContext):
    data = await state.get_data()
    code = data["series_code"]
    seasons = get_seasons(code)
    if not seasons:
        await message.answer("Bu serialda hozircha qismlar yo'q.")
        return
    await state.set_state(AdminStates.series_edit_delete_episode_wait)
    await message.answer(
        "Mavsum va qism raqamini bo'sh joy bilan kiriting.\n"
        "Masalan: 1 5   (1-mavsum, 5-qism)"
    )


@dp.message(AdminStates.series_edit_delete_episode_wait)
async def edit_series_delete_episode_confirm(message: Message, state: FSMContext):
    data = await state.get_data()
    code = data["series_code"]
    parts = message.text.strip().split()
    if len(parts) != 2 or not all(p.isdigit() for p in parts):
        await message.answer("❗ Format noto'g'ri. Masalan: 1 5")
        return
    season, ep_num = int(parts[0]), int(parts[1])
    delete_episode(code, season, ep_num)
    series = get_series(code)
    title = series[1] if series else code
    count = get_episode_count(code)
    await state.set_state(AdminStates.series_edit_menu)
    await message.answer(
        f"🗑 {season}-mavsum, {ep_num}-qism o'chirildi.\n🎞 {title}\nJami qolgan qismlar: {count}",
        reply_markup=series_edit_menu_kb(),
    )


@dp.message(AdminStates.series_edit_menu, F.text == "🗑 Mavsumni o'chirish")
async def edit_series_delete_season_start(message: Message, state: FSMContext):
    data = await state.get_data()
    code = data["series_code"]
    seasons = get_seasons(code)
    if not seasons:
        await message.answer("Bu serialda hozircha mavsum yo'q.")
        return
    seasons_text = ", ".join(str(s) for s in seasons)
    await state.set_state(AdminStates.series_edit_delete_season_wait)
    await message.answer(f"Mavjud mavsumlar: {seasons_text}\n\nO'chirmoqchi bo'lgan mavsum raqamini kiriting:")


@dp.message(AdminStates.series_edit_delete_season_wait)
async def edit_series_delete_season_confirm(message: Message, state: FSMContext):
    data = await state.get_data()
    code = data["series_code"]
    try:
        season = int(message.text.strip())
    except ValueError:
        await message.answer("❗ Iltimos, faqat raqam kiriting.")
        return
    delete_season(code, season)
    series = get_series(code)
    title = series[1] if series else code
    count = get_episode_count(code)
    await state.set_state(AdminStates.series_edit_menu)
    await message.answer(
        f"🗑 {season}-mavsum butunlay o'chirildi.\n🎞 {title}\nJami qolgan qismlar: {count}",
        reply_markup=series_edit_menu_kb(),
    )


@dp.message(AdminStates.series_edit_menu, F.text == "🗑 Serialni butunlay o'chirish")
async def edit_series_delete_all(message: Message, state: FSMContext):
    data = await state.get_data()
    code = data["series_code"]
    series = get_series(code)
    title = series[1] if series else code
    delete_series(code)
    await state.clear()
    await message.answer(f"🗑 Serial butunlay o'chirildi: {title}", reply_markup=kinolar_menu_kb(message.from_user.id))


@dp.message(F.text == "📋 Seriallar ro'yxati")
async def list_series(message: Message):
    if not is_admin(message.from_user.id):
        return
    series_list = get_all_series()
    if not series_list:
        await message.answer("Hozircha seriallar yo'q.")
        return
    lines = ["🎞 Seriallar ro'yxati:\n"]
    for code, title in series_list:
        count = get_episode_count(code)
        seasons_count = len(get_seasons(code))
        lines.append(f"• {code} — {title} ({count} qism, {seasons_count} mavsum)")
    await message.answer("\n".join(lines))


# ---- KANALLAR ----
@dp.message(F.text == "🔐 Kanallar")
async def kanallar_menu(message: Message):
    if not is_admin(message.from_user.id):
        return
    await message.answer("🔐 Majburiy kanallar bo'limi:", reply_markup=kanallar_menu_kb())


@dp.message(F.text == "➕ Kanal qo'shish")
async def add_channel_start(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    await state.set_state(AdminStates.channel_add_wait)
    await message.answer(
        "Kanal username'ini yuboring (masalan: @kanalim).\n"
        "❗ Botni o'sha kanalga admin qilib qo'shishni unutmang!"
    )


@dp.message(AdminStates.channel_add_wait)
async def add_channel_save(message: Message, state: FSMContext):
    chat_id = message.text.strip()
    try:
        chat = await bot.get_chat(chat_id)
        add_channel(chat_id, chat.title)
        await message.answer(f"✅ Kanal qo'shildi: {chat.title}", reply_markup=kanallar_menu_kb())
    except Exception as e:
        await message.answer(f"❌ Xato: bot shu kanalga admin emas yoki username noto'g'ri.\n{e}")
    await state.clear()


@dp.message(F.text == "🗑 Kanal o'chirish")
async def delete_channel_start(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    await state.set_state(AdminStates.channel_delete_wait)
    await message.answer("O'chirmoqchi bo'lgan kanal username'ini kiriting (masalan: @kanalim):")


@dp.message(AdminStates.channel_delete_wait)
async def delete_channel_confirm(message: Message, state: FSMContext):
    chat_id = message.text.strip()
    delete_channel(chat_id)
    await message.answer(f"🗑 {chat_id} o'chirildi.", reply_markup=kanallar_menu_kb())
    await state.clear()


@dp.message(F.text == "📋 Kanallar ro'yxati")
async def list_channels(message: Message):
    if not is_admin(message.from_user.id):
        return
    channels = get_all_channels()
    if not channels:
        await message.answer("Hozircha majburiy kanal yo'q.")
        return
    text = "🔐 Kanallar:\n\n" + "\n".join(f"• {title} ({cid})" for cid, title in channels)
    await message.answer(text)


# ================= QIDIRUV NATIJALARI (RAQAMLI TUGMALAR) =================
def search_all_by_title(query, limit=10):
    """Kino va seriallarni birga nom bo'yicha qidiradi."""
    movies = [("movie", code, title) for code, title in search_movies_by_title(query, limit)]
    series = [("series", code, title) for code, title in search_series_by_title(query, limit)]
    return (movies + series)[:limit]


def search_results_kb(results) -> InlineKeyboardMarkup:
    # Har bir natija uchun raqamli tugma yaratadi (1, 2, 3, ...)
    buttons = []
    row = []
    for i, (kind, code, title) in enumerate(results, start=1):
        row.append(InlineKeyboardButton(text=str(i), callback_data=f"pick:{kind}:{code}"))
        if len(row) == 5:  # har qatorda 5 ta tugma
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    return InlineKeyboardMarkup(inline_keyboard=buttons)


@dp.callback_query(F.data.startswith("pick:"))
async def pick_handler(call: CallbackQuery):
    _, kind, code = call.data.split(":", 2)

    if kind == "movie":
        movie = get_movie(code)
        if movie:
            _, file_id, title = movie
            await call.message.answer_video(video=file_id, caption=f"🎬 {title}")
            await call.answer()
            return

    elif kind == "series":
        await call.answer()
        found = await send_series_seasons_or_episodes(call.message, code, edit=False)
        if found:
            return

    await call.answer("❌ Topilmadi, o'chirilgan bo'lishi mumkin.", show_alert=True)


# ================= KINO/SERIAL KODI YOKI NOMI QABUL QILISH =================
# Bu handler eng oxirida turishi shart — aks holda admin buyruqlari bilan
# to'qnashib qoladi (FSM holatlari va aniq matnli tugmalar avval ushlanadi).
@dp.message(F.text)
async def code_handler(message: Message):
    if not await is_subscribed(message.from_user.id):
        await message.answer("Avval kanallarga obuna bo'ling. 👇", reply_markup=channels_subscribe_kb())
        return

    query = message.text.strip()

    # 1) Avval aniq kod bo'yicha qidiramiz (kino yoki serial, masalan "583" yoki "700")
    if await send_content_by_code(message, query):
        return

    # 2) Kod topilmasa, nom bo'yicha qidiramiz (masalan "matrix")
    results = search_all_by_title(query)
    if results:
        text_lines = [f"🔍 \"{query}\" bo'yicha natijalar:\n"]
        for i, (kind, code, title) in enumerate(results, start=1):
            icon = "🎬" if kind == "movie" else "🎞"
            text_lines.append(f"{i}. {icon} {title}")
        text_lines.append("\n👇 Kerakli raqamni tanlang:")
        await message.answer("\n".join(text_lines), reply_markup=search_results_kb(results))
    else:
        await message.answer("❌ Bunday kino yoki serial topilmadi. Kod yoki nomini qaytadan tekshiring.")


# ================= ISHGA TUSHIRISH =================
async def main():
    db_init()
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
