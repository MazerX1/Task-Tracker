import logging
import os
import sqlite3
from datetime import datetime, timedelta

from dotenv import load_dotenv
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup
)
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ContextTypes,
    ConversationHandler
)

# ================== НАСТРОЙКА ==================
load_dotenv()
logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

CHOOSING_CATEGORY, TASK_NAME, TASK_DEADLINE = range(3)

CATEGORIES = {
    "analytics": "📊 Аналитика",
    "development": "💻 Разработка",
    "design": "🎨 Дизайн",
    "marketing": "📈 Маркетинг",
    "meeting": "🤝 Встречи",
    "other": "📌 Прочее"
}

# ================== КЛАСС ДЛЯ РАБОТЫ С БД ==================
class TaskTrackerBot:
    def __init__(self):
        self.conn = sqlite3.connect("tasks.db", check_same_thread=False)
        self.init_db()

    def init_db(self):
        c = self.conn.cursor()
        c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            last_name TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )""")
        c.execute("""
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            category TEXT,
            task_name TEXT,
            deadline TIMESTAMP,
            completed BOOLEAN DEFAULT FALSE,
            completed_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (user_id)
        )""")
        self.conn.commit()

    def add_user(self, user):
        self.conn.execute(
            "INSERT OR IGNORE INTO users (user_id, username, first_name, last_name) VALUES (?, ?, ?, ?)",
            (user.id, user.username or "", user.first_name or "", user.last_name or "")
        )
        self.conn.commit()

    def add_task(self, user_id, category, task_name, deadline: datetime):
        cur = self.conn.cursor()
        cur.execute(
            "INSERT INTO tasks (user_id, category, task_name, deadline) VALUES (?, ?, ?, ?)",
            (user_id, category, task_name, deadline.isoformat())
        )
        self.conn.commit()
        return cur.lastrowid

    def get_tasks(self, user_id, completed=False):
        cur = self.conn.cursor()
        cur.execute(
            "SELECT id, category, task_name, deadline, completed_at FROM tasks WHERE user_id=? AND completed=? ORDER BY deadline ASC",
            (user_id, completed)
        )
        return cur.fetchall()

    def complete_task(self, task_id, user_id):
        cur = self.conn.cursor()
        cur.execute(
            "UPDATE tasks SET completed=TRUE, completed_at=CURRENT_TIMESTAMP WHERE id=? AND user_id=?",
            (task_id, user_id)
        )
        self.conn.commit()
        return cur.rowcount > 0

    def delete_task(self, task_id, user_id):
        cur = self.conn.cursor()
        cur.execute("DELETE FROM tasks WHERE id=? AND user_id=?", (task_id, user_id))
        self.conn.commit()
        return cur.rowcount > 0


bot = TaskTrackerBot()

# ================== ОБРАБОТЧИКИ ==================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    bot.add_user(user)

    text = (
        f"👋 Привет, {user.first_name}!\n\n"
        "Я бот-задачник. Вот что я умею:\n"
        "📝 /addtask – добавить задачу\n"
        "📋 /mytasks – показать активные задачи\n"
        "✅ /completed – показать выполненные\n"
        "🆘 /help – помощь"
    )
    keyboard = [
        [InlineKeyboardButton("📝 Добавить задачу", callback_data="add_task")],
        [InlineKeyboardButton("📋 Мои задачи", callback_data="show_tasks")],
        [InlineKeyboardButton("✅ Выполненные", callback_data="show_completed")]
    ]
    await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📋 Доступные команды:\n"
        "/start – начать\n"
        "/addtask – добавить задачу\n"
        "/mytasks – активные задачи\n"
        "/completed – выполненные\n"
        "/cancel – отменить добавление"
    )


# ---- Добавление задачи ----
async def add_task_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    buttons = [[InlineKeyboardButton(v, callback_data=f"category_{k}")]
               for k, v in CATEGORIES.items()]
    await update.message.reply_text("Выберите категорию:", reply_markup=InlineKeyboardMarkup(buttons))
    return CHOOSING_CATEGORY


async def category_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    category = query.data.replace("category_", "")
    context.user_data["category"] = category
    await query.edit_message_text(f"Категория: {CATEGORIES[category]}\nВведите название задачи:")
    return TASK_NAME


async def task_name_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["task_name"] = update.message.text
    await update.message.reply_text("📅 Введите дедлайн (например: '25.12.2024 18:00' или 'Завтра'):")
    return TASK_DEADLINE


async def deadline_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    try:
        deadline = parse_deadline(update.message.text)
        task_id = bot.add_task(user_id, context.user_data["category"], context.user_data["task_name"], deadline)
        await update.message.reply_text(
            f"✅ Задача добавлена!\n\n"
            f"📁 {CATEGORIES[context.user_data['category']]}\n"
            f"📝 {context.user_data['task_name']}\n"
            f"📅 {deadline.strftime('%d.%m.%Y %H:%M')}\n"
            f"ID: #{task_id}"
        )
    except ValueError as e:
        await update.message.reply_text(f"❌ {e}\nПопробуйте снова:")
        return TASK_DEADLINE
    context.user_data.clear()
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Добавление задачи отменено")
    context.user_data.clear()
    return ConversationHandler.END


# ---- Список задач ----
async def show_tasks(update: Update, context: ContextTypes.DEFAULT_TYPE, completed=False):
    user_id = update.effective_user.id
    tasks = bot.get_tasks(user_id, completed)

    if not tasks:
        await update.message.reply_text("📭 Нет задач")
        return

    text = "✅ Выполненные:\n\n" if completed else "📋 Активные задачи:\n\n"
    for t in tasks:
        tid, cat, name, deadline, done = t
        deadline_dt = datetime.fromisoformat(deadline) if deadline else None
        deadline_str = deadline_dt.strftime("%d.%m.%Y %H:%M") if deadline_dt else "–"
        if not completed:
            text += f"#{tid} {CATEGORIES.get(cat, cat)} – {name}\nДедлайн: {deadline_str}\n\n"
        else:
            done_dt = datetime.fromisoformat(done) if done else None
            done_str = done_dt.strftime("%d.%m.%Y %H:%M") if done_dt else "?"
            text += f"#{tid} {CATEGORIES.get(cat, cat)} – {name}\n✅ Выполнено: {done_str}\n\n"
    await update.message.reply_text(text)


async def mytasks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_tasks(update, context, completed=False)


async def completed(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_tasks(update, context, completed=True)


# ---- Кнопки ----
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    data = query.data

    if data == "add_task":
        await add_task_start(update, context)
    elif data == "show_tasks":
        await show_tasks(update, context, completed=False)
    elif data == "show_completed":
        await show_tasks(update, context, completed=True)
    elif data.startswith("complete_"):
        tid = int(data.replace("complete_", ""))
        if bot.complete_task(tid, user_id):
            await query.edit_message_text("✅ Задача выполнена!")
    elif data.startswith("delete_"):
        tid = int(data.replace("delete_", ""))
        if bot.delete_task(tid, user_id):
            await query.edit_message_text("🗑️ Задача удалена!")


# ================== ПАРСИНГ ДЕДЛАЙНОВ ==================
def parse_deadline(text: str) -> datetime:
    now = datetime.now()
    t = text.lower().strip()
    if t == "завтра":
        return (now + timedelta(days=1)).replace(hour=23, minute=59)
    for fmt in ["%d.%m.%Y %H:%M", "%d.%m.%Y", "%H:%M"]:
        try:
            dt = datetime.strptime(t, fmt)
            if fmt == "%H:%M":
                result = now.replace(hour=dt.hour, minute=dt.minute)
                return result if result > now else result + timedelta(days=1)
            if fmt == "%d.%m.%Y":
                return dt.replace(hour=23, minute=59)
            return dt
        except ValueError:
            continue
    raise ValueError("Не могу распознать дедлайн")


# ================== MAIN ==================
def main():
    token = os.getenv("BOT_TOKEN")
    if not token:
        print("❌ Установите BOT_TOKEN в .env")
        return

    app = Application.builder().token(token).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("addtask", add_task_start)],
        states={
            CHOOSING_CATEGORY: [CallbackQueryHandler(category_chosen, pattern="^category_")],
            TASK_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, task_name_received)],
            TASK_DEADLINE: [MessageHandler(filters.TEXT & ~filters.COMMAND, deadline_received)]
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("mytasks", mytasks))
    app.add_handler(CommandHandler("completed", completed))
    app.add_handler(conv_handler)
    app.add_handler(CallbackQueryHandler(button_handler))

    print("✅ Task Tracker Bot запущен")
    app.run_polling()


if __name__ == "__main__":
    main()
