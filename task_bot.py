import logging
import sqlite3
from datetime import datetime, timedelta
from telegram import (
    Update,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardMarkup,
    BotCommand
)
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    ConversationHandler,
    filters,
)
import os
from dotenv import load_dotenv

# =========================
# ЛОГИ
# =========================
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# =========================
# ЗАГРУЗКА ТОКЕНА
# =========================
load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")

# =========================
# СТАТУСЫ КОНВЕРСАЦИИ
# =========================
CATEGORY, TASK_NAME, DEADLINE = range(3)

# =========================
# КАТЕГОРИИ
# =========================
CATEGORIES = ["Аналитика", "Разработка", "Тестирование", "Другое"]


# =========================
# БАЗА ДАННЫХ
# =========================
def init_db():
    conn = sqlite3.connect("tasks.db")
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            local_id INTEGER NOT NULL,
            category TEXT,
            task_name TEXT NOT NULL,
            deadline TEXT,
            completed INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            completed_at TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()


# =========================
# ГЛАВНОЕ МЕНЮ
# =========================
MAIN_MENU = [
    ["➕ Добавить задачу"],
    ["📋 Мои задачи", "✅ Выполненные"]
]


def get_main_menu():
    return ReplyKeyboardMarkup(MAIN_MENU, resize_keyboard=True)


# =========================
# КОМАНДА /start
# =========================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await context.bot.set_my_commands([
        BotCommand("start", "Главное меню"),
        BotCommand("add", "Добавить задачу"),
        BotCommand("mytasks", "Мои задачи"),
        BotCommand("completed", "Выполненные задачи")
    ])

    await update.message.reply_text(
        "Привет! Я твой Task Tracker.\nВыбери действие:",
        reply_markup=get_main_menu()
    )


# =========================
# ДОБАВЛЕНИЕ ЗАДАЧИ
# =========================
async def add_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[InlineKeyboardButton(cat, callback_data=cat)] for cat in CATEGORIES]
    reply_markup = InlineKeyboardMarkup(keyboard)
    if update.message:
        await update.message.reply_text("Выбери категорию задачи:", reply_markup=reply_markup)
    else:
        await update.callback_query.edit_message_text("Выбери категорию задачи:", reply_markup=reply_markup)
    return CATEGORY


async def add_category(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    context.user_data['category'] = query.data
    await query.answer()
    await query.edit_message_text("✍ Напиши название задачи:")
    return TASK_NAME


async def add_task_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['task_name'] = update.message.text
    await update.message.reply_text(
        "⏰ Укажи дедлайн в формате дд.мм.гггг чч:мм или напиши 'завтра', или оставь пустым:"
    )
    return DEADLINE


async def add_deadline(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    category = context.user_data['category']
    task_name = context.user_data['task_name']

    # Обработка дедлайна
    if text.lower() == "завтра":
        deadline = (datetime.now() + timedelta(days=1)).isoformat()
    else:
        try:
            deadline = datetime.strptime(text, "%d.%m.%Y %H:%M").isoformat()
        except ValueError:
            deadline = None

    user_id = update.effective_user.id

    # Определяем локальный номер задачи для пользователя
    conn = sqlite3.connect("tasks.db")
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM tasks WHERE user_id=?", (user_id,))
    task_count = cursor.fetchone()[0]
    local_id = task_count + 1

    cursor.execute(
        "INSERT INTO tasks (user_id, local_id, category, task_name, deadline) VALUES (?, ?, ?, ?, ?)",
        (user_id, local_id, category, task_name, deadline)
    )
    conn.commit()
    conn.close()

    await update.message.reply_text(f"✅ Задача добавлена: {task_name} ({category})", reply_markup=get_main_menu())
    return ConversationHandler.END


async def add_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Добавление задачи отменено.", reply_markup=get_main_menu())
    return ConversationHandler.END


# =========================
# МОИ ЗАДАЧИ
# =========================
async def mytasks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    conn = sqlite3.connect("tasks.db")
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, local_id, category, task_name, deadline FROM tasks WHERE user_id=? AND completed=0 ORDER BY local_id",
        (user_id,)
    )
    tasks = cursor.fetchall()
    conn.close()

    if not tasks:
        await update.message.reply_text("Нет активных задач.", reply_markup=get_main_menu())
        return

    for task_id, local_id, category, task_name, deadline in tasks:
        deadline_str = datetime.fromisoformat(deadline).strftime("%d.%m.%Y %H:%M") if deadline else "–"
        text = f"📌 <b>#{local_id} {task_name}</b>\n📂 Категория: {category}\n⏰ Дедлайн: {deadline_str}"

        keyboard = [
            [
                InlineKeyboardButton("✅ Выполнено", callback_data=f"done_{task_id}"),
                InlineKeyboardButton("🗑 Удалить", callback_data=f"delete_{task_id}"),
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode="HTML")


# =========================
# ВЫПОЛНЕННЫЕ ЗАДАЧИ
# =========================
async def completed(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    conn = sqlite3.connect("tasks.db")
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, local_id, category, task_name, completed_at FROM tasks WHERE user_id=? AND completed=1 ORDER BY local_id",
        (user_id,)
    )
    tasks = cursor.fetchall()
    conn.close()

    if not tasks:
        await update.message.reply_text("Нет выполненных задач.", reply_markup=get_main_menu())
        return

    for task_id, local_id, category, task_name, completed_at in tasks:
        completed_str = datetime.fromisoformat(completed_at).strftime("%d.%m.%Y %H:%M") if completed_at else "–"
        text = f"✅ <b>#{local_id} {task_name}</b>\n📂 Категория: {category}\n📅 Завершено: {completed_str}"

        keyboard = [
            [
                InlineKeyboardButton("↩ Вернуть в активные", callback_data=f"restore_{task_id}"),
                InlineKeyboardButton("🗑 Удалить", callback_data=f"delete_{task_id}"),
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode="HTML")


# =========================
# ОБРАБОТКА INLINE-КНОПОК
# =========================
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = query.from_user.id

    conn = sqlite3.connect("tasks.db")
    cursor = conn.cursor()

    if data.startswith("done_"):
        task_id = int(data.split("_")[1])
        cursor.execute(
            "UPDATE tasks SET completed=1, completed_at=CURRENT_TIMESTAMP WHERE id=? AND user_id=?",
            (task_id, user_id),
        )
        conn.commit()
        await query.edit_message_text("✅ Задача выполнена!", reply_markup=None)

    elif data.startswith("delete_"):
        task_id = int(data.split("_")[1])
        cursor.execute("DELETE FROM tasks WHERE id=? AND user_id=?", (task_id, user_id))
        conn.commit()

        # Перенумеруем оставшиеся задачи пользователя
        cursor.execute("SELECT id FROM tasks WHERE user_id=? ORDER BY created_at", (user_id,))
        remaining = cursor.fetchall()
        for idx, (r_id,) in enumerate(remaining, start=1):
            cursor.execute("UPDATE tasks SET local_id=? WHERE id=?", (idx, r_id))
        conn.commit()
        await query.edit_message_text("🗑 Задача удалена!", reply_markup=None)

    elif data.startswith("restore_"):
        task_id = int(data.split("_")[1])
        cursor.execute("UPDATE tasks SET completed=0, completed_at=NULL WHERE id=? AND user_id=?", (task_id, user_id))
        conn.commit()
        await query.edit_message_text("↩ Задача возвращена в активные!", reply_markup=None)

    conn.close()


# =========================
# ОБРАБОТКА КНОПОК МЕНЮ (ReplyKeyboard)
# =========================
async def menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "➕ Добавить задачу":
        return await add_start(update, context)
    elif text == "📋 Мои задачи":
        return await mytasks(update, context)
    elif text == "✅ Выполненные":
        return await completed(update, context)


# =========================
# MAIN
# =========================
def main():
    init_db()
    app = Application.builder().token(TOKEN).build()

    # Команды
    app.add_handler(CommandHandler("start", start))

    # Конвейер добавления задачи
    conv_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^➕ Добавить задачу$"), add_start),
                      CallbackQueryHandler(add_start, pattern="^add$")],
        states={
            CATEGORY: [CallbackQueryHandler(add_category, pattern="|".join(CATEGORIES))],
            TASK_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_task_name)],
            DEADLINE: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_deadline)],
        },
        fallbacks=[CommandHandler("cancel", add_cancel)],
    )
    app.add_handler(conv_handler)

    # Обработчик меню ReplyKeyboard
    app.add_handler(MessageHandler(filters.Regex("^(📋 Мои задачи|✅ Выполненные)$"), menu_handler))

    # Inline-кнопки
    app.add_handler(CallbackQueryHandler(button_handler, pattern="^(done_|delete_|restore_)"))

    app.run_polling()


if __name__ == "__main__":
    main()
