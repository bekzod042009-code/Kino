import asyncio
import logging
import sqlite3
from datetime import datetime

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
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

# Admin qila oladigan foydalanuvchilar ID'lari (o'zingiznikini kiriting)
# ID ni bilish uchun @userinfobot ga /start bosing
ADMIN_IDS = [8012700729]
# =====================================

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

DB_PATH = "kino_bot.db"


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
    cur.execute("""CREATE TABLE IF NOT EXISTS channels (
        chat_id TEXT PRIMARY KEY,
        title TEXT
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


def add_channel(chat_id, title):
    db_run("INSERT OR REPLACE INTO channels (chat_id, title) VALUES (?, ?)", (chat_id, title))


def delete_channel(chat_id):
    db_run("DELETE FROM channels WHERE chat_id=?", (chat_id,))


def get_all_channels():
    return db_run("SELECT chat_id, title FROM channels")


# ---------------- FSM HOLATLARI ----------------
class AdminStates(StatesGroup):
    broadcast_wait = State()
    movie_code_wait = State()
    movie_file_wait = State()
    movie_delete_wait = State()
    channel_add_wait = State()
    channel_delete_wait = State()


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


# ---------------- KLAVIATURALAR ----------------
def admin_menu_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📊 Statistika"), KeyboardButton(text="✉️ Xabar yuborish")],
            [KeyboardButton(text="🎬 Kinolar"), KeyboardButton(text="🔐 Kanallar")],
            [KeyboardButton(text="⬅️ Chiqish")],
        ],
        resize_keyboard=True,
    )


def kinolar_menu_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="➕ Kino qo'shish"), KeyboardButton(text="🗑 Kino o'chirish")],
            [KeyboardButton(text="📋 Kinolar ro'yxati")],
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
async def start_handler(message: Message):
    add_user(message.from_user.id, message.from_user.first_name, message.from_user.username)

    if await is_subscribed(message.from_user.id):
        await message.answer(
            f"🎉 Assalomu alaykum, {message.from_user.first_name}!\n\n🎬 Kino kodini kiriting."
        )
    else:
        await message.answer(
            "Botdan foydalanish uchun quyidagi kanallarga obuna bo'ling "
            "va Tekshirish tugmasini bosing. 👇",
            reply_markup=channels_subscribe_kb(),
        )


@dp.callback_query(F.data == "check_sub")
async def check_sub_handler(call: CallbackQuery):
    if await is_subscribed(call.from_user.id):
        await call.message.edit_text("✅ Obuna tasdiqlandi!\n\n🎬 Endi kino kodini kiriting.")
    else:
        await call.answer("❌ Hali barcha kanallarga obuna bo'lmadingiz!", show_alert=True)


# ================= ADMIN PANEL =================
@dp.message(F.text == "/admin")
async def admin_entry(message: Message):
    if not is_admin(message.from_user.id):
        return
    await message.answer("👮 Admin paneliga xush kelibsiz!", reply_markup=admin_menu_kb())


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
    await message.answer("Admin panel:", reply_markup=admin_menu_kb())


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
    await message.answer(f"✅ Yuborildi: {sent}\n❌ Yuborilmadi: {failed}", reply_markup=admin_menu_kb())


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
    await state.set_state(AdminStates.movie_file_wait)
    await message.answer("Endi videoni (kino faylini) yuboring:")


@dp.message(AdminStates.movie_file_wait, F.video)
async def add_movie_file(message: Message, state: FSMContext):
    data = await state.get_data()
    code = data["code"]
    file_id = message.video.file_id
    title = message.caption or f"Kino {code}"
    add_movie(code, file_id, title)
    await state.clear()
    await message.answer(f"✅ Kino saqlandi!\nKod: {code}", reply_markup=kinolar_menu_kb())


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


# ================= KINO KODI QABUL QILISH =================
# Bu handler eng oxirida turishi shart — aks holda admin buyruqlari bilan
# to'qnashib qoladi (FSM holatlari va aniq matnli tugmalar avval ushlanadi).
@dp.message(F.text)
async def code_handler(message: Message):
    if not await is_subscribed(message.from_user.id):
        await message.answer("Avval kanallarga obuna bo'ling. 👇", reply_markup=channels_subscribe_kb())
        return

    code = message.text.strip()
    movie = get_movie(code)

    if movie:
        _, file_id, title = movie
        await message.answer_video(video=file_id, caption=f"🎬 {title}")
    else:
        await message.answer("❌ Bunday kod topilmadi. Qaytadan urinib ko'ring.")


# ================= ISHGA TUSHIRISH =================
async def main():
    db_init()
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
