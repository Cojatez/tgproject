import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    CallbackQueryHandler,
    ConversationHandler,
    MessageHandler,
    filters,
)
import sqlite3
from datetime import datetime
import matplotlib.pyplot as plt
from io import BytesIO
from pytz import timezone
import uuid
import csv

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

TOKEN = "YOUR_TELEGRAM_BOT_TOKEN"
DB_NAME = "organizer.db"
TIMEZONE = timezone("Europe/Moscow")

(
    TASK_STATES, EXPENSE_STATES, NOTE_STATES, REMINDER_STATES,
    SET_TASK, SET_PRIORITY, SET_DUE_DATE,
    SET_EXPENSE_AMOUNT, SET_EXPENSE_CATEGORY,
    SET_NOTE_TEXT, SET_NOTE_TAGS,
    SET_REMINDER_TEXT, SET_REMINDER_TIME
) = range(13)


def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()

    c.execute('''CREATE TABLE IF NOT EXISTS tasks
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  user_id INTEGER,
                  task TEXT,
                  priority INTEGER,
                  created DATETIME,
                  due DATETIME,
                  completed BOOLEAN)''')

    c.execute('''CREATE TABLE IF NOT EXISTS expenses
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  user_id INTEGER,
                  amount REAL,
                  category TEXT,
                  created DATETIME)''')

    c.execute('''CREATE TABLE IF NOT EXISTS notes
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  user_id INTEGER,
                  text TEXT,
                  tags TEXT,
                  created DATETIME)''')

    c.execute('''CREATE TABLE IF NOT EXISTS reminders
                 (id TEXT PRIMARY KEY,
                  user_id INTEGER,
                  text TEXT,
                  trigger_time DATETIME)''')

    conn.commit()
    conn.close()


init_db()


def get_main_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Задачи", callback_data='tasks'),
         InlineKeyboardButton("Расходы", callback_data='expenses')],
        [InlineKeyboardButton("Заметки", callback_data='notes'),
         InlineKeyboardButton("Напоминания", callback_data='reminders')]
    ])


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text('Действие отменено', reply_markup=get_main_menu())
    return ConversationHandler.END


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text('Главное меню:', reply_markup=get_main_menu())


def get_tasks(user_id: int):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT * FROM tasks WHERE user_id=? AND completed=0 ORDER BY due", (user_id,))
    tasks = c.fetchall()
    conn.close()
    return tasks


def add_task(user_id: int, task: str, priority: int, due: datetime):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("INSERT INTO tasks (user_id, task, priority, created, due, completed) VALUES (?, ?, ?, ?, ?, 0)",
              (user_id, task, priority, datetime.now(), due))
    conn.commit()
    conn.close()


async def tasks_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    keyboard = [
        [InlineKeyboardButton("Добавить задачу", callback_data='add_task'),
         InlineKeyboardButton("Мои задачи", callback_data='list_tasks')],
        [InlineKeyboardButton("Назад", callback_data='main_menu')]
    ]
    await query.edit_message_text(
        text="Меню задач:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def add_task_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(text="Введите описание задачи:")
    return SET_TASK


async def set_task(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['task'] = update.message.text
    await update.message.reply_text("Укажите приоритет (1-5):")
    return SET_PRIORITY


async def set_priority(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not update.message.text.isdigit() or not 1 <= int(update.message.text) <= 5:
        await update.message.reply_text("Некорректный приоритет! Введите число от 1 до 5:")
        return SET_PRIORITY

    context.user_data['priority'] = int(update.message.text)
    await update.message.reply_text("Введите срок выполнения (ДД.ММ.ГГГГ ЧЧ:ММ или 'нет'):")
    return SET_DUE_DATE


async def set_due_date(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    due_date = None
    if update.message.text.lower() != 'нет':
        try:
            due_date = datetime.strptime(update.message.text, "%d.%m.%Y %H:%M")
            due_date = TIMEZONE.localize(due_date)
        except ValueError:
            await update.message.reply_text("Некорректный формат даты! Используйте ДД.ММ.ГГГГ ЧЧ:ММ:")
            return SET_DUE_DATE

    add_task(
        update.message.from_user.id,
        context.user_data['task'],
        context.user_data['priority'],
        due_date
    )
    await update.message.reply_text("Задача добавлена!", reply_markup=get_main_menu())
    return ConversationHandler.END


async def send_reminder_callback(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    await context.bot.send_message(
        chat_id=job.data['user_id'],
        text=f"🔔 Напоминание: {job.data['text']}"
    )
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("DELETE FROM reminders WHERE id=?", (job.name,))
    conn.commit()
    conn.close()


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error(msg="Exception while handling an update:", exc_info=context.error)


def main() -> None:
    application = Application.builder().token(TOKEN).build()
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            TASK_STATES: [
                ConversationHandler(
                    entry_points=[CallbackQueryHandler(add_task_handler, pattern='^add_task$')],
                    states={
                        SET_TASK: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_task)],
                        SET_PRIORITY: [MessageHandler(filters.Regex(r'^[1-5]$'), set_priority)],
                        SET_DUE_DATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_due_date)]
                    },
                    fallbacks=[CommandHandler('cancel', cancel)]
                )
            ]
        },
        fallbacks=[CommandHandler('cancel', cancel)]
    )

    application.add_handler(conv_handler)
    application.add_handler(CallbackQueryHandler(tasks_menu, pattern='^tasks$'))
    application.add_handler(CallbackQueryHandler(expenses_menu, pattern='^expenses$'))
    application.add_error_handler(error_handler)


    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT * FROM reminders")
    for reminder in c.fetchall():
        trigger_time = datetime.fromisoformat(reminder[3])
        if trigger_time > datetime.now():
            application.job_queue.run_once(
                send_reminder_callback,
                trigger_time - datetime.now(),
                data={'user_id': reminder[1], 'text': reminder[2]},
                name=reminder[0]
            )
    conn.close()

    application.run_polling()


if __name__ == "__main__":
    main()