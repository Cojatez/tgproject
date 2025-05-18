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
from pytz import timezone
import uuid


logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

TOKEN = "tok"
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


def get_back_button():
    return InlineKeyboardMarkup([[InlineKeyboardButton("Назад", callback_data='main_menu')]])


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
    if update.message:
        await update.message.reply_text(welcome_text, reply_markup=get_main_menu())
    else:
        await update.callback_query.edit_message_text(welcome_text, reply_markup=get_main_menu())


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text('Действие отменено', reply_markup=get_main_menu())
    return ConversationHandler.END



def get_tasks(user_id: int):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT * FROM tasks WHERE user_id=? AND completed=0 ORDER BY due", (user_id,))
    tasks = c.fetchall()
    conn.close()
    return tasks


def add_task(user_id: int, task: str, priority: int, due: datetime = None):
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

    tasks_text = "📝 Ваши задачи:\n\n"
    for task in tasks:
        due_date = datetime.strptime(task[5], "%Y-%m-%d %H:%M:%S").strftime("%d.%m.%Y %H:%M") if task[
            5] else "нет срока"
        tasks_text += f"• {task[2]}\nПриоритет: {task[3]}/5\nСрок: {due_date}\n\n"

    await query.edit_message_text(text=tasks_text, reply_markup=get_back_button())


async def add_task_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(text="Введите описание задачи:", reply_markup=get_back_button())
    return SET_TASK


async def set_task(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['task'] = update.message.text
    await update.message.reply_text("Укажите приоритет (1-5):", reply_markup=get_back_button())
    return SET_PRIORITY


async def set_priority(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not update.message.text.isdigit() or not 1 <= int(update.message.text) <= 5:
        await update.message.reply_text("Некорректный приоритет! Введите число от 1 до 5:",
                                        reply_markup=get_back_button())
        return SET_PRIORITY

    context.user_data['priority'] = int(update.message.text)
    await update.message.reply_text("Введите срок выполнения (ДД.ММ.ГГГГ ЧЧ:ММ или 'нет'):",
                                    reply_markup=get_back_button())
    return SET_DUE_DATE


async def set_due_date(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    due_date = None
    if update.message.text.lower() != 'нет':
        try:
            due_date = datetime.strptime(update.message.text, "%d.%m.%Y %H:%M")
            due_date = TIMEZONE.localize(due_date)
        except ValueError:
            await update.message.reply_text("Некорректный формат даты! Используйте ДД.ММ.ГГГГ ЧЧ:ММ:",
                                            reply_markup=get_back_button())
            return SET_DUE_DATE

    add_task(
        update.message.from_user.id,
        context.user_data['task'],
        context.user_data['priority'],
        due_date
    )
    await update.message.reply_text("✅ Задача добавлена!", reply_markup=get_main_menu())
    return ConversationHandler.END



def get_expenses(user_id: int):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT * FROM expenses WHERE user_id=? ORDER BY created DESC LIMIT 10", (user_id,))
    expenses = c.fetchall()
    conn.close()
    return expenses


def add_expense(user_id: int, amount: float, category: str):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("INSERT INTO expenses (user_id, amount, category, created) VALUES (?, ?, ?, ?)",
              (user_id, amount, category, datetime.now()))
    conn.commit()
    conn.close()


async def expenses_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    keyboard = [
        [InlineKeyboardButton("Добавить расход", callback_data='add_expense'),
         InlineKeyboardButton("Последние расходы", callback_data='list_expenses')],
        [InlineKeyboardButton("Назад", callback_data='main_menu')]
    ]
    await query.edit_message_text(
        text="💰 Меню расходов:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def list_expenses(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    expenses = get_expenses(user_id)

    if not expenses:
        await query.edit_message_text(text="У вас нет записанных расходов.", reply_markup=get_main_menu())
        return

    expenses_text = "💰 Последние расходы:\n\n"
    for expense in expenses:
        date = datetime.strptime(expense[4], "%Y-%m-%d %H:%M:%S").strftime("%d.%m.%Y %H:%M")
        expenses_text += f"• {expense[2]} руб. - {expense[3]}\nДата: {date}\n\n"

    await query.edit_message_text(text=expenses_text, reply_markup=get_back_button())


async def add_expense_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(text="Введите сумму расхода:", reply_markup=get_back_button())
    return SET_EXPENSE_AMOUNT


async def set_expense_amount(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        amount = float(update.message.text.replace(',', '.'))
        if amount <= 0:
            raise ValueError
        context.user_data['amount'] = amount
        await update.message.reply_text("Введите категорию расхода (например: 'Еда', 'Транспорт'):",
                                        reply_markup=get_back_button())
        return SET_EXPENSE_CATEGORY
    except ValueError:
        await update.message.reply_text("Некорректная сумма! Введите положительное число:",
                                        reply_markup=get_back_button())
        return SET_EXPENSE_AMOUNT


async def set_expense_category(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    category = update.message.text
    add_expense(update.message.from_user.id, context.user_data['amount'], category)
    await update.message.reply_text(
        f"✅ Расход {context.user_data['amount']} руб. на '{category}' добавлен!",
        reply_markup=get_main_menu()
    )
    return ConversationHandler.END



def get_notes(user_id: int):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT * FROM notes WHERE user_id=? ORDER BY created DESC LIMIT 10", (user_id,))
    notes = c.fetchall()
    conn.close()
    return notes


def add_note(user_id: int, text: str, tags: str = None):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("INSERT INTO notes (user_id, text, tags, created) VALUES (?, ?, ?, ?)",
              (user_id, text, tags, datetime.now()))
    conn.commit()
    conn.close()


async def notes_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    keyboard = [
        [InlineKeyboardButton("Добавить заметку", callback_data='add_note'),
         InlineKeyboardButton("Последние заметки", callback_data='list_notes')],
        [InlineKeyboardButton("Назад", callback_data='main_menu')]
    ]
    await query.edit_message_text(
        text="📌 Меню заметок:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def list_notes(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    notes = get_notes(user_id)

    if not notes:
        await query.edit_message_text(text="У вас нет сохраненных заметок.", reply_markup=get_main_menu())
        return

    notes_text = "📌 Последние заметки:\n\n"
    for note in notes:
        date = datetime.strptime(note[4], "%Y-%m-%d %H:%M:%S").strftime("%d.%m.%Y %H:%M")
        tags = f"Теги: {note[3]}" if note[3] else ""
        notes_text += f"• {note[2]}\n{tags}\nДата: {date}\n\n"

    await query.edit_message_text(text=notes_text, reply_markup=get_back_button())


async def add_note_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(text="Введите текст заметки:", reply_markup=get_back_button())
    return SET_NOTE_TEXT


async def set_note_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['note_text'] = update.message.text
    await update.message.reply_text("Введите теги через запятую (или 'нет'):", reply_markup=get_back_button())
    return SET_NOTE_TAGS


async def set_note_tags(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    tags = None if update.message.text.lower() == 'нет' else update.message.text
    add_note(update.message.from_user.id, context.user_data['note_text'], tags)
    await update.message.reply_text("✅ Заметка добавлена!", reply_markup=get_main_menu())
    return ConversationHandler.END



def get_reminders(user_id: int):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT * FROM reminders WHERE user_id=? AND trigger_time > datetime('now') ORDER BY trigger_time",
              (user_id,))
    reminders = c.fetchall()
    conn.close()
    return reminders


def add_reminder(user_id: int, text: str, trigger_time: datetime):
    reminder_id = str(uuid.uuid4())
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("INSERT INTO reminders (id, user_id, text, trigger_time) VALUES (?, ?, ?, ?)",
              (reminder_id, user_id, text, trigger_time))
    conn.commit()
    conn.close()
    return reminder_id


async def reminders_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    keyboard = [
        [InlineKeyboardButton("Добавить напоминание", callback_data='add_reminder'),
         InlineKeyboardButton("Мои напоминания", callback_data='list_reminders')],
        [InlineKeyboardButton("Назад", callback_data='main_menu')]
    ]
    await query.edit_message_text(
        text="🔔 Меню напоминаний:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def list_reminders(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    reminders = get_reminders(user_id)

    if not reminders:
        await query.edit_message_text(text="У вас нет активных напоминаний.", reply_markup=get_main_menu())
        return

    reminders_text = "🔔 Активные напоминания:\n\n"
    for reminder in reminders:
        trigger_time = datetime.strptime(reminder[3], "%Y-%m-%d %H:%M:%S").strftime("%d.%m.%Y %H:%M")
        reminders_text += f"• {reminder[2]}\nВремя: {trigger_time}\n\n"

    await query.edit_message_text(text=reminders_text, reply_markup=get_back_button())


async def add_reminder_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(text="Введите текст напоминания:", reply_markup=get_back_button())
    return SET_REMINDER_TEXT


async def set_reminder_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['reminder_text'] = update.message.text
    await update.message.reply_text("Введите дату и время напоминания (ДД.ММ.ГГГГ ЧЧ:ММ):",
                                    reply_markup=get_back_button())
    return SET_REMINDER_TIME


async def set_reminder_time(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        trigger_time = datetime.strptime(update.message.text, "%d.%m.%Y %H:%M")
        trigger_time = TIMEZONE.localize(trigger_time)

        if trigger_time <= datetime.now():
            await update.message.reply_text("Время напоминания должно быть в будущем! Введите заново:",
                                            reply_markup=get_back_button())
            return SET_REMINDER_TIME

        reminder_id = add_reminder(
            update.message.from_user.id,
            context.user_data['reminder_text'],
            trigger_time
        )


        delay = (trigger_time - datetime.now()).total_seconds()
        context.application.job_queue.run_once(
            send_reminder_callback,
            delay,
            data={'user_id': update.message.from_user.id, 'text': context.user_data['reminder_text']},
            name=reminder_id
        )

        await update.message.reply_text(
            f"✅ Напоминание установлено на {trigger_time.strftime('%d.%m.%Y %H:%M')}!",
            reply_markup=get_main_menu()
        )
        return ConversationHandler.END
    except ValueError:
        await update.message.reply_text("Некорректный формат даты! Используйте ДД.ММ.ГГГГ ЧЧ:ММ:",
                                        reply_markup=get_back_button())
        return SET_REMINDER_TIME


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


async def main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(text="Главное меню:", reply_markup=get_main_menu())


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


    expense_conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(add_expense_handler, pattern='^add_expense$')],
        states={
            SET_EXPENSE_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_expense_amount)],
            SET_EXPENSE_CATEGORY: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_expense_category)]
        },
        fallbacks=[CommandHandler('cancel', cancel)]
    )


    note_conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(add_note_handler, pattern='^add_note$')],
        states={
            SET_NOTE_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_note_text)],
            SET_NOTE_TAGS: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_note_tags)]
        },
        fallbacks=[CommandHandler('cancel', cancel)]
    )


    reminder_conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(add_reminder_handler, pattern='^add_reminder$')],
        states={
            SET_REMINDER_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_reminder_text)],
            SET_REMINDER_TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_reminder_time)]
        },
        fallbacks=[CommandHandler('cancel', cancel)]
    )


    application.add_handler(CommandHandler('start', start))
    application.add_handler(CallbackQueryHandler(tasks_menu, pattern='^tasks$'))
    application.add_handler(CallbackQueryHandler(expenses_menu, pattern='^expenses$'))
    application.add_handler(CallbackQueryHandler(notes_menu, pattern='^notes$'))
    application.add_handler(CallbackQueryHandler(reminders_menu, pattern='^reminders$'))
    application.add_handler(CallbackQueryHandler(main_menu, pattern='^main_menu$'))
    application.add_handler(CallbackQueryHandler(list_tasks, pattern='^list_tasks$'))
    application.add_handler(CallbackQueryHandler(list_expenses, pattern='^list_expenses$'))
    application.add_handler(CallbackQueryHandler(list_notes, pattern='^list_notes$'))
    application.add_handler(CallbackQueryHandler(list_reminders, pattern='^list_reminders$'))


    application.add_handler(task_conv_handler)
    application.add_handler(expense_conv_handler)
    application.add_handler(note_conv_handler)
    application.add_handler(reminder_conv_handler)

    application.add_error_handler(error_handler)


    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT * FROM reminders WHERE trigger_time > datetime('now')")
    for reminder in c.fetchall():
        trigger_time = datetime.strptime(reminder[3], "%Y-%m-%d %H:%M:%S")
        if trigger_time > datetime.now():
            delay = (trigger_time - datetime.now()).total_seconds()
            application.job_queue.run_once(
                send_reminder_callback,
                delay,
                data={'user_id': reminder[1], 'text': reminder[2]},
                name=reminder[0]
            )
    conn.close()

    application.run_polling()


if __name__ == "__main__":
    main()