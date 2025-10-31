import os
import logging
import sqlite3
from datetime import datetime, date, time, timezone, timedelta

# Import library python-telegram-bot
# Pastikan Anda sudah menginstalnya: pip install python-telegram-bot
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode  # <-- INI PERBAIKANNYA
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ConversationHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# Setup logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# Nama file database
DB_NAME = "tasks.db"

# State untuk ConversationHandler
TASK_NAME, DEADLINE = range(2)

# === FUNGSI DATABASE ===

def get_db_connection():
    """Membuat koneksi ke database SQLite."""
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn

def setup_database():
    """Membuat tabel 'tasks' jika belum ada."""
    conn = get_db_connection()
    with conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                task_name TEXT NOT NULL,
                deadline TEXT NOT NULL,
                is_complete INTEGER DEFAULT 0
            );
            """
        )
    conn.close()
    logger.info("Database berhasil disiapkan.")

def calculate_days_remaining(deadline_str):
    """Menghitung sisa hari berdasarkan string deadline 'YYYY-MM-DD'."""
    today = date.today()
    try:
        deadline_date = datetime.strptime(deadline_str, "%Y-MM-d").date()
        days_remaining = (deadline_date - today).days
        return days_remaining
    except ValueError:
        logger.warning(f"Format tanggal salah: {deadline_str}")
        return None

# === FUNGSI JOB HARIAN ===

async def send_daily_reminders(context: ContextTypes.DEFAULT_TYPE):
    """Job harian untuk mengirim pengingat semua tugas yang belum selesai."""
    logger.info("Menjalankan job pengingat harian...")
    conn = get_db_connection()
    try:
        with conn:
            tasks = conn.execute(
                "SELECT id, chat_id, task_name, deadline FROM tasks WHERE is_complete = 0"
            ).fetchall()

        for task in tasks:
            days_remaining = calculate_days_remaining(task["deadline"])

            if days_remaining is None:
                continue

            if days_remaining < 0:
                # Tugas sudah lewat deadline, tandai selesai agar tidak diingatkan lagi
                with conn:
                    conn.execute("UPDATE tasks SET is_complete = 1 WHERE id = ?", (task["id"],))
                logger.info(f"Tugas '{task['task_name']}' (ID: {task['id']}) sudah lewat deadline, ditandai selesai.")
            
            elif days_remaining >= 0:
                # Kirim pengingat
                message = (
                    f"🔔 *Pengingat Tugas!* 🔔\n\n"
                    f"Tugas: *{task['task_name']}*\n"
                    f"Deadline: *{task['deadline']}*\n"
                    f"Sisa Hari: *{days_remaining} hari lagi!*\n\n"
                    "Jangan lupa dikerjakan ya! Semangat! 💪"
                )
                try:
                    await context.bot.send_message(
                        chat_id=task["chat_id"],
                        text=message,
                        parse_mode=ParseMode.MARKDOWN,
                    )
                except Exception as e:
                    logger.error(f"Gagal mengirim pesan ke chat_id {task['chat_id']}: {e}")

    except Exception as e:
        logger.error(f"Error pada job pengingat harian: {e}")
    finally:
        conn.close()

# === HANDLER PERINTAH ===

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler untuk perintah /start."""
    user = update.effective_user
    await update.message.reply_html(
        f"Halo, {user.mention_html()}!\n\n"
        "Saya adalah bot pengingat tugas. Saya akan membantumu mengingat deadline.\n\n"
        "Perintah yang tersedia:\n"
        "/tugasbaru - Menambah tugas baru\n"
        "/listtugas - Melihat daftar tugas yang belum selesai\n"
        "/selesai - Menandai tugas sebagai selesai\n"
    )

async def listtugas(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler untuk perintah /listtugas."""
    chat_id = update.effective_chat.id
    conn = get_db_connection()
    
    try:
        tasks = conn.execute(
            "SELECT task_name, deadline FROM tasks WHERE chat_id = ? AND is_complete = 0",
            (chat_id,),
        ).fetchall()

        if not tasks:
            await update.message.reply_text("Hore! Tidak ada tugas yang belum selesai.")
            return

        message = "Daftar Tugas Anda yang Belum Selesai:\n\n"
        for i, task in enumerate(tasks, 1):
            days_remaining = calculate_days_remaining(task["deadline"])
            if days_remaining is not None:
                message += (
                    f"*{i}. {task['task_name']}*\n"
                    f"   Deadline: {task['deadline']} (Sisa {days_remaining} hari)\n"
                )
        
        await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)

    except Exception as e:
        logger.error(f"Error di /listtugas: {e}")
        await update.message.reply_text("Maaf, terjadi kesalahan saat mengambil daftar tugas.")
    finally:
        conn.close()

# --- Flow Tandai Selesai ---

async def selesai_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Memulai flow /selesai, menampilkan tugas untuk dipilih."""
    chat_id = update.effective_chat.id
    conn = get_db_connection()
    
    try:
        tasks = conn.execute(
            "SELECT id, task_name FROM tasks WHERE chat_id = ? AND is_complete = 0",
            (chat_id,),
        ).fetchall()

        if not tasks:
            await update.message.reply_text("Tidak ada tugas yang bisa ditandai selesai.")
            return

        keyboard = []
        for task in tasks:
            # callback_data harus unik, kita gunakan 'selesai_{id_tugas}'
            button = [
                InlineKeyboardButton(
                    task["task_name"], callback_data=f"selesai_{task['id']}"
                )
            ]
            keyboard.append(button)

        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            "Pilih tugas yang sudah selesai:", reply_markup=reply_markup
        )

    except Exception as e:
        logger.error(f"Error di /selesai: {e}")
        await update.message.reply_text("Maaf, terjadi kesalahan.")
    finally:
        conn.close()

async def selesai_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Menangani callback query dari tombol /selesai."""
    query = update.callback_query
    await query.answer()  # Memberi tahu Telegram bahwa tombol sudah diproses

    try:
        task_id = int(query.data.split("_")[1])
        chat_id = query.effective_chat.id

        conn = get_db_connection()
        task_name = ""
        with conn:
            # Ambil nama tugas untuk pesan konfirmasi
            cursor = conn.execute("SELECT task_name FROM tasks WHERE id = ? AND chat_id = ?", (task_id, chat_id))
            task = cursor.fetchone()
            
            if task:
                task_name = task["task_name"]
                # Update status tugas
                conn.execute(
                    "UPDATE tasks SET is_complete = 1 WHERE id = ? AND chat_id = ?",
                    (task_id, chat_id),
                )
                await query.edit_message_text(
                    text=f"Mantap! Tugas '{task_name}' telah ditandai selesai."
                )
            else:
                await query.edit_message_text(text="Maaf, tugas tidak ditemukan.")

    except Exception as e:
        logger.error(f"Error di selesai_callback: {e}")
        await query.edit_message_text(text="Terjadi kesalahan.")
    finally:
        if 'conn' in locals() and conn:
            conn.close()

# --- Flow /tugasbaru (Conversation) ---

async def tugasbaru_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Memulai conversation /tugasbaru."""
    await update.message.reply_text(
        "Oke, mari tambahkan tugas baru.\n"
        "Apa nama tugasnya? (Ketik /cancel untuk batal)"
    )
    return TASK_NAME

async def tugasbaru_get_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Menyimpan nama tugas dan meminta deadline."""
    task_name = update.message.text
    context.user_data["task_name"] = task_name
    
    await update.message.reply_text(
        f"Nama tugas: *{task_name}*\n\n"
        "Kapan deadlinenya? (Format: *YYYY-MM-DD*, contoh: 2025-12-31)\n"
        "(Ketik /cancel untuk batal)",
        parse_mode=ParseMode.MARKDOWN,
    )
    return DEADLINE

async def tugasbaru_get_deadline(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Menyimpan deadline dan mengakhiri conversation."""
    deadline_text = update.message.text
    task_name = context.user_data.get("task_name")
    chat_id = update.effective_chat.id

    # Validasi format tanggal
    try:
        datetime.strptime(deadline_text, "%Y-%m-%d")
    except ValueError:
        await update.message.reply_text(
            "Format tanggal salah. Harap gunakan *YYYY-MM-DD*.\n"
            "Kapan deadlinenya?",
            parse_mode=ParseMode.MARKDOWN,
        )
        return DEADLINE  # Tetap di state DEADLINE

    # Simpan ke database
    conn = get_db_connection()
    try:
        with conn:
            conn.execute(
                "INSERT INTO tasks (chat_id, task_name, deadline) VALUES (?, ?, ?)",
                (chat_id, task_name, deadline_text),
            )
        
        await update.message.reply_text(
            f"Berhasil! Tugas '{task_name}' dengan deadline {deadline_text} telah disimpan."
        )
        logger.info(f"Tugas baru disimpan: {task_name} oleh chat_id {chat_id}")

    except Exception as e:
        logger.error(f"Gagal menyimpan tugas: {e}")
        await update.message.reply_text("Maaf, terjadi kesalahan saat menyimpan tugas.")
    finally:
        conn.close()
        context.user_data.clear()
        return ConversationHandler.END

async def tugasbaru_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Membatalkan conversation /tugasbaru."""
    context.user_data.clear()
    await update.message.reply_text("Penambahan tugas baru dibatalkan.")
    return ConversationHandler.END

# === FUNGSI MAIN ===

def main() -> None:
    """Fungsi utama untuk menjalankan bot."""
    
    # Ambil TOKEN Bot dari Environment Variable
    TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not TOKEN:
        logger.critical(
            "Token bot tidak ditemukan! "
            "Silakan atur environment variable 'TELEGRAM_BOT_TOKEN'."
        )
        return

    # Pastikan database dan tabel sudah siap
    setup_database()

    # Buat Application
    application = Application.builder().token(TOKEN).build()

    # --- Setup Conversation Handler untuk /tugasbaru ---
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("tugasbaru", tugasbaru_start)],
        states={
            TASK_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, tugasbaru_get_name)
            ],
            DEADLINE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, tugasbaru_get_deadline)
            ],
        },
        fallbacks=[CommandHandler("cancel", tugasbaru_cancel)],
    )
    
    # Daftarkan semua handler
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("listtugas", listtugas))
    application.add_handler(CommandHandler("selesai", selesai_start))
    application.add_handler(CallbackQueryHandler(selesai_callback, pattern="^selesai_"))
    application.add_handler(conv_handler) # Tambahkan conversation handler

    # --- Setup Job Queue (Pengingat Harian) ---
    job_queue = application.job_queue
    
    # Tentukan zona waktu (WIB = UTC+7)
    wib_tz = timezone(timedelta(hours=7))
    
    # Atur job untuk berjalan setiap hari jam 8:00 pagi WIB
    daily_time = time(hour=8, minute=0, second=0, tzinfo=wib_tz)
    job_queue.run_daily(
        send_daily_reminders,
        time=daily_time
    )
    
    logger.info("Bot siap dijalankan... Job harian diatur jam 8:00 WIB.")

    # Mulai bot
    application.run_polling()


if __name__ == "__main__":
    main()

