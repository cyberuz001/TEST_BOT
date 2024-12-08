import json
import sqlite3
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters, ConversationHandler
import os
from dotenv import load_dotenv
import asyncio
import signal

# Import functions from other files
from test_functions import (
    create_test, process_test_creation, send_test, view_results, view_tests,
    delete_test, process_correct_answer, add_question, finish_test, create_test_file,
    process_test_file_creation, delete_test_file, process_send_test,
    confirm_send_test, cancel_send_test, select_test_file, view_file_tests, add_new_test
)
from student_functions import (
    start_test, process_answer, register_student, process_name, process_surname,
    select_test_file as student_select_test_file,
    start_selected_test, ENTERING_NAME, ENTERING_SURNAME, view_available_tests, view_my_results, check_new_tests, view_class_ranking
)

# Load environment variables
load_dotenv()

# Get bot token and admin ID from environment variables
TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
ADMIN_ID = int(os.getenv('ADMIN_TELEGRAM_ID'))

# Update ADMIN_IDs list
ADMIN_IDS = [ADMIN_ID]  # You can add more admin IDs here if needed

# Define conversation states
SELECTING_ACTION, CREATING_TEST_FILE, CREATING_TEST, ANSWERING_QUESTION = range(4)

# Connect to SQLite database
conn = sqlite3.connect('test_bot.db')
cursor = conn.cursor()

# Create tables if they don't exist
cursor.execute('''
CREATE TABLE IF NOT EXISTS students (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    first_name TEXT,
    last_name TEXT,
    telegram_id INTEGER UNIQUE,
    registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
''')

cursor.execute('''
CREATE TABLE IF NOT EXISTS students_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER,
    test_id INTEGER,
    correct_answers INTEGER,
    wrong_answers INTEGER,
    total_questions INTEGER,
    rank INTEGER,
    FOREIGN KEY(student_id) REFERENCES students(id)
)
''')

cursor.execute('''
CREATE TABLE IF NOT EXISTS available_tests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER,
    test_file TEXT,
    FOREIGN KEY(student_id) REFERENCES students(id)
)
''')

conn.commit()
conn.close()

# Function to check if user is admin
def is_admin(user_id):
    return user_id in ADMIN_IDS

# Command handlers
async def testlarni_korish(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle the /testlarni_korish command"""
    return await view_tests(update, context)

# Start command handler
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if is_admin(user.id):
        keyboard = [
            [InlineKeyboardButton("Test yaratish", callback_data="create_test"),
             InlineKeyboardButton("Test file yaratish", callback_data="create_test_file")],
            [InlineKeyboardButton("Testlarni ko'rish", callback_data="view_tests"),
             InlineKeyboardButton("Natijalarni ko'rish", callback_data="view_results")],
            [InlineKeyboardButton("Test jo'natish", callback_data="send_test")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        message = f"Salom, {user.first_name}! Siz admin sifatida tizimga kirdingiz. Nima qilishni xohlaysiz?"
    else:
        conn = sqlite3.connect('test_bot.db')
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM students WHERE telegram_id = ?', (user.id,))
        student = cursor.fetchone()
        conn.close()

        if student:
            keyboard = [
                [InlineKeyboardButton("Test yechish", callback_data="solve_test")],
                [InlineKeyboardButton("Natijalarimni ko'rish", callback_data="view_my_results")],
                [InlineKeyboardButton("Yangi testlar bormi?", callback_data="check_new_tests")],
                [InlineKeyboardButton("Sinf reytingi", callback_data="view_class_ranking")]
            ]
            message = f"Salom, {student[1]} {student[2]}! Nima qilishni xohlaysiz?"
        else:
            keyboard = [[InlineKeyboardButton("Ro'yxatdan o'tish", callback_data="register")]]
            message = "Salom! Test botiga xush kelibsiz. Iltimos, ro'yxatdan o'ting."

        reply_markup = InlineKeyboardMarkup(keyboard)
    
    if update.message:
        await update.message.reply_text(message, reply_markup=reply_markup)
    elif update.callback_query:
        await update.callback_query.edit_message_text(message, reply_markup=reply_markup)
    
    return SELECTING_ACTION

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "create_test":
        return await create_test(update, context)
    elif query.data == "create_test_file":
        return await create_test_file(update, context)
    elif query.data == "view_tests":
        return await view_tests(update, context)
    elif query.data.startswith("view_file_"):
        return await view_file_tests(update, context)
    elif query.data == "view_results":
        return await view_results(update, context)
    elif query.data == "send_test":
        return await send_test(update, context)
    elif query.data == "register":
        return await register_student(update, context)
    elif query.data == "solve_test":
        return await start_test(update, context)
    elif query.data == "main_menu":
        return await start(update, context)
    elif query.data.startswith("delete_test_"):
        return await delete_test(update, context)
    elif query.data.startswith("delete_file_"):
        return await delete_test_file(update, context)
    elif query.data.startswith("select_file_"):
        return await student_select_test_file(update, context)
    elif query.data.startswith("start_test_"):
        return await start_selected_test(update, context)
    elif query.data == "view_available_tests":
        return await view_available_tests(update, context)
    elif query.data == "add_new_test":
        return await add_new_test(update, context)
    elif query.data == "view_my_results":
        return await view_my_results(update, context)
    elif query.data == "check_new_tests":
        return await check_new_tests(update, context)
    elif query.data == "view_class_ranking":
        return await view_class_ranking(update, context)


async def shutdown(application: Application):
    """Cleanup function to be called before shutdown"""
    await application.stop()
    await application.shutdown()

# Main function to run the bot
def main():
    if not TOKEN:
        raise ValueError("No token provided. Set TELEGRAM_BOT_TOKEN in .env file.")
    
    # Create the Application
    application = Application.builder().token(TOKEN).build()

    # Add handlers
    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("start", start),
            CommandHandler("testlarni_korish", testlarni_korish),
            CallbackQueryHandler(button_callback)
        ],
        states={
            SELECTING_ACTION: [
                CallbackQueryHandler(button_callback),
            ],
            CREATING_TEST_FILE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, process_test_file_creation),
            ],
            CREATING_TEST: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, process_test_creation),
                CallbackQueryHandler(process_correct_answer, pattern="^correct_"),
                CallbackQueryHandler(add_question, pattern="^add_question"),
                CallbackQueryHandler(finish_test, pattern="^finish_test"),
            ],
            ANSWERING_QUESTION: [
                CallbackQueryHandler(process_answer, pattern="^answer_"),
            ],
            ENTERING_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, process_name),
            ],
            ENTERING_SURNAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, process_surname),
            ],
        },
        fallbacks=[
            CommandHandler("start", start),
            CommandHandler("testlarni_korish", testlarni_korish),
            CallbackQueryHandler(button_callback)
        ],
        per_message=False
    )

    application.add_handler(conv_handler)

    # Add these handlers outside of the ConversationHandler
    application.add_handler(CallbackQueryHandler(delete_test, pattern="^delete_test_"))
    application.add_handler(CallbackQueryHandler(delete_test_file, pattern="^delete_file_"))
    application.add_handler(CallbackQueryHandler(select_test_file, pattern="^select_file_"))
    application.add_handler(CallbackQueryHandler(process_send_test, pattern="^send_file_"))
    application.add_handler(CallbackQueryHandler(confirm_send_test, pattern="^confirm_send_"))
    application.add_handler(CallbackQueryHandler(cancel_send_test, pattern="^cancel_send$"))

    # Set up proper signal handling
    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, lambda s=sig: asyncio.create_task(shutdown(application)))
        except NotImplementedError:
            # Signal handlers are not supported on Windows
            pass

    # Run the bot
    print("Bot started successfully!")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\nBot stopped by user")
    except Exception as e:
        print(f"Error occurred: {e}")

