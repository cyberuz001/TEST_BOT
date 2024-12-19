import logging
import json
import sqlite3
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters, ConversationHandler
import os
from dotenv import load_dotenv
import asyncio

# Configure logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

# Get bot token and admin ID from environment variables
TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
ADMIN_ID = int(os.getenv('ADMIN_TELEGRAM_ID'))

# Update ADMIN_IDs list
ADMIN_IDS = [ADMIN_ID]

# Define conversation states
SELECTING_ACTION, CREATING_TEST_FILE, CREATING_TEST, ANSWERING_QUESTION, ENTERING_NAME, ENTERING_SURNAME = range(6)

# Ensure tests directory exists
def ensure_tests_directory_exists():
    if not os.path.exists("tests"):
        os.makedirs("tests")

# Connect to SQLite database
def get_db_connection():
    conn = sqlite3.connect('test_bot.db')
    conn.row_factory = sqlite3.Row
    return conn

# Initialize database
def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
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
        test_id TEXT,
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
        completed INTEGER DEFAULT 0,
        FOREIGN KEY(student_id) REFERENCES students(id)
    )
    ''')
    conn.commit()
    conn.close()

# Initialize database
init_db()

# Function to check if user is admin
def is_admin(user_id):
    return user_id in ADMIN_IDS

# Load tests from JSON file
def load_tests(file_name):
    file_path = f"tests/{file_name}"
    if not os.path.exists(file_path):
        logger.error(f"Test file not found: {file_path}")
        return None, "Test fayli topilmadi."
    try:
        with open(file_path, 'r') as f:
            content = f.read().strip()
            if not content:
                logger.warning(f"Empty test file: {file_path}")
                return None, "Test fayli bo'sh."
            return json.loads(content), None
    except json.JSONDecodeError as e:
        logger.error(f"Error decoding JSON from file {file_path}: {e}")
        return None, "Test faylini o'qishda xatolik yuz berdi."
    except Exception as e:
        logger.error(f"Unexpected error loading tests from {file_path}: {e}")
        return None, "Kutilmagan xatolik yuz berdi."

# Save tests to JSON file
def save_tests(tests, file_name):
    file_path = f"tests/{file_name}"
    with open(file_path, 'w') as f:
        json.dump(tests, f)

async def safe_edit_message_text(update, text, reply_markup=None):
    try:
        if update.callback_query and update.callback_query.message:
            await update.callback_query.edit_message_text(text, reply_markup=reply_markup)
        else:
            if hasattr(update, 'message'):
                await update.message.reply_text(text, reply_markup=reply_markup)
            elif hasattr(update, 'callback_query') and update.callback_query.message:
                await update.callback_query.message.reply_text(text, reply_markup=reply_markup)
            else:
                logger.error("Unable to send message: no valid message object found")
                return False
    except Exception as e:
        logger.error(f"Error in safe_edit_message_text: {e}")
        try:
            if hasattr(update, 'message'):
                await update.message.reply_text(text, reply_markup=reply_markup)
            elif hasattr(update, 'callback_query') and update.callback_query.message:
                await update.callback_query.message.reply_text(text, reply_markup=reply_markup)
            else:
                logger.error("Unable to send message: no valid message object found")
                return False
        except Exception as e:
            logger.error(f"Failed to send message after edit attempt: {e}")
            return False
    return True

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
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM students WHERE telegram_id = ?', (user.id,))
        student = cursor.fetchone()
        conn.close()

        if student:
            keyboard = [
                [InlineKeyboardButton("Test yechish", callback_data="solve_test")],
                [InlineKeyboardButton("Mening natijalarim", callback_data="view_my_results")]
            ]
            message = f"{student['first_name']} {student['last_name']}! uchun bosh menyu"
        else:
            keyboard = [[InlineKeyboardButton("Ro'yxatdan o'tish", callback_data="register")]]
            message = "Salom! Test botiga xush kelibsiz. Iltimos, ro'yxatdan o'ting."

        reply_markup = InlineKeyboardMarkup(keyboard)
    
    await safe_edit_message_text(update, message, reply_markup=reply_markup)
    return SELECTING_ACTION

# Create a new test file
async def create_test_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_admin(user.id):
        await update.callback_query.answer("Kechirasiz, siz admin emassiz.")
        return ConversationHandler.END

    ensure_tests_directory_exists()
    await update.callback_query.edit_message_text("Yangi test file yaratish uchun file nomini kiriting:")
    context.user_data['awaiting_file_name'] = True
    return CREATING_TEST_FILE

async def process_test_file_creation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if 'awaiting_file_name' not in context.user_data or not context.user_data['awaiting_file_name']:
        await update.message.reply_text("Xatolik yuz berdi. Iltimos, /start komandasini ishlatib, qaytadan urinib ko'ring.")
        return ConversationHandler.END

    file_name = update.message.text
    if not file_name.endswith('.json'):
        file_name += '.json'

    file_path = f"tests/{file_name}"
    if os.path.exists(file_path):
        await update.message.reply_text(f"'{file_name}' nomli file allaqachon mavjud. Boshqa nom tanlang.")
        return CREATING_TEST_FILE

    try:
        # Create an empty JSON file
        with open(file_path, 'w') as f:
            json.dump([], f)

        # Animate file creation
        message = await update.message.reply_text("File yaratilmoqda...")
        for i in range(3):
            await message.edit_text(f"File yaratilmoqda{'.' * (i + 1)}")
            await asyncio.sleep(0.3)

        keyboard = [
            [InlineKeyboardButton("Test yaratishni boshlash", callback_data=f"start_test_creation_{file_name}")],
            [InlineKeyboardButton("Bosh menyuga qaytish", callback_data="main_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await message.edit_text(f"'{file_name}' nomli yangi test file yaratildi.", reply_markup=reply_markup)
        context.user_data['awaiting_file_name'] = False
        return SELECTING_ACTION
    except Exception as e:
        logger.error(f"Error creating test file: {e}")
        await update.message.reply_text(f"File yaratishda xatolik yuz berdi: {str(e)}. Iltimos, qaytadan urinib ko'ring.")
        return ConversationHandler.END

# Create a new test
async def create_test(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_admin(user.id):
        await update.callback_query.edit_message_text("Kechirasiz, siz admin emassiz.")
        return ConversationHandler.END

    ensure_tests_directory_exists()
    test_files = [f for f in os.listdir("tests") if f.endswith('.json')]
    
    if not test_files:
        return await handle_test_file_error(update, context, "Hozircha test file'lari mavjud emas.")

    keyboard = [[InlineKeyboardButton(file, callback_data=f"select_file_{file}")] for file in test_files]
    keyboard.append([InlineKeyboardButton("Yangi test file yaratish", callback_data="create_test_file")])
    keyboard.append([InlineKeyboardButton("Bosh menyuga qaytish", callback_data="main_menu")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.callback_query.edit_message_text("Qaysi file'ga test qo'shmoqchisiz?", reply_markup=reply_markup)
    return SELECTING_ACTION

async def select_test_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    try:
        file_name = query.data.split('_')[-1]
        tests, error_message = load_tests(file_name)

        if error_message:
            await query.edit_message_text(f"Xatolik: {error_message}")
            return ConversationHandler.END

        if not tests:
            tests = []

        context.user_data['current_file'] = file_name
        context.user_data['all_tests'] = tests
        context.user_data['current_test_index'] = 0
        
        if is_admin(query.from_user.id):
            # For admin, show test creation options
            keyboard = [
                [InlineKeyboardButton("Yangi test qo'shish", callback_data=f"add_test_{file_name}")],
                [InlineKeyboardButton("Testlarni ko'rish", callback_data=f"view_tests_{file_name}")],
                [InlineKeyboardButton("Bosh menyuga qaytish", callback_data="main_menu")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(f"'{file_name}' fayli tanlandi. Nima qilishni xohlaysiz?", reply_markup=reply_markup)
            return SELECTING_ACTION
        else:
            # For students, start the test
            return await start_selected_test(update, context)
    except Exception as e:
        logger.error(f"Error in select_test_file: {e}")
        await query.edit_message_text(f"Testni tanlashda xatolik yuz berdi: {str(e)}. Iltimos, qaytadan urinib ko'ring.")
        return ConversationHandler.END

async def process_test_creation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if 'creating_test' not in context.user_data or not context.user_data['creating_test']:
        return SELECTING_ACTION

    current_test = context.user_data['current_test']
    current_step = context.user_data['current_step']

    if current_step == 'question':
        current_test['questions'].append(update.message.text)
        await update.message.reply_text("A javobni kiriting:")
        context.user_data['current_step'] = 'answer_a'
    elif current_step == 'answer_a':
        current_test['answers'].append([f"a) {update.message.text}"])
        await update.message.reply_text("B javobni kiriting:")
        context.user_data['current_step'] = 'answer_b'
    elif current_step == 'answer_b':
        current_test['answers'][-1].append(f"b) {update.message.text}")
        await update.message.reply_text("C javobni kiriting:")
        context.user_data['current_step'] = 'answer_c'
    elif current_step == 'answer_c':
        current_test['answers'][-1].append(f"c) {update.message.text}")
        await update.message.reply_text("D javobni kiriting:")
        context.user_data['current_step'] = 'answer_d'
    elif current_step == 'answer_d':
        current_test['answers'][-1].append(f"d) {update.message.text}")
        keyboard = [
            [InlineKeyboardButton("A", callback_data="correct_a"),
             InlineKeyboardButton("B", callback_data="correct_b"),
             InlineKeyboardButton("C", callback_data="correct_c"),
             InlineKeyboardButton("D", callback_data="correct_d")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text("To'g'ri javobni tanlang:", reply_markup=reply_markup)
        context.user_data['current_step'] = 'correct_answer'
    return CREATING_TEST

async def process_correct_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    current_test = context.user_data['current_test']
    current_test['correct_answers'].append(query.data.split('_')[1])

    # Animate saving process
    message = await query.edit_message_text("To'g'ri javob saqlanmoqda...")
    for i in range(3):
        await message.edit_text(f"To'g'ri javob saqlanmoqda{'.' * (i + 1)}")
        await asyncio.sleep(0.3)

    keyboard = [
        [InlineKeyboardButton("Ha", callback_data="add_question"),
         InlineKeyboardButton("Yo'q", callback_data="finish_test")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await message.edit_text("To'g'ri javob saqlandi. Yana savol qo'shmoqchimisiz?", reply_markup=reply_markup)
    return CREATING_TEST

async def add_question(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    await query.edit_message_text("Yangi savolni kiriting:")
    context.user_data['current_step'] = 'question'
    return CREATING_TEST

async def finish_test(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    current_test = context.user_data['current_test']
    file_name = context.user_data['current_file']
    tests, error_message = load_tests(file_name)

    if error_message:
        await safe_edit_message_text(update, f"Xatolik: {error_message}")
        return ConversationHandler.END

    if not tests:
        tests = []

    current_test['id'] = len(tests) + 1
    tests.append(current_test)
    save_tests(tests, file_name)

    # Animate test saving process
    message = await query.edit_message_text("Test saqlanmoqda...")
    for i in range(3):
        await message.edit_text(f"Test saqlanmoqda{'.' * (i + 1)}")
        await asyncio.sleep(0.3)

    context.user_data['creating_test'] = False
    context.user_data['current_test'] = None
    context.user_data['current_step'] = None
    context.user_data.pop('current_file', None)

    keyboard = [
        [InlineKeyboardButton("Yangi test yaratish", callback_data="create_test")],
        [InlineKeyboardButton("Bosh menyuga qaytish", callback_data="main_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await message.edit_text(f"Test muvaffaqiyatli yaratildi va '{file_name}' file'ga saqlandi!", reply_markup=reply_markup)
    return SELECTING_ACTION

async def start_selected_test(update: Update, context: ContextTypes.DEFAULT_TYPE):
    all_tests = context.user_data.get('all_tests', [])
    current_test_index = context.user_data.get('current_test_index', 0)
    
    if current_test_index >= len(all_tests):
        return await finish_all_tests(update, context)
    
    context.user_data['current_test'] = all_tests[current_test_index]
    context.user_data['current_question'] = 0
    if 'answers' not in context.user_data:
        context.user_data['answers'] = []
    
    return await send_question(update, context)

async def send_question(update: Update, context: ContextTypes.DEFAULT_TYPE):
    all_tests = context.user_data.get('all_tests', [])
    current_test_index = context.user_data.get('current_test_index', 0)
    current_test = context.user_data.get('current_test')
    question_index = context.user_data.get('current_question', 0)
    
    if current_test_index >= len(all_tests):
        return await finish_all_tests(update, context)
    
    if question_index >= len(current_test['questions']):
        context.user_data['current_test_index'] = current_test_index + 1
        context.user_data['current_question'] = 0
        return await start_selected_test(update, context)
    
    total_questions_before = sum(len(test['questions']) for test in all_tests[:current_test_index])
    overall_question_number = total_questions_before + question_index + 1
    
    question = current_test['questions'][question_index]
    answers = current_test['answers'][question_index]
    
    keyboard = [[InlineKeyboardButton(answer[2:], callback_data=f"answer_{answer[0]}")] for answer in answers]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    message = f"Savol {overall_question_number}: {question}"
    if update.callback_query:
        await update.callback_query.edit_message_text(message, reply_markup=reply_markup)
    else:
        await update.message.reply_text(message, reply_markup=reply_markup)
    
    return ANSWERING_QUESTION

async def process_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    answer = query.data.split('_')[-1]
    
    # Make sure we have an answers list
    if 'answers' not in context.user_data:
        context.user_data['answers'] = []
    
    # Add the answer
    context.user_data['answers'].append(answer)
    
    # Increment question counter
    context.user_data['current_question'] = context.user_data.get('current_question', 0) + 1
    
    return await send_question(update, context)

async def finish_all_tests(update: Update, context: ContextTypes.DEFAULT_TYPE):
    all_tests = context.user_data['all_tests']
    user_answers = context.user_data.get('answers', [])
    
    total_correct = 0
    total_questions = sum(len(test['questions']) for test in all_tests)
    detailed_results = []
    
    # Track the current position in user_answers
    answer_index = 0
    
    # Process each test's answers
    for test in all_tests:
        for q_idx, question in enumerate(test['questions']):
            user_answer = user_answers[answer_index] if answer_index < len(user_answers) else None
            correct_answer = test['correct_answers'][q_idx]
            
            is_correct = user_answer == correct_answer
            if is_correct:
                total_correct += 1
            
            detailed_results.append({
                'question': question,
                'user_answer': user_answer if user_answer is not None else "Javob berilmagan",
                'correct_answer': correct_answer,
                'is_correct': is_correct
            })
            
            answer_index += 1
    
    total_wrong = total_questions - total_correct
    
    # Generate result text
    result_text = f"Test yakunlandi!\n\nBatafsil natijalar:\n\n"
    
    for i, result in enumerate(detailed_results, 1):
        result_text += f"Savol {i}: {result['question']}\n"
        result_text += f"Sizning javobingiz: {result['user_answer']}\n"
        result_text += f"To'g'ri javob: {result['correct_answer']}\n"
        result_text += f"Natija: {'Togri' if result['is_correct'] else 'Notogri'}\n\n"
    
    result_text += f"Umumiy natija:\n"
    result_text += f"Jami savollar: {total_questions}\n"
    result_text += f"To'g'ri javoblar: {total_correct}\n"
    result_text += f"Xato javoblar: {total_wrong}\n"
    result_text += f"Foiz: {(total_correct / total_questions) * 100:.2f}%\n"
    
    # Save results to database
    user = update.effective_user
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute('SELECT id FROM students WHERE telegram_id = ?', (user.id,))
        student = cursor.fetchone()
        
        if student is None:
            await update.callback_query.message.reply_text("Xatolik: Foydalanuvchi ma'lumotlari topilmadi.")
            return ConversationHandler.END
        
        student_id = student['id']
        
        # Save the results
        cursor.execute('''
        INSERT INTO students_results 
        (student_id, test_id, correct_answers, wrong_answers, total_questions)
        VALUES (?, ?, ?, ?, ?)
        ''', (student_id, context.user_data['current_file'], total_correct, total_wrong, total_questions))
        
        # Mark the test as completed
        cursor.execute('''
        UPDATE available_tests
        SET completed = 1
        WHERE student_id = ? AND test_file = ?
        ''', (student_id, context.user_data['current_file']))
        
        conn.commit()
    except Exception as e:
        logger.error(f"Error saving test results: {e}")
    finally:
        conn.close()
    
    # Show celebration animation
    celebration_frames = ["🎉", "🎊", "✨", "🎈", "🎇", "🎆"]
    celebration_message = await update.callback_query.edit_message_text("Tabriklaymiz!")
    
    for _ in range(3):
        for frame in celebration_frames:
            await celebration_message.edit_text(f"{frame} Tabriklaymiz! {frame}")
            await asyncio.sleep(0.3)
    
    # Split and send result text if it's too long
    max_message_length = 4096
    result_chunks = [result_text[i:i+max_message_length] for i in range(0, len(result_text), max_message_length)]
    
    for chunk in result_chunks:
        await update.callback_query.message.reply_text(chunk)
    
    keyboard = [[InlineKeyboardButton("Bosh menyu", callback_data="main_menu")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.callback_query.message.reply_text("Test muvaffaqiyatli yakunlandi!", reply_markup=reply_markup)
    
    # Clear user data
    context.user_data.clear()
    
    return ConversationHandler.END

# Send a test to students
async def send_test(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_admin(user.id):
        await update.callback_query.answer("Kechirasiz, siz admin emassiz.")
        return ConversationHandler.END

    ensure_tests_directory_exists()
    test_files = [f for f in os.listdir("tests") if f.endswith('.json')]
    if not test_files:
        keyboard = [
            [InlineKeyboardButton("Bosh menyuga qaytish", callback_data="main_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.callback_query.edit_message_text("Hozircha test file'lari mavjud emas.", reply_markup=reply_markup)
        return SELECTING_ACTION

    keyboard = [[InlineKeyboardButton(file, callback_data=f"send_file_{file}")] for file in test_files]
    keyboard.append([InlineKeyboardButton("Bosh menyuga qaytish", callback_data="main_menu")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.callback_query.edit_message_text("Qaysi file'dagi testlarni jo'natmoqchisiz?", reply_markup=reply_markup)
    return SELECTING_ACTION

async def process_send_test(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    file_name = query.data.split('_')[-1]
    tests, error_message = load_tests(file_name)

    if error_message:
        keyboard = [
            [InlineKeyboardButton("Bosh menyuga qaytish", callback_data="main_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(f"Xatolik: {error_message}", reply_markup=reply_markup)
        return SELECTING_ACTION

    if not tests:
        keyboard = [
            [InlineKeyboardButton("Bosh menyuga qaytish", callback_data="main_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(f"'{file_name}' file'ida hozircha testlar mavjud emas.", reply_markup=reply_markup)
        return SELECTING_ACTION

    context.user_data['selected_test_file'] = file_name

    keyboard = [
        [InlineKeyboardButton("Ha", callback_data=f"confirm_send_{file_name}")],
        [InlineKeyboardButton("Yo'q", callback_data="cancel_send")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(f"'{file_name}' fayl ichidagi barcha testlarni hamma o'quvchilarga jo'natishni istaysizmi?", reply_markup=reply_markup)
    return SELECTING_ACTION

async def confirm_send_test(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    file_name = query.data.split('_')[-1]

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT id, telegram_id FROM students')
    students = cursor.fetchall()

    if not students:
        keyboard = [
            [InlineKeyboardButton("Bosh menyuga qaytish", callback_data="main_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text("Hozircha ro'yxatdan o'tgan o'quvchilar yo'q.", reply_markup=reply_markup)
        conn.close()
        return SELECTING_ACTION

    for student in students:
        cursor.execute('INSERT OR REPLACE INTO available_tests (student_id, test_file, completed) VALUES (?, ?, 0)', (student['id'], file_name))
        
        # Notify the student
        keyboard = [[InlineKeyboardButton("Testni boshlash", callback_data="solve_test")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        try:
            await context.bot.send_message(chat_id=student['telegram_id'], text="Sizga yangi test tayinlandi!", reply_markup=reply_markup)
        except Exception as e:
            logger.error(f"Error sending message to student {student['id']}: {e}")

    conn.commit()
    conn.close()

    keyboard = [[InlineKeyboardButton("Bosh menyuga qaytish", callback_data="main_menu")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(f"'{file_name}' faylidagi testlar barcha o'quvchilarga muvaffaqiyatli jo'natildi!", reply_markup=reply_markup)
    return SELECTING_ACTION

async def cancel_send_test(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    keyboard = [
        [InlineKeyboardButton("Bosh menyuga qaytish", callback_data="main_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text("Test jo'natish bekor qilindi.", reply_markup=reply_markup)
    return SELECTING_ACTION

# View test results
async def view_results(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_admin(user.id):
        await update.callback_query.answer("Kechirasiz, siz admin emassiz.")
        return ConversationHandler.END

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
    SELECT s.first_name, s.last_name,
           COALESCE(sr.total_questions, 0) AS total_questions,
           COALESCE(sr.correct_answers, 0) AS correct_answers,
           COALESCE(sr.wrong_answers, 0) AS wrong_answers,
           COALESCE(sr.rank, 'N/A') AS rank
    FROM students s
    LEFT JOIN students_results sr ON s.id = sr.student_id
    ORDER BY sr.rank
    ''')
    results = cursor.fetchall()
    conn.close()

    if not results:
        keyboard = [
            [InlineKeyboardButton("Bosh menyuga qaytish", callback_data="main_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.callback_query.edit_message_text("Hozircha natijalar mavjud emas.", reply_markup=reply_markup)
        return SELECTING_ACTION

    result_text = "Natijalar:\n\n"
    result_text += "Ism       | Familiya  | Jami savollar | To'g'ri javoblar | Xato javoblar | Reyting \n"
    result_text += "-----------|-----------|----------------|-------------------|----------------|--------\n"

    for result in results:
        result_text += f"{result['first_name']:<9} | {result['last_name']:<9} | {result['total_questions']:<14} | {result['correct_answers']:<17} | {result['wrong_answers']:<14} | {result['rank']:<7}\n"

    # Split the results into chunks if they're too long
    max_message_length = 4096
    result_chunks = [result_text[i:i+max_message_length] for i in range(0, len(result_text), max_message_length)]

    for chunk in result_chunks:
        await update.callback_query.message.reply_text(f"```\n{chunk}\n```", parse_mode='MarkdownV2')

    keyboard = [
        [InlineKeyboardButton("Bosh menyuga qaytish", callback_data="main_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.callback_query.message.reply_text("Barcha natijalar ko'rsatildi.", reply_markup=reply_markup)
    return SELECTING_ACTION

# View and manage tests
async def view_tests(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_admin(user.id):
        await update.callback_query.edit_message_text("Kechirasiz, siz admin emassiz.")
        return ConversationHandler.END

    test_files = [f for f in os.listdir("tests") if f.endswith('.json')]
    if not test_files:
        keyboard = [
            [InlineKeyboardButton("Bosh menyuga qaytish", callback_data="main_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.callback_query.edit_message_text("Hozircha test file'lari mavjud emas.", reply_markup=reply_markup)
        return SELECTING_ACTION

    keyboard = [[InlineKeyboardButton(file, callback_data=f"view_file_{file}")] for file in test_files]
    keyboard.append([InlineKeyboardButton("Bosh menyuga qaytish", callback_data="main_menu")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.callback_query.edit_message_text("Qaysi file'dagi testlarni ko'rmoqchisiz?", reply_markup=reply_markup)
    return SELECTING_ACTION

async def view_file_tests(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    file_name = query.data.split('_')[-1]
    tests, error_message = load_tests(file_name)

    if error_message:
        keyboard = [
            [InlineKeyboardButton("Ortga", callback_data="view_tests")],
            [InlineKeyboardButton("Bosh menyuga qaytish", callback_data="main_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(f"Xatolik: {error_message}", reply_markup=reply_markup)
        return SELECTING_ACTION

    if not tests:
        keyboard = [
            [InlineKeyboardButton("Ortga", callback_data="view_tests")],
            [InlineKeyboardButton("Bosh menyuga qaytish", callback_data="main_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(f"'{file_name}' file'ida hozircha testlar mavjud emas.", reply_markup=reply_markup)
        return SELECTING_ACTION

    for test in tests:
        keyboard = [
            [InlineKeyboardButton("O'chirish", callback_data=f"delete_test_{file_name}_{test['id']}")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.reply_text(f"Test ID: {test['id']}\nSavollar soni: {len(test['questions'])}", reply_markup=reply_markup)

    keyboard = [
        [InlineKeyboardButton("Ortga", callback_data="view_tests")],
        [InlineKeyboardButton("Bosh menyuga qaytish", callback_data="main_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.message.reply_text("Barcha testlar ko'rsatildi.", reply_markup=reply_markup)
    return SELECTING_ACTION

async def delete_test(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    file_name, test_id = query.data.split('_')[-2:]
    tests, error_message = load_tests(file_name)

    if error_message:
        await safe_edit_message_text(update, f"Xatolik: {error_message}")
        return ConversationHandler.END

    tests = [test for test in tests if str(test['id']) != test_id]
    save_tests(tests, file_name)

    # Animate deletion process
    message = await query.edit_message_text("Test o'chirilmoqda...")
    for i in range(3):
        await message.edit_text(f"Test o'chirilmoqda{'.' * (i + 1)}")
        await asyncio.sleep(0.3)

    keyboard = [
        [InlineKeyboardButton("Bosh menyuga qaytish", callback_data="main_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await message.edit_text(f"Test (ID: {test_id}) o'chirildi.", reply_markup=reply_markup)
    return SELECTING_ACTION

async def delete_test_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    file_name = query.data.split('_')[-1]
    file_path = f"tests/{file_name}"
    
    if os.path.exists(file_path):
        os.remove(file_path)
        # Animate deletion process
        message = await query.edit_message_text("Test file o'chirilmoqda...")
        for i in range(3):
            await message.edit_text(f"Test file o'chirilmoqda{'.' * (i + 1)}")
            await asyncio.sleep(0.3)
        keyboard = [
            [InlineKeyboardButton("Bosh menyuga qaytish", callback_data="main_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await message.edit_text(f"'{file_name}' nomli test file o'chirildi.", reply_markup=reply_markup)
    else:
        keyboard = [
            [InlineKeyboardButton("Bosh menyuga qaytish", callback_data="main_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(f"'{file_name}' nomli test file topilmadi.", reply_markup=reply_markup)
    return SELECTING_ACTION

# Student functions
async def register_student(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if update.callback_query:
        await update.callback_query.answer()
        message = update.callback_query.message
    else:
        message = update.message

    context.user_data['telegram_id'] = user.id
    await message.reply_text("Ro'yxatdan o'tish uchun ismingizni kiriting:")
    return ENTERING_NAME

async def process_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.message.text
    if not name:
        await update.message.reply_text("Iltimos, to'g'ri ism kiriting:")
        return ENTERING_NAME
    
    context.user_data['first_name'] = name
    await update.message.reply_text("Endi familiyangizni kiriting:")
    return ENTERING_SURNAME

async def process_surname(update: Update, context: ContextTypes.DEFAULT_TYPE):
    surname = update.message.text
    if not surname:
        await update.message.reply_text("Iltimos, to'g'ri familiya kiriting:")
        return ENTERING_SURNAME
    
    context.user_data['last_name'] = surname
    user = update.effective_user
    
    if 'first_name' not in context.user_data:
        await update.message.reply_text("Xatolik yuz berdi. Iltimos, qaytadan ro'yxatdan o'ting.")
        context.user_data.clear()
        return ConversationHandler.END
    
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('INSERT INTO students (first_name, last_name, telegram_id) VALUES (?, ?, ?)',
                      (context.user_data['first_name'], surname, user.id))
        conn.commit()
        
        # Animate registration process
        message = await update.message.reply_text("Ro'yxatdan o'tkazilmoqda...")
        for i in range(3):
            await message.edit_text(f"Ro'yxatdan o'tkazilmoqda{'.' * (i + 1)}")
            await asyncio.sleep(0.3)

        keyboard = [
            [InlineKeyboardButton("Bosh menyu", callback_data="main_menu")],
            [InlineKeyboardButton("Mavjud testlarni ko'rish", callback_data="view_available_tests")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await message.edit_text(
            f"Rahmat, {context.user_data['first_name']}! Siz muvaffaqiyatli ro'yxatdan o'tdingiz.",
            reply_markup=reply_markup
        )
    except sqlite3.IntegrityError:
        await update.message.reply_text("Siz allaqachon ro'yxatdan o'tgansiz.")
    except Exception as e:
        logger.error(f"Registration error: {e}")
        await update.message.reply_text("Ro'yxatdan o'tishda xatolik yuz berdi. Iltimos, qaytadan urinib ko'ring.")
    finally:
        conn.close()
        context.user_data.clear()
    
    return ConversationHandler.END

async def start_test(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM students WHERE telegram_id = ?', (user.id,))
    student = cursor.fetchone()

    if not student:
        keyboard = [[InlineKeyboardButton("Ro'yxatdan o'tish", callback_data="register")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        success = await safe_edit_message_text(update, "Iltimos, avval ro'yxatdan o'ting.", reply_markup=reply_markup)
        conn.close()
        if not success:
            return ConversationHandler.END

    cursor.execute('''
    SELECT DISTINCT test_file
    FROM available_tests
    WHERE student_id = ? AND completed = 0
    ''', (student['id'],))
    available_tests = cursor.fetchall()
    conn.close()

    if not available_tests:
        success = await safe_edit_message_text(update, "Hozircha sizga tayinlangan yangi testlar mavjud emas. Iltimos, keyinroq urinib ko'ring.")
        if not success:
            return ConversationHandler.END

    try:
        keyboard = [[InlineKeyboardButton(file['test_file'], callback_data=f"select_test_file_{file['test_file']}")] for file in available_tests]
        keyboard.append([InlineKeyboardButton("Bosh menyuga qaytish", callback_data="main_menu")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        success = await safe_edit_message_text(update, "Testlar yuklanmoqda...")
        if not success:
            return ConversationHandler.END
        
        for i in range(3):
            success = await safe_edit_message_text(update, f"Testlar yuklanmoqda{'.' * (i + 1)}")
            if not success:
                return ConversationHandler.END
            await asyncio.sleep(0.3)
        
        success = await safe_edit_message_text(update, "Test Menyusi", reply_markup=reply_markup)
        if not success:
            return ConversationHandler.END
        return SELECTING_ACTION
    except Exception as e:
        logger.error(f"Error in start_test: {e}")
        success = await safe_edit_message_text(update, f"Testlarni yuklashda xatolik yuz berdi: {str(e)}. Iltimos, qaytadan urinib ko'ring.")
        if not success:
            return ConversationHandler.END
        return ConversationHandler.END

async def view_my_results(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
    SELECT sr.test_id, sr.correct_answers, sr.wrong_answers, sr.total_questions, sr.rank
    FROM students_results sr
    JOIN students s ON s.id = sr.student_id
    WHERE s.telegram_id = ?
    ''', (user.id,))
    results = cursor.fetchall()
    conn.close()

    if not results:
        keyboard = [
            [InlineKeyboardButton("Bosh menyuga qaytish", callback_data="main_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await safe_edit_message_text(update, "Natija hali mavjud emas.", reply_markup=reply_markup)
        return SELECTING_ACTION

    result_text = "Sizning natijalaringiz:\n\n"
    for result in results:
        result_text += f"Test ID: {result['test_id']}\n"
        result_text += f"To'g'ri javoblar: {result['correct_answers']}\n"
        result_text += f"Xato javoblar: {result['wrong_answers']}\n"
        result_text += f"Jami savollar: {result['total_questions']}\n"
        result_text += f"Reyting: {result['rank']}\n\n"

    keyboard = [
        [InlineKeyboardButton("Bosh menyuga qaytish", callback_data="main_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await safe_edit_message_text(update, result_text, reply_markup=reply_markup)
    return SELECTING_ACTION

async def check_new_tests(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
    SELECT test_file
    FROM available_tests at
    JOIN students s ON s.id = at.student_id
    WHERE s.telegram_id = ? AND at.completed = 0
    ''', (user.id,))
    available_tests = cursor.fetchall()
    conn.close()

    if not available_tests:
        keyboard = [
            [InlineKeyboardButton("Bosh menyuga qaytish", callback_data="main_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await safe_edit_message_text(update, "Hozircha sizga yangi testlar tayinlanmagan.", reply_markup=reply_markup)
        return SELECTING_ACTION

    keyboard = [[InlineKeyboardButton(file['test_file'], callback_data=f"select_test_file_{file['test_file']}")] for file in available_tests]
    keyboard.append([InlineKeyboardButton("Bosh menyuga qaytish", callback_data="main_menu")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    await safe_edit_message_text(update, "Sizga quyidagi yangi testlar tayinlangan:", reply_markup=reply_markup)
    return SELECTING_ACTION

async def view_class_ranking(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
    SELECT s.first_name, s.last_name, 
           SUM(sr.correct_answers) as total_correct,
           SUM(sr.total_questions) as total_questions,
           CAST(SUM(sr.correct_answers) AS FLOAT) / SUM(sr.total_questions) * 100 as percentage
    FROM students s
    LEFT JOIN students_results sr ON s.id = sr.student_id
    GROUP BY s.id
    ORDER BY percentage DESC
    ''')
    rankings = cursor.fetchall()
    conn.close()

    if not rankings:
        keyboard = [
            [InlineKeyboardButton("Bosh menyuga qaytish", callback_data="main_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await safe_edit_message_text(update, "Hozircha reyting ma'lumotlari mavjud emas.", reply_markup=reply_markup)
        return SELECTING_ACTION

    ranking_text = "Sinf reytingi:\n\n"
    for i, ranking in enumerate(rankings, 1):
        ranking_text += f"{i}. {ranking['first_name']} {ranking['last_name']}\n"
        ranking_text += f"   To'g'ri javoblar: {ranking['total_correct']}/{ranking['total_questions']}\n"
        ranking_text += f"   Foiz: {ranking['percentage']:.2f}%\n\n"

    keyboard = [
        [InlineKeyboardButton("Bosh menyuga qaytish", callback_data="main_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await safe_edit_message_text(update, ranking_text, reply_markup=reply_markup)
    return SELECTING_ACTION

async def view_available_tests(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
    SELECT test_file
    FROM available_tests at
    JOIN students s ON s.id = at.student_id
    WHERE s.telegram_id = ? AND at.completed = 0
    ''', (user.id,))
    available_tests = cursor.fetchall()
    conn.close()

    if not available_tests:
        keyboard = [
            [InlineKeyboardButton("Bosh menyuga qaytish", callback_data="main_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await safe_edit_message_text(update, "Hozircha sizga tayinlangan testlar mavjud emas.", reply_markup=reply_markup)
        return SELECTING_ACTION

    keyboard = [[InlineKeyboardButton(file['test_file'], callback_data=f"select_test_file_{file['test_file']}")] for file in available_tests]
    keyboard.append([InlineKeyboardButton("Bosh menyuga qaytish", callback_data="main_menu")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    await safe_edit_message_text(update, "Sizga tayinlangan testlar:", reply_markup=reply_markup)
    return SELECTING_ACTION

async def handle_test_file_error(update: Update, context: ContextTypes.DEFAULT_TYPE, error_message: str):
    keyboard = [
        [InlineKeyboardButton("Yangi test file yaratish", callback_data="create_test_file")],
        [InlineKeyboardButton("Bosh menyuga qaytish", callback_data="main_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await safe_edit_message_text(update, f"{error_message}\n\nYangi test file yaratishni xohlaysizmi?", reply_markup=reply_markup)
    return SELECTING_ACTION

async def add_test(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    file_name = query.data.split('_')[-1]
    context.user_data['current_file'] = file_name
    await query.edit_message_text("Yangi savolni kiriting:")
    context.user_data['creating_test'] = True
    context.user_data['current_test'] = {"questions": [], "answers": [], "correct_answers": []}
    context.user_data['current_step'] = 'question'
    return CREATING_TEST

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    try:
        if query.data == "create_test":
            return await create_test(update, context)
        elif query.data == "create_test_file":
            return await create_test_file(update, context)
        elif query.data.startswith("add_test_"):
            return await add_test(update, context)
        elif query.data.startswith("view_tests_"):
            return await view_file_tests(update, context)
        elif query.data.startswith("start_test_creation_"):
            file_name = query.data.split('_')[-1]
            context.user_data['current_test_file'] = file_name
            await query.edit_message_text("Yangi savolni kiriting:")
            context.user_data['creating_test'] = True
            context.user_data['current_test'] = {"questions": [], "answers": [], "correct_answers": []}
            context.user_data['current_step'] = 'question'
            return CREATING_TEST
        elif query.data.startswith("select_file_"):
            return await select_test_file(update, context)
        elif query.data == "view_tests":
            return await view_tests(update, context)
        elif query.data.startswith("view_file_"):
            return await view_file_tests(update, context)
        elif query.data == "view_results":
            return await view_results(update, context)
        elif query.data == "send_test":
            return await send_test(update, context)
        elif query.data.startswith("send_file_"):
            return await process_send_test(update, context)
        elif query.data.startswith("confirm_send_"):
            return await confirm_send_test(update, context)
        elif query.data == "cancel_send":
            return await cancel_send_test(update, context)
        elif query.data == "register":
            return await register_student(update, context)
        elif query.data == "solve_test":
            return await start_test(update, context)
        elif query.data == "view_my_results":
            return await view_my_results(update, context)
        elif query.data == "check_new_tests":
            return await check_new_tests(update, context)
        elif query.data == "view_class_ranking":
            return await view_class_ranking(update, context)
        elif query.data == "main_menu":
            return await start(update, context)
        elif query.data.startswith("delete_test_"):
            return await delete_test(update, context)
        elif query.data.startswith("delete_file_"):
            return await delete_test_file(update, context)
        elif query.data.startswith("select_test_file_"):
            return await select_test_file(update, context)
        elif query.data == "next_test":
            return await start_selected_test(update, context)
        elif query.data == "view_available_tests":
            return await view_available_tests(update, context)
        elif query.data.startswith("answer_"):
            return await process_answer(update, context)
        else:
            logger.warning(f"Unexpected callback data: {query.data}")
            await safe_edit_message_text(update, f"Kutilmagan xatolik yuz berdi: Noma'lum callback data '{query.data}'. Iltimos, qaytadan urinib ko'ring.")
            return SELECTING_ACTION
    except Exception as e:
        logger.error(f"Xatolik yuz berdi: {e}")
        error_message = f"Xatolik yuz berdi: {str(e)}. Iltimos, qaytadan urinib ko'ring."
        await safe_edit_message_text(update, error_message)
        return SELECTING_ACTION

def main() -> None:
    application = Application.builder().token(TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            SELECTING_ACTION: [
                CallbackQueryHandler(button_callback),
            ],
            CREATING_TEST_FILE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, process_test_file_creation),
            ],
            CREATING_TEST: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, process_test_creation),
                CallbackQueryHandler(process_correct_answer, pattern=r'^correct_'),
                CallbackQueryHandler(add_question, pattern=r'^add_question$'),
                CallbackQueryHandler(finish_test, pattern=r'^finish_test$'),
            ],
            ANSWERING_QUESTION: [
                CallbackQueryHandler(process_answer, pattern=r'^answer_')
            ],
            ENTERING_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, process_name),
            ],
            ENTERING_SURNAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, process_surname),
            ],
        },
        fallbacks=[CommandHandler("start", start)],
    )

    application.add_handler(conv_handler)

    # Run the bot until the user presses Ctrl-C
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
