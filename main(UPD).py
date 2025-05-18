import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
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

TOKEN = "7650414135:AAH778jHnOVVQNjr_QFGjmv4Nv0pD6ZRajE"
DB_NAME = "organizer.db"
TIMEZONE = timezone('Europe/Moscow')

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


async def handle_new_members(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    for member in update.message.new_chat_members:
        if member.id == context.bot.id:
            welcome_text = """
            👋 Привет! Я твой личный организатор.

            Напиши мне /start, чтобы начать работу!
            """
            await update.message.reply_text(welcome_text)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    welcome_text = """
    👋 Привет! Я твой личный организатор.

    Я помогу тебе:
    - 📝 Вести список задач
    - 💰 Учитывать расходы
    - 📌 Сохранять заметки
    - 🔔 Устанавливать напоминания

    Выбери нужный раздел в меню ниже:
    """
    await update.message.reply_text(welcome_text, reply_markup=get_main_menu())


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


async def list_tasks(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    tasks = get_tasks(user_id)

    if not tasks:
        await query.edit_message_text(text="У вас нет активных задач.", reply_markup=get_main_menu())
        return

    tasks_text = "Ваши задачи:\n\n"
    for task in tasks:
        due_date = datetime.strptime(task[5], "%Y-%m-%d %H:%M:%S").strftime("%d.%m.%Y %H:%M") if task[
            5] else "нет срока"
        tasks_text += f"📌 {task[2]}\nПриоритет: {task[3]}\nСрок: {due_date}\n\n"

    await query.edit_message_text(text=tasks_text, reply_markup=get_main_menu())


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


async def expenses_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    keyboard = [
        [InlineKeyboardButton("Добавить расход", callback_data='add_expense'),
         InlineKeyboardButton("Мои расходы", callback_data='list_expenses')],
        [InlineKeyboardButton("Назад", callback_data='main_menu')]
    ]
    await query.edit_message_text(
        text="Меню расходов:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def notes_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    keyboard = [
        [InlineKeyboardButton("Добавить заметку", callback_data='add_note'),
         InlineKeyboardButton("Мои заметки", callback_data='list_notes')],
        [InlineKeyboardButton("Назад", callback_data='main_menu')]
    ]
    await query.edit_message_text(
        text="Меню заметок:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def reminders_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    keyboard = [
        [InlineKeyboardButton("Добавить напоминание", callback_data='add_reminder'),
         InlineKeyboardButton("Мои напоминания", callback_data='list_reminders')],
        [InlineKeyboardButton("Назад", callback_data='main_menu')]
    ]
    await query.edit_message_text(
        text="Меню напоминаний:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(text="Главное меню:", reply_markup=get_main_menu())


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


    task_conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(add_task_handler, pattern='^add_task$')],
        states={
            SET_TASK: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_task)],
            SET_PRIORITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_priority)],
            SET_DUE_DATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_due_date)]
        },
        fallbacks=[CommandHandler('cancel', cancel)]
    )


    application.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, handle_new_members))
    application.add_handler(CommandHandler('start', start))
    application.add_handler(CallbackQueryHandler(tasks_menu, pattern='^tasks$'))
    application.add_handler(CallbackQueryHandler(expenses_menu, pattern='^expenses$'))
    application.add_handler(CallbackQueryHandler(notes_menu, pattern='^notes$'))
    application.add_handler(CallbackQueryHandler(reminders_menu, pattern='^reminders$'))
    application.add_handler(CallbackQueryHandler(main_menu, pattern='^main_menu$'))
    application.add_handler(CallbackQueryHandler(list_tasks, pattern='^list_tasks$'))
    application.add_handler(task_conv_handler)
    application.add_error_handler(error_handler)


    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT * FROM reminders")
    for reminder in c.fetchall():
        trigger_time = datetime.strptime(reminder[3], "%Y-%m-%d %H:%M:%S")
        if trigger_time > datetime.now():
            application.job_queue.run_once(
                send_reminder_callback,
                (trigger_time - datetime.now()).total_seconds(),
                data={'user_id': reminder[1], 'text': reminder[2]},
                name=reminder[0]
            )
    conn.close()

    application.run_polling()


if __name__ == "__main__":
    main()