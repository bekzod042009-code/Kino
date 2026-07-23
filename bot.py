import asyncio
import logging
import os
import random
import sqlite3
from datetime import datetime

import aiohttp
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

# Bosh admin (to'liq huquqli) foydalanuvchi ID'lari
# ID ni bilish uchun @userinfobot ga /start bosing
ADMIN_IDS = [8012700729]

# TMDb API kaliti — kino/serial haqida internetdan avtomatik ma'lumot olish uchun
TMDB_API_KEY = os.getenv("TMDB_API_KEY", "b610f6ae054e3aea457f189f6a9e6407")
TMDB_BASE = "https://api.themoviedb.org/3"
# =====================================

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

DB_PATH = os.getenv("DB_PATH", "kino_bot.db")

# Bot username — ishga tushganda avtomatik aniqlanadi (kanal postidagi "Ko'rish" tugmasi uchun)
BOT_USERNAME = ""


# ---------------- JANR VA DAVLAT NOMLARINI O'ZBEKCHAGA O'GIRISH ----------------
GENRE_UZ = {
    "Action": "Jangari",
    "Adventure": "Sarguzasht",
    "Animation": "Multfilm",
    "Comedy": "Komediya",
    "Crime": "Jinoiy",
    "Documentary": "Hujjatli",
    "Drama": "Drama",
    "Family": "Oilaviy",
    "Fantasy": "Fantastika",
    "History": "Tarixiy",
    "Horror": "Qo'rqinchli",
    "Music": "Musiqiy",
    "Mystery": "Sirli",
    "Romance": "Romantik",
    "Science Fiction": "Ilmiy fantastika",
    "TV Movie": "TV kino",
    "Thriller": "Triller",
    "War": "Urush",
    "Western": "Vestern",
    "Action & Adventure": "Jangari-sarguzasht",
    "Kids": "Bolalar",
    "News": "Yangiliklar",
    "Reality": "Realiti-shou",
    "Sci-Fi & Fantasy": "Fantastika",
    "Soap": "Melodrama",
    "Talk": "Tok-shou",
    "War & Politics": "Urush va siyosat",
}

COUNTRY_UZ = {
    "US": "AQSH",
    "GB": "Buyuk Britaniya",
    "FR": "Fransiya",
    "DE": "Germaniya",
    "RU": "Rossiya",
    "KR": "Janubiy Koreya",
    "KP": "Shimoliy Koreya",
    "JP": "Yaponiya",
    "CN": "Xitoy",
    "IN": "Hindiston",
    "TR": "Turkiya",
    "IT": "Italiya",
    "ES": "Ispaniya",
    "CA": "Kanada",
    "AU": "Avstraliya",
    "UZ": "O'zbekiston",
    "KZ": "Qozog'iston",
    "UA": "Ukraina",
    "BR": "Braziliya",
    "MX": "Meksika",
    "TH": "Tailand",
    "HK": "Gonkong",
    "PH": "Filippin",
    "PL": "Polsha",
    "NL": "Niderlandiya",
    "SE": "Shvetsiya",
    "BE": "Belgiya",
    "CH": "Shveytsariya",
    "AT": "Avstriya",
    "DK": "Daniya",
    "NO": "Norvegiya",
    "FI": "Finlyandiya",
    "IE": "Irlandiya",
    "PT": "Portugaliya",
    "GR": "Gretsiya",
    "EG": "Misr",
    "IR": "Eron",
    "SA": "Saudiya Arabistoni",
    "AE": "BAA",
    "IL": "Isroil",
    "ID": "Indoneziya",
    "MY": "Malayziya",
    "SG": "Singapur",
    "VN": "Vyetnam",
    "AR": "Argentina",
    "CO": "Kolumbiya",
    "CZ": "Chexiya",
    "RO": "Ruminiya",
    "HU": "Vengriya",
    "NZ": "Yangi Zelandiya",
    "TW": "Tayvan",
}


def translate_genres(genre_names) -> str:
    """Vergul bilan ajratilgan janr nomlarini o'zbekchaga o'giradi."""
    if not genre_names:
        return ""
    parts = [g.strip() for g in genre_names.split(",") if g.strip()]
    translated = [GENRE_UZ.get(p, p) for p in parts]
    return ", ".join(translated)


def translate_country(code_or_name: str) -> str:
    if not code_or_name:
        return ""
    return COUNTRY_UZ.get(code_or_name, code_or_name)


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
        episode_number INTEGER,
        file_id TEXT
    )""")
    cur.execute("""CREATE TABLE IF NOT EXISTS channels (
        chat_id TEXT PRIMARY KEY,
        title TEXT
    )""")
    cur.execute("""CREATE TABLE IF NOT EXISTS admins (
        user_id INTEGER PRIMARY KEY,
        added_at TEXT
    )""")
    cur.execute("""CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT
    )""")
    conn.commit()

    # Eski bazalarda ham ishlashi uchun yangi ustunlarni qo'shib qo'yamiz
    extra_columns = [
        ("movies", "poster_url", "TEXT"),
        ("movies", "rating", "TEXT"),
        ("movies", "genre", "TEXT"),
        ("movies", "country", "TEXT"),
        ("movies", "year", "TEXT"),
        ("movies", "views", "INTEGER DEFAULT 0"),
        ("series", "poster_url", "TEXT"),
        ("series", "rating", "TEXT"),
        ("series", "genre", "TEXT"),
        ("series", "country", "TEXT"),
        ("series", "year", "TEXT"),
        ("series", "views", "INTEGER DEFAULT 0"),
    ]
    for table, col, coltype in extra_columns:
        try:
            cur.execute(f"ALTER TABLE {table} ADD COLUMN {col} {coltype}")
        except sqlite3.OperationalError:
            pass  # ustun allaqachon mavjud
    conn.commit()
    conn.close()


def db_run(query, params=()):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
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


# ---------------- SOZLAMALAR (settings) ----------------
def set_setting(key, value):
    db_run("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))


def get_setting(key):
    rows = db_run("SELECT value FROM settings WHERE key=?", (key,))
    return rows[0][0] if rows else None


# ---------------- KINOLAR ----------------
def add_movie(code, file_id, title, info=None):
    info = info or {}
    db_run(
        """INSERT OR REPLACE INTO movies
           (code, file_id, title, poster_url, rating, genre,
            country, year, views)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, COALESCE((SELECT views FROM movies WHERE code=?), 0))""",
        (code, file_id, title, info.get("poster_url", ""),
         info.get("rating", ""), info.get("genre", ""), info.get("country", ""),
         info.get("year", ""), code),
    )


def get_movie(code):
    rows = db_run("SELECT * FROM movies WHERE code=?", (code,))
    return rows[0] if rows else None


def delete_movie(code):
    db_run("DELETE FROM movies WHERE code=?", (code,))


def get_all_movies():
    return db_run("SELECT code, title FROM movies")


def search_movies_by_title(query, limit=10):
    return db_run(
        "SELECT code, title FROM movies WHERE title LIKE ? LIMIT ?",
        (f"%{query}%", limit),
    )


def increment_movie_views(code):
    db_run("UPDATE movies SET views = COALESCE(views, 0) + 1 WHERE code=?", (code,))


def get_top_movies(limit=5):
    return db_run("SELECT code, title, views FROM movies ORDER BY views DESC LIMIT ?", (limit,))


# ---------------- KANALLAR ----------------
def add_channel(chat_id, title):
    db_run("INSERT OR REPLACE INTO channels (chat_id, title) VALUES (?, ?)", (chat_id, title))


def delete_channel(chat_id):
    db_run("DELETE FROM channels WHERE chat_id=?", (chat_id,))


def get_all_channels():
    return db_run("SELECT chat_id, title FROM channels")


# ---------------- ADMINLAR ----------------
def add_admin_db(user_id: int):
    db_run(
        "INSERT OR IGNORE INTO admins (user_id, added_at) VALUES (?, ?)",
        (user_id, datetime.now().isoformat()),
    )


def remove_admin_db(user_id: int):
    db_run("DELETE FROM admins WHERE user_id=?", (user_id,))


def get_all_admin_ids_db():
    rows = db_run("SELECT user_id FROM admins")
    return [r[0] for r in rows]


# ---------------- SERIALLAR (shu jumladan 2-3 qismli kinolar) ----------------
def add_series(code, title, info=None):
    info = info or {}
    db_run(
        """INSERT OR REPLACE INTO series
           (code, title, poster_url, rating, genre,
            country, year, views)
           VALUES (?, ?, ?, ?, ?, ?, ?, COALESCE((SELECT views FROM series WHERE code=?), 0))""",
        (code, title, info.get("poster_url", ""),
         info.get("rating", ""), info.get("genre", ""), info.get("country", ""),
         info.get("year", ""), code),
    )


def get_series(code):
    rows = db_run("SELECT * FROM series WHERE code=?", (code,))
    return rows[0] if rows else None


def delete_series(code):
    db_run("DELETE FROM series WHERE code=?", (code,))
    db_run("DELETE FROM episodes WHERE series_code=?", (code,))


def get_all_series():
    return db_run("SELECT code, title FROM series")


def search_series_by_title(query, limit=10):
    return db_run(
        "SELECT code, title FROM series WHERE title LIKE ? LIMIT ?",
        (f"%{query}%", limit),
    )


def increment_series_views(code):
    db_run("UPDATE series SET views = COALESCE(views, 0) + 1 WHERE code=?", (code,))


def get_top_series(limit=5):
    return db_run("SELECT code, title, views FROM series ORDER BY views DESC LIMIT ?", (limit,))


def add_episode(series_code, episode_number, file_id):
    db_run(
        "INSERT INTO episodes (series_code, episode_number, file_id) VALUES (?, ?, ?)",
        (series_code, episode_number, file_id),
    )


def get_episodes(series_code):
    return db_run(
        "SELECT episode_number, file_id FROM episodes WHERE series_code=? ORDER BY episode_number",
        (series_code,),
    )


def get_episode_count(series_code):
    return len(get_episodes(series_code))


def get_last_episode_number(series_code):
    rows = db_run("SELECT MAX(episode_number) FROM episodes WHERE series_code=?", (series_code,))
    return rows[0][0] or 0


def delete_episode(series_code, episode_number):
    db_run(
        "DELETE FROM episodes WHERE series_code=? AND episode_number=?",
        (series_code, episode_number),
    )


# ---------------- KOD AVTOMATIK GENERATSIYASI ----------------
def generate_unique_code() -> str:
    """Kino/serial uchun hech qachon takrorlanmaydigan 3 xonali kod yaratadi."""
    for _ in range(2000):
        code = str(random.randint(100, 999))
        if not get_movie(code) and not get_series(code):
            return code
    while True:
        code = str(random.randint(1000, 9999))
        if not get_movie(code) and not get_series(code):
            return code


# ---------------- TMDb: INTERNETDAN AVTOMATIK MA'LUMOT OLISH ----------------
async def _tmdb_try(session: aiohttp.ClientSession, media_type: str, title: str):
    try:
        search_url = f"{TMDB_BASE}/search/{media_type}"
        params = {"api_key": TMDB_API_KEY, "query": title, "language": "en-US"}
        async with session.get(search_url, params=params, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            data = await resp.json()
        results = data.get("results") or []
        if not results:
            return None
        tmdb_id = results[0]["id"]

        detail_url = f"{TMDB_BASE}/{media_type}/{tmdb_id}"
        params = {"api_key": TMDB_API_KEY, "language": "en-US"}
        async with session.get(detail_url, params=params, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            detail = await resp.json()

        genres_en = ", ".join(g["name"] for g in detail.get("genres", []))
        genres = translate_genres(genres_en)

        country = ""
        countries = detail.get("production_countries")
        if countries:
            country = ", ".join(
                translate_country(c.get("iso_3166_1") or c.get("name"))
                for c in countries
            )
        elif detail.get("origin_country"):
            country = ", ".join(translate_country(c) for c in detail["origin_country"])

        poster_path = detail.get("poster_path")
        poster_url = f"https://image.tmdb.org/t/p/w500{poster_path}" if poster_path else ""

        year = (detail.get("release_date") or detail.get("first_air_date") or "")[:4]
        rating = detail.get("vote_average")
        rating = round(rating, 1) if rating else ""

        return {
            "poster_url": poster_url,
            "rating": rating,
            "genre": genres,
            "country": country,
            "year": year,
        }
    except Exception as e:
        logging.warning(f"TMDb xato ({media_type}, {title}): {e}")
        return None


async def tmdb_fetch(title: str):
    """Kino sifatida, topilmasa serial sifatida qidiradi. Topilmasa None qaytaradi."""
    async with aiohttp.ClientSession() as session:
        info = await _tmdb_try(session, "movie", title)
        if not info:
            info = await _tmdb_try(session, "tv", title)
        return info


def format_info_preview(info) -> str:
    if not info:
        return "⚠️ Internetdan ma'lumot topilmadi — kino/serial faqat nomi bilan saqlanadi."
    lines = ["🌐 Topilgan ma'lumot:"]
    if info.get("year"):
        lines.append(f"📆 Yili: {info['year']}")
    if info.get("genre"):
        lines.append(f"🍿 Janri: {info['genre']}")
    if info.get("country"):
        lines.append(f"🗽 Davlati: {info['country']}")
    if info.get("rating"):
        lines.append(f"⭐ Reytingi: {info['rating']}")
    return "\n".join(lines)


def build_caption(row, kind="movie", header=None) -> str:
    """Kanal posti va foydalanuvchiga yuboriladigan qisqa ma'lumot bloki."""
    row = dict(row)
    icon = "🎬" if kind == "movie" else "🎞"
    lines = []
    if header:
        lines.append(header)
        lines.append("")
    lines.append(f"{icon} {row.get('title', '')}")
    lines.append("➖➖➖➖➖➖➖")
    lines.append(f"🗽 Davlati: {row.get('country') or 'Nomaʼlum'}")
    lines.append("🇺🇿 Tili: O'zbek")

    genre = row.get("genre") or ""
    if genre:
        tags = " ".join(f"#{g.strip().replace(' ', '_')}" for g in genre.split(",") if g.strip())
    else:
        tags = "#Nomaʼlum"
    lines.append(f"🍿 Janri: {tags}")
    lines.append(f"📆 Yili: {row.get('year') or 'Nomaʼlum'}")

    if kind == "series":
        total = get_episode_count(row.get("code", ""))
        if total:
            lines.append(f"🔢 Qismlar soni: {total}")

    if row.get("rating"):
        lines.append(f"⭐ Reytingi: {row['rating']}")

    return "\n".join(lines)


async def post_to_channel(code, row, is_series=False):
    """Kino/serial saqlanganda kanalga avtomatik chiroyli post joylaydi."""
    post_channel = get_setting("post_channel")
    if not post_channel:
        return
    header = "🔥 Yangi Serial" if is_series else "🔥 Yangi Premyera"
    kind = "series" if is_series else "movie"
    caption = build_caption(row, kind=kind, header=header)

    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(
            text="🎬 Ko'rish",
            url=f"https://t.me/{BOT_USERNAME}?start={code}",
        )
    ]])

    poster_url = dict(row).get("poster_url")
    try:
        if poster_url:
            await bot.send_photo(chat_id=post_channel, photo=poster_url, caption=caption, reply_markup=kb)
        else:
            await bot.send_message(chat_id=post_channel, text=caption, reply_markup=kb)
    except Exception as e:
        logging.warning(f"Kanalga post qilishda xato: {e}")


# ---------------- FSM HOLATLARI ----------------
class AdminStates(StatesGroup):
    broadcast_wait = State()
    movie_title_wait = State()
    movie_file_wait = State()
    movie_delete_wait = State()
    channel_add_wait = State()
    channel_delete_wait = State()
    channel_edit_select_wait = State()
    channel_edit_new_wait = State()
    post_channel_wait = State()
    series_title_wait = State()
    series_episode_wait = State()
    series_edit_select_wait = State()
    series_edit_menu = State()
    series_edit_delete_episode_wait = State()
    admin_add_wait = State()
    admin_remove_wait = State()


def is_bosh_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


def is_admin(user_id: int) -> bool:
    """Bosh admin yoki qo'shilgan (yuklovchi) admin."""
    return is_bosh_admin(user_id) or user_id in get_all_admin_ids_db()


# ---------------- KLAVIATURALAR ----------------
def admin_menu_kb(is_bosh: bool = False) -> ReplyKeyboardMarkup:
    if is_bosh:
        keyboard = [
            [KeyboardButton(text="📊 Statistika"), KeyboardButton(text="✉️ Xabar yuborish")],
            [KeyboardButton(text="🎬 Kinolar"), KeyboardButton(text="🔐 Kanallar")],
            [KeyboardButton(text="👤 Adminlar")],
            [KeyboardButton(text="⬅️ Chiqish")],
        ]
    else:
        # Qo'shilgan adminlar faqat kino/serial yuklashi mumkin
        keyboard = [
            [KeyboardButton(text="➕ Kino qo'shish"), KeyboardButton(text="🎞 Serial qo'shish")],
            [KeyboardButton(text="⬅️ Chiqish")],
        ]
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
        keyboard=[[KeyboardButton(text="✅ Yakunlash")]],
        resize_keyboard=True,
    )


def series_edit_menu_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="➕ Qism qo'shish"), KeyboardButton(text="🗑 Qism o'chirish")],
            [KeyboardButton(text="🗑 Serialni butunlay o'chirish")],
            [KeyboardButton(text="⬅️ Orqaga")],
        ],
        resize_keyboard=True,
    )


def kanallar_menu_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="➕ Kanal qo'shish"), KeyboardButton(text="🗑 Kanal o'chirish")],
            [KeyboardButton(text="✏️ Kanal tahrirlash"), KeyboardButton(text="📢 Post kanali")],
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

    deep_link_code = command.args

    if await is_subscribed(message.from_user.id):
        if deep_link_code:
            await send_content_by_code(message, deep_link_code)
        else:
            await message.answer(
                f"🎉 Assalomu alaykum, {message.from_user.first_name}!\n\n🎬 Kino kodini kiriting."
            )
    else:
        if deep_link_code:
            await state.update_data(pending_code=deep_link_code)
        await message.answer(
            "Botdan foydalanish uchun quyidagi kanallarga obuna bo'ling "
            "va Tekshirish tugmasini bosing. 👇",
            reply_markup=channels_subscribe_kb(),
        )


EPISODES_PAGE_SIZE = 10


def episodes_page_kb(series_code: str, total_episodes: int, page: int = 0) -> InlineKeyboardMarkup:
    start = page * EPISODES_PAGE_SIZE + 1
    end = min(start + EPISODES_PAGE_SIZE - 1, total_episodes)

    buttons = []
    row = []
    for n in range(start, end + 1):
        row.append(InlineKeyboardButton(text=str(n), callback_data=f"eppick:{series_code}:{n}"))
        if len(row) == 5:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)

    nav_row = []
    if page > 0:
        nav_row.append(InlineKeyboardButton(text="« Oldingi", callback_data=f"eppage:{series_code}:{page - 1}"))
    if end < total_episodes:
        nav_row.append(InlineKeyboardButton(
            text=f"» {end + 1}-{min(end + EPISODES_PAGE_SIZE, total_episodes)}",
            callback_data=f"eppage:{series_code}:{page + 1}",
        ))
    if nav_row:
        buttons.append(nav_row)

    return InlineKeyboardMarkup(inline_keyboard=buttons)


async def send_series_episode_list(target, series_code: str, page: int = 0, edit: bool = False) -> bool:
    series = get_series(series_code)
    if not series:
        return False
    title = series["title"]
    total = get_episode_count(series_code)
    if total == 0:
        return False

    kb = episodes_page_kb(series_code, total, page)
    text = f"🎞 {title}\n\nJami qismlar: {total}\n\n👇 Kerakli qismni tanlang:"

    if edit:
        await target.edit_text(text, reply_markup=kb)
    else:
        await target.answer(text, reply_markup=kb)
    return True


@dp.callback_query(F.data.startswith("eppick:"))
async def eppick_handler(call: CallbackQuery):
    _, series_code, ep_num_str = call.data.split(":", 2)
    ep_num = int(ep_num_str)
    episodes = dict(get_episodes(series_code))
    file_id = episodes.get(ep_num)
    series = get_series(series_code)
    title = series["title"] if series else series_code

    if file_id:
        await call.message.answer_video(video=file_id, caption=f"{title} — {ep_num}-qism")
        increment_series_views(series_code)
        await call.answer()
    else:
        await call.answer("❌ Bu qism topilmadi.", show_alert=True)


@dp.callback_query(F.data.startswith("eppage:"))
async def eppage_handler(call: CallbackQuery):
    _, series_code, page_str = call.data.split(":", 2)
    page = int(page_str)
    await send_series_episode_list(call.message, series_code, page=page, edit=True)
    await call.answer()


async def send_content_by_code(message: Message, code: str) -> bool:
    movie = get_movie(code)
    if movie:
        caption = build_caption(movie, kind="movie")
        await message.answer_video(video=movie["file_id"], caption=caption)
        increment_movie_views(code)
        return True

    series = get_series(code)
    if series:
        return await send_series_episode_list(message, code, page=0, edit=False)

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
    await message.answer(
        "👮 Admin paneliga xush kelibsiz!",
        reply_markup=admin_menu_kb(is_bosh_admin(message.from_user.id)),
    )


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
    await message.answer(
        "Admin panel:",
        reply_markup=admin_menu_kb(is_bosh_admin(message.from_user.id)),
    )


# ---- STATISTIKA (FAQAT BOSH ADMIN) ----
@dp.message(F.text == "📊 Statistika")
async def stats_handler(message: Message):
    if not is_bosh_admin(message.from_user.id):
        return
    count = get_user_count()
    movies_count = len(get_all_movies())
    series_count = len(get_all_series())
    channels_count = len(get_all_channels())

    lines = [
        "📊 Statistika:\n",
        f"👥 Foydalanuvchilar: {count}",
        f"🎬 Kinolar soni: {movies_count}",
        f"🎞 Seriallar/qismli kinolar soni: {series_count}",
        f"🔐 Majburiy kanallar: {channels_count}",
    ]

    top_movies = get_top_movies(5)
    if top_movies:
        lines.append("\n🔝 Eng ko'p ko'rilgan kinolar:")
        for code, title, views in top_movies:
            lines.append(f"• {title} — {views or 0} marta")

    top_series = get_top_series(5)
    if top_series:
        lines.append("\n🔝 Eng ko'p ko'rilgan seriallar:")
        for code, title, views in top_series:
            lines.append(f"• {title} — {views or 0} marta")

    await message.answer("\n".join(lines))


# ---- XABAR YUBORISH / BROADCAST (FAQAT BOSH ADMIN) ----
@dp.message(F.text == "✉️ Xabar yuborish")
async def broadcast_start(message: Message, state: FSMContext):
    if not is_bosh_admin(message.from_user.id):
        return
    await state.set_state(AdminStates.broadcast_wait)
    await message.answer("Yubormoqchi bo'lgan xabaringizni yuboring (matn, rasm, video — barchasi bo'ladi):")


@dp.message(AdminStates.broadcast_wait)
async def broadcast_send(message: Message, state: FSMContext):
    if not is_bosh_admin(message.from_user.id):
        await state.clear()
        return
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
        await asyncio.sleep(0.05)
    await message.answer(
        f"✅ Yuborildi: {sent}\n❌ Yuborilmadi: {failed}",
        reply_markup=admin_menu_kb(is_bosh_admin(message.from_user.id)),
    )


# ---- KINOLAR (BOSH ADMIN UCHUN TO'LIQ BO'LIM) ----
@dp.message(F.text == "🎬 Kinolar")
async def kinolar_menu(message: Message):
    if not is_bosh_admin(message.from_user.id):
        return
    await message.answer("🎬 Kinolar bo'limi:", reply_markup=kinolar_menu_kb())


# ---- KINO QO'SHISH (bosh admin va qo'shilgan adminlar uchun ham ochiq — faqat yuklash) ----
@dp.message(F.text == "➕ Kino qo'shish")
async def add_movie_start(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    await state.set_state(AdminStates.movie_title_wait)
    await message.answer(
        "Kino nomini yozing (masalan: Matrix 1999):\n\n"
        "⏳ Nomni yozganingizdan so'ng, bot avtomatik ravishda internetdan "
        "poster, janr, davlat va yil kabi ma'lumotlarni qidiradi."
    )


@dp.message(AdminStates.movie_title_wait)
async def add_movie_title(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await state.clear()
        return
    title = message.text.strip()
    searching = await message.answer("🔎 Internetdan ma'lumot qidirilmoqda...")
    info = await tmdb_fetch(title)
    await state.update_data(title=title, info=info or {})
    await state.set_state(AdminStates.movie_file_wait)
    try:
        await searching.delete()
    except Exception:
        pass
    await message.answer(format_info_preview(info))
    await message.answer("🎥 Endi videoni (kino faylini) yuboring:")


@dp.message(AdminStates.movie_file_wait, F.video)
async def add_movie_file(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await state.clear()
        return
    data = await state.get_data()
    title = data["title"]
    info = data.get("info") or {}
    file_id = message.video.file_id

    code = generate_unique_code()
    add_movie(code, file_id, title, info)
    row = get_movie(code)

    await state.clear()
    await message.answer(
        f"✅ Kino saqlandi!\n🔢 Kod: {code}\n🎬 Nomi: {title}",
        reply_markup=admin_menu_kb(is_bosh_admin(message.from_user.id)),
    )
    await post_to_channel(code, row, is_series=False)


@dp.message(AdminStates.movie_file_wait)
async def add_movie_file_invalid(message: Message):
    if not is_admin(message.from_user.id):
        return
    await message.answer("❗ Iltimos, video fayl yuboring.")


# ---- KINO O'CHIRISH (FAQAT BOSH ADMIN) ----
@dp.message(F.text == "🗑 Kino o'chirish")
async def delete_movie_start(message: Message, state: FSMContext):
    if not is_bosh_admin(message.from_user.id):
        return
    await state.set_state(AdminStates.movie_delete_wait)
    await message.answer("O'chirmoqchi bo'lgan kino kodini kiriting:")


@dp.message(AdminStates.movie_delete_wait)
async def delete_movie_confirm(message: Message, state: FSMContext):
    if not is_bosh_admin(message.from_user.id):
        await state.clear()
        return
    code = message.text.strip()
    if get_movie(code):
        delete_movie(code)
        await message.answer(f"🗑 Kod {code} o'chirildi.", reply_markup=kinolar_menu_kb())
    else:
        await message.answer("❌ Bunday kod topilmadi.", reply_markup=kinolar_menu_kb())
    await state.clear()


# ---- KINOLAR RO'YXATI (FAQAT BOSH ADMIN) ----
@dp.message(F.text == "📋 Kinolar ro'yxati")
async def list_movies(message: Message):
    if not is_bosh_admin(message.from_user.id):
        return
    movies = get_all_movies()
    if not movies:
        await message.answer("Hozircha kinolar yo'q.")
        return
    text = "🎬 Kinolar ro'yxati:\n\n" + "\n".join(f"• {code} — {title}" for code, title in movies)
    await message.answer(text)


# ---- SERIAL / QISMLI KINO QO'SHISH (bosh admin va qo'shilgan adminlar uchun ham ochiq) ----
@dp.message(F.text == "🎞 Serial qo'shish")
async def add_series_start(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    await state.set_state(AdminStates.series_title_wait)
    await message.answer(
        "Serial yoki qismli kino nomini yozing (masalan: The Boys yoki Matrix):\n\n"
        "⏳ Nomni yozganingizdan so'ng, bot avtomatik ravishda internetdan ma'lumot qidiradi."
    )


@dp.message(AdminStates.series_title_wait)
async def add_series_title(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await state.clear()
        return
    title = message.text.strip()
    searching = await message.answer("🔎 Internetdan ma'lumot qidirilmoqda...")
    info = await tmdb_fetch(title)

    code = generate_unique_code()
    add_series(code, title, info)

    await state.update_data(series_code=code, return_state="new")
    await state.set_state(AdminStates.series_episode_wait)
    try:
        await searching.delete()
    except Exception:
        pass
    await message.answer(format_info_preview(info))
    await message.answer(
        f"✅ Yaratildi: {title}\n🔢 Kod: {code}\n\n1-qismni (videoni) yuboring:",
        reply_markup=episode_add_kb(),
    )


@dp.message(AdminStates.series_episode_wait, F.video)
async def add_series_episode(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await state.clear()
        return
    data = await state.get_data()
    code = data["series_code"]
    series = get_series(code)
    title = series["title"] if series else code
    next_num = get_last_episode_number(code) + 1
    add_episode(code, next_num, message.video.file_id)
    await message.answer(
        f"✅ {next_num}-qism saqlandi ({title}).\n"
        f"Keyingi qismni yuboring yoki ✅ Yakunlash tugmasini bosing."
    )


@dp.message(AdminStates.series_episode_wait, F.text == "✅ Yakunlash")
async def finish_series_episodes(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await state.clear()
        return
    data = await state.get_data()
    code = data["series_code"]
    is_new = data.get("return_state") == "new"
    series = get_series(code)
    title = series["title"] if series else code
    total = get_episode_count(code)
    await state.clear()
    await message.answer(
        f"🏁 Yakunlandi!\n🎞 {title}\n🔢 Kod: {code}\nJami qismlar: {total}",
        reply_markup=admin_menu_kb(is_bosh_admin(message.from_user.id)),
    )
    if is_new and series:
        await post_to_channel(code, series, is_series=True)


@dp.message(AdminStates.series_episode_wait)
async def add_series_episode_invalid(message: Message):
    if not is_admin(message.from_user.id):
        return
    await message.answer("❗ Iltimos, video yuboring yoki ✅ Yakunlash tugmasini bosing.")


# ---- SERIAL TAHRIRLASH (FAQAT BOSH ADMIN) ----
@dp.message(F.text == "✏️ Serial tahrirlash")
async def edit_series_start(message: Message, state: FSMContext):
    if not is_bosh_admin(message.from_user.id):
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
    if not is_bosh_admin(message.from_user.id):
        await state.clear()
        return
    code = message.text.strip()
    series = get_series(code)
    if not series:
        await message.answer("❌ Bunday serial topilmadi. Qaytadan kiriting:")
        return
    title = series["title"]
    count = get_episode_count(code)
    await state.update_data(series_code=code)
    await state.set_state(AdminStates.series_edit_menu)
    await message.answer(
        f"🎞 {title}\nJami qismlar: {count}\n\nNima qilmoqchisiz?",
        reply_markup=series_edit_menu_kb(),
    )


@dp.message(AdminStates.series_edit_menu, F.text == "➕ Qism qo'shish")
async def edit_series_add_episode(message: Message, state: FSMContext):
    if not is_bosh_admin(message.from_user.id):
        await state.clear()
        return
    await state.update_data(return_state="edit")
    await state.set_state(AdminStates.series_episode_wait)
    await message.answer("Yangi qismni (videoni) yuboring:", reply_markup=episode_add_kb())


@dp.message(AdminStates.series_edit_menu, F.text == "🗑 Qism o'chirish")
async def edit_series_delete_episode_start(message: Message, state: FSMContext):
    if not is_bosh_admin(message.from_user.id):
        await state.clear()
        return
    data = await state.get_data()
    code = data["series_code"]
    episodes = get_episodes(code)
    if not episodes:
        await message.answer("Bu serialda hozircha qismlar yo'q.")
        return
    nums = ", ".join(str(n) for n, _ in episodes)
    await state.set_state(AdminStates.series_edit_delete_episode_wait)
    await message.answer(f"Mavjud qismlar: {nums}\n\nO'chirmoqchi bo'lgan qism raqamini kiriting:")


@dp.message(AdminStates.series_edit_delete_episode_wait)
async def edit_series_delete_episode_confirm(message: Message, state: FSMContext):
    if not is_bosh_admin(message.from_user.id):
        await state.clear()
        return
    data = await state.get_data()
    code = data["series_code"]
    try:
        ep_num = int(message.text.strip())
    except ValueError:
        await message.answer("❗ Iltimos, faqat raqam kiriting.")
        return
    delete_episode(code, ep_num)
    series = get_series(code)
    title = series["title"] if series else code
    count = get_episode_count(code)
    await state.set_state(AdminStates.series_edit_menu)
    await message.answer(
        f"🗑 {ep_num}-qism o'chirildi.\n🎞 {title}\nQolgan qismlar: {count}",
        reply_markup=series_edit_menu_kb(),
    )


@dp.message(AdminStates.series_edit_menu, F.text == "🗑 Serialni butunlay o'chirish")
async def edit_series_delete_all(message: Message, state: FSMContext):
    if not is_bosh_admin(message.from_user.id):
        await state.clear()
        return
    data = await state.get_data()
    code = data["series_code"]
    series = get_series(code)
    title = series["title"] if series else code
    delete_series(code)
    await state.clear()
    await message.answer(f"🗑 Serial butunlay o'chirildi: {title}", reply_markup=kinolar_menu_kb())


# ---- SERIALLAR RO'YXATI (FAQAT BOSH ADMIN) ----
@dp.message(F.text == "📋 Seriallar ro'yxati")
async def list_series(message: Message):
    if not is_bosh_admin(message.from_user.id):
        return
    series_list = get_all_series()
    if not series_list:
        await message.answer("Hozircha seriallar yo'q.")
        return
    lines = ["🎞 Seriallar ro'yxati:\n"]
    for code, title in series_list:
        count = get_episode_count(code)
        lines.append(f"• {code} — {title} ({count} qism)")
    await message.answer("\n".join(lines))


# ---- KANALLAR (FAQAT BOSH ADMIN) ----
@dp.message(F.text == "🔐 Kanallar")
async def kanallar_menu(message: Message):
    if not is_bosh_admin(message.from_user.id):
        return
    await message.answer("🔐 Majburiy kanallar bo'limi:", reply_markup=kanallar_menu_kb())


@dp.message(F.text == "➕ Kanal qo'shish")
async def add_channel_start(message: Message, state: FSMContext):
    if not is_bosh_admin(message.from_user.id):
        return
    await state.set_state(AdminStates.channel_add_wait)
    await message.answer(
        "Kanal username'ini yuboring (masalan: @kanalim).\n"
        "❗ Botni o'sha kanalga admin qilib qo'shishni unutmang!"
    )


@dp.message(AdminStates.channel_add_wait)
async def add_channel_save(message: Message, state: FSMContext):
    if not is_bosh_admin(message.from_user.id):
        await state.clear()
        return
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
    if not is_bosh_admin(message.from_user.id):
        return
    await state.set_state(AdminStates.channel_delete_wait)
    await message.answer("O'chirmoqchi bo'lgan kanal username'ini kiriting (masalan: @kanalim):")


@dp.message(AdminStates.channel_delete_wait)
async def delete_channel_confirm(message: Message, state: FSMContext):
    if not is_bosh_admin(message.from_user.id):
        await state.clear()
        return
    chat_id = message.text.strip()
    delete_channel(chat_id)
    if get_setting("post_channel") == chat_id:
        set_setting("post_channel", "")
    await message.answer(f"🗑 {chat_id} o'chirildi.", reply_markup=kanallar_menu_kb())
    await state.clear()


# ---- KANAL TAHRIRLASH (username'ini almashtirish) — FAQAT BOSH ADMIN ----
@dp.message(F.text == "✏️ Kanal tahrirlash")
async def edit_channel_start(message: Message, state: FSMContext):
    if not is_bosh_admin(message.from_user.id):
        return
    channels = get_all_channels()
    if not channels:
        await message.answer("Hozircha kanal yo'q.")
        return
    text = "🔐 Kanallar:\n\n" + "\n".join(f"• {title} ({cid})" for cid, title in channels)
    text += "\n\n✏️ Tahrirlamoqchi (username'ini almashtirmoqchi) bo'lgan kanalning joriy username'ini kiriting:"
    await state.set_state(AdminStates.channel_edit_select_wait)
    await message.answer(text)


@dp.message(AdminStates.channel_edit_select_wait)
async def edit_channel_select(message: Message, state: FSMContext):
    if not is_bosh_admin(message.from_user.id):
        await state.clear()
        return
    chat_id = message.text.strip()
    channels = dict(get_all_channels())
    if chat_id not in channels:
        await message.answer("❌ Bunday kanal topilmadi. Qaytadan kiriting:")
        return
    await state.update_data(old_chat_id=chat_id)
    await state.set_state(AdminStates.channel_edit_new_wait)
    await message.answer("Yangi username'ini kiriting (masalan: @yangikanal):")


@dp.message(AdminStates.channel_edit_new_wait)
async def edit_channel_save(message: Message, state: FSMContext):
    if not is_bosh_admin(message.from_user.id):
        await state.clear()
        return
    data = await state.get_data()
    old_chat_id = data["old_chat_id"]
    new_chat_id = message.text.strip()
    try:
        chat = await bot.get_chat(new_chat_id)
        delete_channel(old_chat_id)
        add_channel(new_chat_id, chat.title)
        if get_setting("post_channel") == old_chat_id:
            set_setting("post_channel", new_chat_id)
        await message.answer(
            f"✅ Kanal yangilandi: {old_chat_id} → {chat.title} ({new_chat_id})",
            reply_markup=kanallar_menu_kb(),
        )
    except Exception as e:
        await message.answer(f"❌ Xato: bot shu kanalga admin emas yoki username noto'g'ri.\n{e}")
    await state.clear()


# ---- POST KANALINI TANLASH (FAQAT BOSH ADMIN) ----
@dp.message(F.text == "📢 Post kanali")
async def set_post_channel_start(message: Message, state: FSMContext):
    if not is_bosh_admin(message.from_user.id):
        return
    channels = get_all_channels()
    if not channels:
        await message.answer("Avval kamida bitta kanal qo'shing.")
        return
    current = get_setting("post_channel") or "belgilanmagan"
    text = "📢 Mavjud kanallar:\n\n" + "\n".join(f"• {title} ({cid})" for cid, title in channels)
    text += f"\n\nHozirgi post kanali: {current}\n\n"
    text += "Yangi kino/serial qo'shilganda post qaysi kanalga joylansin? Username kiriting:"
    await state.set_state(AdminStates.post_channel_wait)
    await message.answer(text)


@dp.message(AdminStates.post_channel_wait)
async def set_post_channel_save(message: Message, state: FSMContext):
    if not is_bosh_admin(message.from_user.id):
        await state.clear()
        return
    chat_id = message.text.strip()
    channels = dict(get_all_channels())
    if chat_id not in channels:
        await message.answer("❌ Bunday kanal ro'yxatda yo'q. Qaytadan kiriting:")
        return
    set_setting("post_channel", chat_id)
    await message.answer(f"✅ Post kanali o'rnatildi: {channels[chat_id]}", reply_markup=kanallar_menu_kb())
    await state.clear()


@dp.message(F.text == "📋 Kanallar ro'yxati")
async def list_channels(message: Message):
    if not is_bosh_admin(message.from_user.id):
        return
    channels = get_all_channels()
    if not channels:
        await message.answer("Hozircha majburiy kanal yo'q.")
        return
    post_channel = get_setting("post_channel")
    lines = ["🔐 Kanallar:\n"]
    for cid, title in channels:
        mark = " 📢" if cid == post_channel else ""
        lines.append(f"• {title} ({cid}){mark}")
    if post_channel:
        lines.append("\n📢 — postlar shu kanalga avtomatik joylanadi")
    await message.answer("\n".join(lines))


# ---- ADMINLAR (FAQAT BOSH ADMIN UCHUN) ----
@dp.message(F.text == "👤 Adminlar")
async def adminlar_menu(message: Message):
    if not is_bosh_admin(message.from_user.id):
        return
    await message.answer("👤 Adminlarni boshqarish:", reply_markup=adminlar_menu_kb())


@dp.message(F.text == "➕ Admin qo'shish")
async def add_admin_start(message: Message, state: FSMContext):
    if not is_bosh_admin(message.from_user.id):
        return
    await state.set_state(AdminStates.admin_add_wait)
    await message.answer(
        "Yangi admin qilmoqchi bo'lgan foydalanuvchining Telegram ID raqamini yuboring.\n"
        "❗ ID ni bilish uchun o'sha odam @userinfobot ga /start bosishi kerak.\n\n"
        "ℹ️ Qo'shilgan admin faqat kino va serial yuklay oladi, boshqa bo'limlarga kira olmaydi."
    )


@dp.message(AdminStates.admin_add_wait)
async def add_admin_save(message: Message, state: FSMContext):
    if not is_bosh_admin(message.from_user.id):
        await state.clear()
        return
    text = message.text.strip()
    if not text.isdigit():
        await message.answer("❗ Iltimos, faqat raqamlardan iborat ID kiriting.")
        return
    new_admin_id = int(text)
    if is_admin(new_admin_id):
        await message.answer("❗ Bu foydalanuvchi allaqachon admin.", reply_markup=adminlar_menu_kb())
    else:
        add_admin_db(new_admin_id)
        await message.answer(
            f"✅ Yangi admin qo'shildi: {new_admin_id}",
            reply_markup=adminlar_menu_kb(),
        )
    await state.clear()


@dp.message(F.text == "🗑 Admin o'chirish")
async def remove_admin_start(message: Message, state: FSMContext):
    if not is_bosh_admin(message.from_user.id):
        return
    admin_ids = get_all_admin_ids_db()
    if not admin_ids:
        await message.answer("Hozircha qo'shilgan adminlar yo'q.")
        return
    text = "👤 Qo'shilgan adminlar:\n\n" + "\n".join(f"• {uid}" for uid in admin_ids)
    text += "\n\nO'chirmoqchi bo'lgan adminning ID raqamini kiriting:"
    await state.set_state(AdminStates.admin_remove_wait)
    await message.answer(text)


@dp.message(AdminStates.admin_remove_wait)
async def remove_admin_confirm(message: Message, state: FSMContext):
    if not is_bosh_admin(message.from_user.id):
        await state.clear()
        return
    text = message.text.strip()
    if not text.isdigit():
        await message.answer("❗ Iltimos, faqat raqamlardan iborat ID kiriting.")
        return
    target_id = int(text)
    if is_bosh_admin(target_id):
        await message.answer(
            "❗ Bosh adminni o'chirib bo'lmaydi.",
            reply_markup=adminlar_menu_kb(),
        )
    elif target_id not in get_all_admin_ids_db():
        await message.answer("❌ Bu ID qo'shilgan adminlar orasida yo'q.", reply_markup=adminlar_menu_kb())
    else:
        remove_admin_db(target_id)
        await message.answer(f"🗑 Admin o'chirildi: {target_id}", reply_markup=adminlar_menu_kb())
    await state.clear()


@dp.message(F.text == "📋 Adminlar ro'yxati")
async def list_admins(message: Message):
    if not is_bosh_admin(message.from_user.id):
        return
    lines = ["👤 Adminlar ro'yxati:\n", f"👑 Bosh admin: {', '.join(str(a) for a in ADMIN_IDS)}"]
    extra_admins = get_all_admin_ids_db()
    if extra_admins:
        lines.append("\nQo'shilgan adminlar (faqat yuklash huquqi):")
        lines.extend(f"• {uid}" for uid in extra_admins)
    else:
        lines.append("\nQo'shilgan adminlar yo'q.")
    await message.answer("\n".join(lines))


# ================= QIDIRUV NATIJALARI (RAQAMLI TUGMALAR) =================
def search_all_by_title(query, limit=10):
    movies = [("movie", code, title) for code, title in search_movies_by_title(query, limit)]
    series = [("series", code, title) for code, title in search_series_by_title(query, limit)]
    return (movies + series)[:limit]


def search_results_kb(results) -> InlineKeyboardMarkup:
    buttons = []
    row = []
    for i, (kind, code, title) in enumerate(results, start=1):
        row.append(InlineKeyboardButton(text=str(i), callback_data=f"pick:{kind}:{code}"))
        if len(row) == 5:
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
            caption = build_caption(movie, kind="movie")
            await call.message.answer_video(video=movie["file_id"], caption=caption)
            increment_movie_views(code)
            await call.answer()
            return

    elif kind == "series":
        await call.answer()
        found = await send_series_episode_list(call.message, code, page=0, edit=False)
        if found:
            return

    await call.answer("❌ Topilmadi, o'chirilgan bo'lishi mumkin.", show_alert=True)


# ================= KINO/SERIAL KODI YOKI NOMI QABUL QILISH =================
@dp.message(F.text)
async def code_handler(message: Message):
    if not await is_subscribed(message.from_user.id):
        await message.answer("Avval kanallarga obuna bo'ling. 👇", reply_markup=channels_subscribe_kb())
        return

    query = message.text.strip()

    if await send_content_by_code(message, query):
        return

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
    global BOT_USERNAME
    db_init()
    me = await bot.get_me()
    BOT_USERNAME = me.username
    logging.info(f"Bot ishga tushdi: @{BOT_USERNAME}")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
