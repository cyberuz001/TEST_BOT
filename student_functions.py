import json
import sqlite3
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
import asyncio
import os

# Define conversation states
ENTERING_NAME, ENTERING_SURNAME, SELECTING_ACTION, ANSWERING_QUESTION = range(4)

def load_tests(file_name=None):
    if file_name:
        file_path = f"tests/{file_name}"
        if not os.path.exists(file_path):
            return []
        try:
            with open(file_path, 'r') as f:
                content = f.read().strip()
                if not content:
                    return []
                return json.loads(content)
        except json.JSONDecodeError:
            print(f"Error: {file_name} contains invalid JSON.")
            return []
        except Exception as e:
            print(f"Error loading {file_name}: {str(e)}")
            return []
    else:
        try:
            with open('tests.json', 'r') as f:
                content = f.read().strip()
                if not content:
                    return []
                return json.loads(content)
        except FileNotFoundError:
            return []
        except json.JSONDecodeError:
            print("Error: tests.json contains invalid JSON.")
            return []
        except Exception as e:
            print(f"Error loading tests.json: {str(e)}")
            return []

async def register_student(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if update.callback_query:
        await update.callback_query.answer()
        message = update.callback_query.message
    else:
        message = update.message

    conn = sqlite3.connect('test_bot.db')
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM students WHERE telegram_id = ?', (user.id,))
    existing_user = cursor.fetchone()
    conn.close()

    if existing_user:
        await message.reply_text(f"Siz allaqachon ro'yxatdan o'tgansiz, {existing_user[1]} {existing_user[2]}!")
        return ConversationHandler.END

    await message.reply_text("Ro'yxatdan o'tish uchun ismingizni kiriting:")
    return ENTERING_NAME

async def process_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['first_name'] = update.message.text
    await update.message.reply_text("Endi familiyangizni kiriting:")
    return ENTERING_SURNAME

async def process_surname(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if 'first_name' not in context.user_data:
        await update.message.reply_text("Xatolik yuz berdi. Iltimos, ro'yxatdan o'tish jarayonini qaytadan boshlang.")
        return ConversationHandler.END

    context.user_data['last_name'] = update.message.text
    user = update.effective_user
    
    conn = sqlite3.connect('test_bot.db')
    cursor = conn.cursor()
    cursor.execute('INSERT INTO students (first_name, last_name, telegram_id) VALUES (?, ?, ?)',
                   (context.user_data['first_name'], context.user_data['last_name'], user.id))
    conn.commit()
    conn.close()

    # Animate registration process
    message = await update.message.reply_text("Ro'yxatdan o'tkazilmoqda...")
    for i in range(5):
        await message.edit_text(f"Ro'yxatdan o'tkazilmoqda{'.' * (i + 1)}")
        await asyncio.sleep(0.5)

    keyboard = [
        [InlineKeyboardButton("Bosh menyu", callback_data="main_menu")],
        [InlineKeyboardButton("Mavjud testlarni ko'rish", callback_data="view_available_tests")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await message.edit_text(f"Rahmat, {context.user_data['first_name']}! Siz muvaffaqiyatli ro'yxatdan o'tdingiz.", reply_markup=reply_markup)

    context.user_data.clear()
    return ConversationHandler.END

async def start_test(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    conn = sqlite3.connect('test_bot.db')
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM students WHERE telegram_id = ?', (user.id,))
    student = cursor.fetchone()

    if not student:
        keyboard = [[InlineKeyboardButton("Ro'yxatdan o'tish", callback_data="register")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        if update.callback_query:
            await update.callback_query.edit_message_text("Iltimos, avval ro'yxatdan o'ting.", reply_markup=reply_markup)
        else:
            await update.message.reply_text("Iltimos, avval ro'yxatdan o'ting.", reply_markup=reply_markup)
        conn.close()
        return ConversationHandler.END

    # Check if there's an available test for this student that hasn't been taken yet
    cursor.execute('''
    SELECT at.test_file
    FROM available_tests at
    LEFT JOIN students_results sr ON at.id = sr.test_id AND sr.student_id = ?
    WHERE at.student_id = ? AND sr.id IS NULL
    LIMIT 1
    ''', (student[0], student[0]))
    available_test = cursor.fetchone()
    conn.close()

    if not available_test:
        keyboard = [
            [InlineKeyboardButton("Bosh menyu", callback_data="main_menu")],
            [InlineKeyboardButton("Yangi testlar bormi?", callback_data="check_new_tests")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        message = "Hozircha sizga yangi test yo'q. Iltimos, keyinroq urinib ko'ring."
        if update.callback_query:
            await update.callback_query.edit_message_text(message, reply_markup=reply_markup)
        else:
            await update.message.reply_text(message, reply_markup=reply_markup)
        return ConversationHandler.END

    test_file = available_test[0]
    tests = load_tests(test_file)

    if not tests:
        keyboard = [
            [InlineKeyboardButton("Bosh menyu", callback_data="main_menu")],
            [InlineKeyboardButton("Yangi testlar bormi?", callback_data="check_new_tests")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        message = "Kechirasiz, test fayli bo'sh yoki mavjud emas."
        if update.callback_query:
            await update.callback_query.edit_message_text(message, reply_markup=reply_markup)
        else:
            await update.message.reply_text(message, reply_markup=reply_markup)
        return ConversationHandler.END

    # Start the first test in the file
    test = tests[0]
    context.user_data['current_test'] = test
    context.user_data['current_question'] = 0
    context.user_data['answers'] = []
    context.user_data['test_file'] = test_file
    await send_question(update, context)

async def view_available_tests(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    conn = sqlite3.connect('test_bot.db')
    cursor = conn.cursor()
    cursor.execute('SELECT id FROM students WHERE telegram_id = ?', (user.id,))
    student = cursor.fetchone()

    if not student:
        keyboard = [[InlineKeyboardButton("Ro'yxatdan o'tish", callback_data="register")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.callback_query.edit_message_text("Iltimos, avval ro'yxatdan o'ting.", reply_markup=reply_markup)
        return ConversationHandler.END

    cursor.execute('SELECT test_file FROM available_tests WHERE student_id = ?', (student[0],))
    available_tests = cursor.fetchall()
    conn.close()

    if not available_tests:
        keyboard = [[InlineKeyboardButton("Bosh menyu", callback_data="main_menu")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.callback_query.edit_message_text("Hozircha sizga tayinlangan testlar yo'q.", reply_markup=reply_markup)
        return ConversationHandler.END

    keyboard = [[InlineKeyboardButton(test[0], callback_data=f"start_test_{test[0]}")] for test in available_tests]
    keyboard.append([InlineKeyboardButton("Bosh menyu", callback_data="main_menu")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # Animate the process of loading available tests
    message = await update.callback_query.edit_message_text("Mavjud testlar yuklanmoqda...")
    for i in range(3):
        await message.edit_text(f"Mavjud testlar yuklanmoqda{'.' * (i + 1)}")
        await asyncio.sleep(0.5)
    
    await message.edit_text("Quyidagi testlardan birini tanlang:", reply_markup=reply_markup)
    return SELECTING_ACTION

async def send_question(update: Update, context: ContextTypes.DEFAULT_TYPE):
    current_test = context.user_data['current_test']
    current_question = context.user_data['current_question']

    if current_question >= len(current_test['questions']):
        return await finish_test(update, context)

    question = current_test['questions'][current_question]
    answers = current_test['answers'][current_question]

    keyboard = [
        [InlineKeyboardButton(answer.split(') ')[1], callback_data=f"answer_{answer.split(') ')[0]}")]
        for answer in answers
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    if update.callback_query:
        await update.callback_query.edit_message_text(f"Savol {current_question + 1}: {question}", reply_markup=reply_markup)
    else:
        await update.message.reply_text(f"Savol {current_question + 1}: {question}", reply_markup=reply_markup)

    return ANSWERING_QUESTION

async def process_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_answer = query.data.split('_')[1]
    context.user_data['answers'].append(user_answer)

    current_test = context.user_data['current_test']
    current_question = context.user_data['current_question']
    correct_answer = current_test['correct_answers'][current_question]

    if user_answer == correct_answer:
        await query.edit_message_text("To'g'ri javob! 👍")
    else:
        await query.edit_message_text(f"Noto'g'ri javob. To'g'ri javob: {correct_answer}")

    await asyncio.sleep(1)  # Give the user a moment to see the result

    context.user_data['current_question'] += 1
    return await send_question(update, context)

async def finish_test(update: Update, context: ContextTypes.DEFAULT_TYPE):
    current_test = context.user_data['current_test']
    user_answers = context.user_data['answers']
    correct_answers = current_test['correct_answers']

    total_questions = len(correct_answers)
    correct_count = sum([1 for user, correct in zip(user_answers, correct_answers) if user == correct])
    wrong_count = total_questions - correct_count

    user = update.effective_user
    conn = sqlite3.connect('test_bot.db')
    cursor = conn.cursor()
    cursor.execute('SELECT id FROM students WHERE telegram_id = ?', (user.id,))
    student_id = cursor.fetchone()[0]

    cursor.execute('''
    INSERT INTO students_results (student_id, test_id, correct_answers, wrong_answers, total_questions)
    VALUES (?, ?, ?, ?, ?)
    ''', (student_id, current_test['id'], correct_count, wrong_count, total_questions))
    conn.commit()

    # Calculate and update rank
    cursor.execute('''
    SELECT id, correct_answers FROM students_results
    WHERE test_id = ?
    ORDER BY correct_answers DESC
    ''', (current_test['id'],))
    results = cursor.fetchall()

    for rank, (result_id, _) in enumerate(results, start=1):
        cursor.execute('UPDATE students_results SET rank = ? WHERE id = ?', (rank, result_id))

    conn.commit()
    conn.close()

    message = f"Test yakunlandi!\n\n"
    message += f"Jami savollar: {total_questions}\n"
    message += f"To'g'ri javoblar: {correct_count}\n"
    message += f"Noto'g'ri javoblar: {wrong_count}\n"
    message += f"Foiz: {(correct_count / total_questions) * 100:.2f}%"

    keyboard = [
        [InlineKeyboardButton("Bosh menyu", callback_data="main_menu")],
        [InlineKeyboardButton("Boshqa testni boshlash", callback_data="view_available_tests")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    if update.callback_query:
        await update.callback_query.edit_message_text(message, reply_markup=reply_markup)
    else:
        await update.message.reply_text(message, reply_markup=reply_markup)

    # Clear user data
    context.user_data.clear()

    return ConversationHandler.END

async def select_test_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    file_name = query.data.split('_')[-1]
    tests = load_tests(file_name)

    if not tests:
        keyboard = [
            [InlineKeyboardButton("Bosh menyu", callback_data="main_menu")],
            [InlineKeyboardButton("Boshqa testni tanlash", callback_data="view_available_tests")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(f"Kechirasiz, '{file_name}' fayli bo'sh yoki mavjud emas.", reply_markup=reply_markup)
        return SELECTING_ACTION

    context.user_data['current_test'] = tests[0]
    context.user_data['current_question'] = 0
    context.user_data['answers'] = []

    return await send_question(update, context)

async def start_selected_test(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    file_name = query.data.split('_')[-1]
    tests = load_tests(file_name)

    if not tests:
        keyboard = [
            [InlineKeyboardButton("Bosh menyu", callback_data="main_menu")],
            [InlineKeyboardButton("Boshqa testni tanlash", callback_data="view_available_tests")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(f"Kechirasiz, '{file_name}' fayli bo'sh yoki mavjud emas.", reply_markup=reply_markup)
        return SELECTING_ACTION

    context.user_data['current_test'] = tests[0]
    context.user_data['current_question'] = 0
    context.user_data['answers'] = []

    return await send_question(update, context)

async def view_my_results(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    conn = sqlite3.connect('test_bot.db')
    cursor = conn.cursor()
    cursor.execute('''
    SELECT sr.test_id, sr.correct_answers, sr.wrong_answers, sr.total_questions, sr.rank
    FROM students_results sr
    JOIN students s ON s.id = sr.student_id
    WHERE s.telegram_id = ?
    ORDER BY sr.id DESC
    LIMIT 5
    ''', (user.id,))
    results = cursor.fetchall()
    conn.close()

    if not results:
        message = "Siz hali hech qanday test yechmagansiz."
    else:
        message = "Sizning so'nggi 5 ta test natijalaringiz:\n\n"
        for result in results:
            message += f"Test ID: {result[0]}\n"
            message += f"To'g'ri javoblar: {result[1]}\n"
            message += f"Noto'g'ri javoblar: {result[2]}\n"
            message += f"Jami savollar: {result[3]}\n"
            message += f"Reyting: {result[4]}\n\n"

    keyboard = [[InlineKeyboardButton("Bosh menyu", callback_data="main_menu")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if update.callback_query:
        await update.callback_query.edit_message_text(message, reply_markup=reply_markup)
    else:
        await update.message.reply_text(message, reply_markup=reply_markup)
    
    return SELECTING_ACTION

async def check_new_tests(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    conn = sqlite3.connect('test_bot.db')
    cursor = conn.cursor()
    cursor.execute('''
    SELECT at.test_file
    FROM available_tests at
    JOIN students s ON s.id = at.student_id
    WHERE s.telegram_id = ? AND at.id NOT IN (SELECT test_id FROM students_results WHERE student_id = s.id)
    ''', (user.id,))
    new_tests = cursor.fetchall()
    conn.close()

    if not new_tests:
        message = "Hozircha sizga yangi testlar yo'q."
    else:
        message = "Sizga yangi testlar mavjud:\n\n"
        for test in new_tests:
            message += f"- {test[0]}\n"
        message += "\nTest yechishni boshlash uchun 'Test yechish' tugmasini bosing."

    keyboard = [
        [InlineKeyboardButton("Test yechish", callback_data="solve_test")],
        [InlineKeyboardButton("Bosh menyu", callback_data="main_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if update.callback_query:
        await update.callback_query.edit_message_text(message, reply_markup=reply_markup)
    else:
        await update.message.reply_text(message, reply_markup=reply_markup)
    
    return SELECTING_ACTION

async def view_class_ranking(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    conn = sqlite3.connect('test_bot.db')
    cursor = conn.cursor()
    cursor.execute('''
    SELECT s.first_name, s.last_name, COUNT(sr.id) as tests_completed
    FROM students s
    LEFT JOIN students_results sr ON s.id = sr.student_id
    GROUP BY s.id
    ORDER BY tests_completed DESC
    LIMIT 10
    ''')
    rankings = cursor.fetchall()
    
    cursor.execute('''
    SELECT COUNT(sr.id) as tests_completed
    FROM students s
    LEFT JOIN students_results sr ON s.id = sr.student_id
    WHERE s.telegram_id = ?
    ''', (user.id,))
    user_tests_completed = cursor.fetchone()[0]
    
    cursor.execute('''
    SELECT COUNT(*) + 1
    FROM (
        SELECT s.id, COUNT(sr.id) as tests_completed
        FROM students s
        LEFT JOIN students_results sr ON s.id = sr.student_id
        GROUP BY s.id
        HAVING tests_completed > ?
    ) as rankings
    ''', (user_tests_completed,))
    user_rank = cursor.fetchone()[0]
    
    conn.close()

    message = "Sinf reytingi (eng ko'p test yechganlar):\n\n"
    for i, (first_name, last_name, tests_completed) in enumerate(rankings, 1):
        message += f"{i}. {first_name} {last_name}: {tests_completed} ta test\n"
    
    message += f"\nSizning reytingingiz: {user_rank}\n"
    message += f"Siz yechgan testlar soni: {user_tests_completed}"

    keyboard = [[InlineKeyboardButton("Bosh menyu", callback_data="main_menu")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if update.callback_query:
        await update.callback_query.edit_message_text(message, reply_markup=reply_markup)
    else:
        await update.message.reply_text(message, reply_markup=reply_markup)
    
    return SELECTING_ACTION

