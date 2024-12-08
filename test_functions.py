import json
import sqlite3
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CallbackQueryHandler, ConversationHandler
import os
import asyncio

# Define conversation states
SELECTING_ACTION, CREATING_TEST_FILE, CREATING_TEST, ANSWERING_QUESTION = range(4)

def ensure_tests_directory_exists():
    if not os.path.exists("tests"):
        os.makedirs("tests")

# Load tests from JSON file
def load_tests(file_name):
    file_path = f"tests/{file_name}"
    if not os.path.exists(file_path):
        return []
    try:
        with open(file_path, 'r') as f:
            content = f.read().strip()
            if not content:
                # If the file is empty, create a default structure
                default_content = []
                with open(file_path, 'w') as f:
                    json.dump(default_content, f)
                return default_content
            return json.loads(content)
    except json.JSONDecodeError:
        print(f"Error: {file_name} contains invalid JSON. Creating a new empty file.")
        default_content = []
        with open(file_path, 'w') as f:
            json.dump(default_content, f)
        return default_content
    except Exception as e:
        print(f"Error loading {file_name}: {str(e)}")
        return []

# Save tests to JSON file
def save_tests(tests, file_name):
    file_path = f"tests/{file_name}"
    with open(file_path, 'w') as f:
        json.dump(tests, f)

# Function to check if user is admin
def is_admin(user_id):
    from main import ADMIN_IDS
    return user_id in ADMIN_IDS

# Create a new test file
async def create_test_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_admin(user.id):
        await update.callback_query.edit_message_text("Kechirasiz, siz admin emassiz.")
        return ConversationHandler.END

    ensure_tests_directory_exists()
    await update.callback_query.edit_message_text("Yangi test file yaratish uchun file nomini kiriting:")
    return CREATING_TEST_FILE

async def process_test_file_creation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    file_name = update.message.text
    if not file_name.endswith('.json'):
        file_name += '.json'

    file_path = f"tests/{file_name}"
    if os.path.exists(file_path):
        await update.message.reply_text(f"'{file_name}' nomli file allaqachon mavjud. Boshqa nom tanlang.")
        return CREATING_TEST_FILE

    # Create an empty JSON file
    with open(file_path, 'w') as f:
        json.dump([], f)

    # Animate file creation
    message = await update.message.reply_text("File yaratilmoqda...")
    for i in range(5):
        await message.edit_text(f"File yaratilmoqda{'.' * (i + 1)}")
        await asyncio.sleep(0.5)

    keyboard = [
        [InlineKeyboardButton("Test yaratishni boshlash", callback_data=f"start_test_creation_{file_name}")],
        [InlineKeyboardButton("Bosh menyuga qaytish", callback_data="main_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await message.edit_text(f"'{file_name}' nomli yangi test file yaratildi.", reply_markup=reply_markup)
    return SELECTING_ACTION

# Create a new test
async def create_test(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_admin(user.id):
        await update.callback_query.edit_message_text("Kechirasiz, siz admin emassiz.")
        return ConversationHandler.END

    ensure_tests_directory_exists()
    test_files = [f for f in os.listdir("tests") if f.endswith('.json')]
    
    if not test_files:
        keyboard = [
            [InlineKeyboardButton("Yangi test file yaratish", callback_data="create_test_file")],
            [InlineKeyboardButton("Bosh menyuga qaytish", callback_data="main_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.callback_query.edit_message_text("Hozircha test file'lari mavjud emas. Yangi file yaratishni xohlaysizmi?", reply_markup=reply_markup)
        return SELECTING_ACTION

    keyboard = [[InlineKeyboardButton(file, callback_data=f"select_file_{file}")] for file in test_files]
    keyboard.append([InlineKeyboardButton("Yangi test file yaratish", callback_data="create_test_file")])
    keyboard.append([InlineKeyboardButton("Bosh menyuga qaytish", callback_data="main_menu")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # Animate the process of loading test files
    message = await update.callback_query.edit_message_text("Test fayllari yuklanmoqda...")
    for i in range(3):
        await message.edit_text(f"Test fayllari yuklanmoqda{'.' * (i + 1)}")
        await asyncio.sleep(0.5)
    
    await message.edit_text("Qaysi file'ga test qo'shmoqchisiz?", reply_markup=reply_markup)
    return SELECTING_ACTION

async def select_test_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    file_name = query.data.split('_')[-1]
    context.user_data['current_test_file'] = file_name

    # Animate file selection
    message = await query.edit_message_text("File tanlanmoqda...")
    for i in range(3):
        await message.edit_text(f"File tanlanmoqda{'.' * (i + 1)}")
        await asyncio.sleep(0.5)

    tests = load_tests(file_name)
    if not tests:
        keyboard = [
            [InlineKeyboardButton("Yangi test qo'shish", callback_data="add_new_test")],
            [InlineKeyboardButton("Boshqa file tanlash", callback_data="create_test")],
            [InlineKeyboardButton("Bosh menyuga qaytish", callback_data="main_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await message.edit_text(f"'{file_name}' file'ida hozircha testlar mavjud emas. Nima qilishni xohlaysiz?", reply_markup=reply_markup)
        return SELECTING_ACTION

    await message.edit_text("Yangi savolni kiriting:")
    context.user_data['creating_test'] = True
    context.user_data['current_test'] = {"questions": [], "answers": [], "correct_answers": []}
    context.user_data['current_step'] = 'question'
    return CREATING_TEST

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
        await asyncio.sleep(0.5)

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
    file_name = context.user_data['current_test_file']
    tests = load_tests(file_name)
    current_test['id'] = len(tests) + 1
    tests.append(current_test)
    save_tests(tests, file_name)

    # Animate test saving process
    message = await query.edit_message_text("Test saqlanmoqda...")
    for i in range(5):
        await message.edit_text(f"Test saqlanmoqda{'.' * (i + 1)}")
        await asyncio.sleep(0.5)

    context.user_data['creating_test'] = False
    context.user_data['current_test'] = None
    context.user_data['current_step'] = None
    context.user_data.pop('current_test_file', None)

    keyboard = [
        [InlineKeyboardButton("Yangi test yaratish", callback_data="create_test")],
        [InlineKeyboardButton("Bosh menyuga qaytish", callback_data="main_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await message.edit_text(f"Test muvaffaqiyatli yaratildi va '{file_name}' file'ga saqlandi!", reply_markup=reply_markup)
    return SELECTING_ACTION

async def send_test(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_admin(user.id):
        await update.callback_query.edit_message_text("Kechirasiz, siz admin emassiz.")
        return ConversationHandler.END

    test_files = [f for f in os.listdir("tests") if f.endswith('.json')]
    if not test_files:
        await update.callback_query.edit_message_text("Hozircha test file'lari mavjud emas.")
        return ConversationHandler.END

    keyboard = [[InlineKeyboardButton(file, callback_data=f"send_file_{file}")] for file in test_files]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.callback_query.edit_message_text("Qaysi file'dagi testlarni jo'natmoqchisiz?", reply_markup=reply_markup)
    return SELECTING_ACTION

async def process_send_test(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    file_name = query.data.split('_')[-1]
    tests = load_tests(file_name)

    if not tests:
        await query.edit_message_text(f"'{file_name}' file'ida hozircha testlar mavjud emas.")
        return SELECTING_ACTION

    context.user_data['selected_test_file'] = file_name

    conn = sqlite3.connect('test_bot.db')
    cursor = conn.cursor()
    cursor.execute('SELECT id, first_name, last_name FROM students')
    students = cursor.fetchall()
    conn.close()

    if not students:
        await query.edit_message_text("Hozircha ro'yxatdan o'tgan o'quvchilar yo'q.")
        return SELECTING_ACTION

    keyboard = [[InlineKeyboardButton(f"{student[1]} {student[2]}", callback_data=f"send_to_{student[0]}")] for student in students]
    keyboard.append([InlineKeyboardButton("Bekor qilish", callback_data="cancel_send")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text("Qaysi o'quvchiga test jo'natmoqchisiz?", reply_markup=reply_markup)
    return SELECTING_ACTION

async def confirm_send_test(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    student_id = int(query.data.split('_')[-1])
    file_name = context.user_data['selected_test_file']

    conn = sqlite3.connect('test_bot.db')
    cursor = conn.cursor()
    cursor.execute('INSERT OR REPLACE INTO available_tests (student_id, test_file) VALUES (?, ?)', (student_id, file_name))
    cursor.execute('SELECT telegram_id FROM students WHERE id = ?', (student_id,))
    student_telegram_id = cursor.fetchone()[0]
    conn.commit()
    conn.close()

    # Animate sending process
    message = await query.edit_message_text("Test jo'natilmoqda...")
    for i in range(5):
        await message.edit_text(f"Test jo'natilmoqda{'.' * (i + 1)}")
        await asyncio.sleep(0.5)

    # Notify the student
    keyboard = [[InlineKeyboardButton("Testni boshlash", callback_data="start_test")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await context.bot.send_message(chat_id=student_telegram_id, text="Sizga yangi test tayinlandi!", reply_markup=reply_markup)

    keyboard = [[InlineKeyboardButton("Bosh menyuga qaytish", callback_data="main_menu")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await message.edit_text(f"Test muvaffaqiyatli jo'natildi!", reply_markup=reply_markup)
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

async def view_results(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_admin(user.id):
        await update.callback_query.edit_message_text("Kechirasiz, siz admin emassiz.")
        return ConversationHandler.END

    conn = sqlite3.connect('test_bot.db')
    cursor = conn.cursor()
    cursor.execute('''
    SELECT s.first_name, s.last_name, s.telegram_id, sr.correct_answers, sr.wrong_answers, sr.total_questions, sr.rank
    FROM students s
    JOIN students_results sr ON s.id = sr.student_id
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
    for result in results:
        result_text += f"Ism: {result[0]} {result[1]}\n"
        result_text += f"Telegram ID: {result[2]}\n"
        result_text += f"To'g'ri javoblar: {result[3]}\n"
        result_text += f"Xato javoblar: {result[4]}\n"
        result_text += f"Jami savollar: {result[5]}\n"
        result_text += f"Reyting: {result[6]}\n\n"

    # Split the results into chunks if they're too long
    max_message_length = 4096
    result_chunks = [result_text[i:i+max_message_length] for i in range(0, len(result_text), max_message_length)]

    for chunk in result_chunks:
        await update.callback_query.message.reply_text(chunk)

    keyboard = [
        [InlineKeyboardButton("Bosh menyuga qaytish", callback_data="main_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.callback_query.message.reply_text("Barcha natijalar ko'rsatildi.", reply_markup=reply_markup)
    return SELECTING_ACTION

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
    tests = load_tests(file_name)

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
    tests = load_tests(file_name)
    tests = [test for test in tests if str(test['id']) != test_id]
    save_tests(tests, file_name)

    # Animate deletion process
    message = await query.edit_message_text("Test o'chirilmoqda...")
    for i in range(3):
        await message.edit_text(f"Test o'chirilmoqda{'.' * (i + 1)}")
        await asyncio.sleep(0.5)

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
            await asyncio.sleep(0.5)
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

async def add_new_test(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    # Animate the process of preparing to add a new test
    message = await query.edit_message_text("Yangi test qo'shishga tayyorlanmoqda...")
    for i in range(3):
        await message.edit_text(f"Yangi test qo'shishga tayyorlanmoqda{'.' * (i + 1)}")
        await asyncio.sleep(0.5)

    await message.edit_text("Yangi savolni kiriting:")
    context.user_data['creating_test'] = True
    context.user_data['current_test'] = {"questions": [], "answers": [], "correct_answers": []}
    context.user_data['current_step'] = 'question'
    return CREATING_TEST
