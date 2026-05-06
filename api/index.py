import os
import time
import telebot
from telebot import types
from flask import Flask, request
from openai import OpenAI
from supabase import create_client, Client

app = Flask(__name__)

# Ключи из Vercel
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_KEY')

bot = telebot.TeleBot(TELEGRAM_TOKEN, threaded=False)
client_ai = OpenAI(api_key=OPENAI_API_KEY, base_url='https://codex.sale/v1')
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Хранилище сессий для диалогов
user_states = {}

SYSTEM_PROMPT = """
Role: Ты — Арт-Директор и Продюсер AI-инфлюенсера Leya.
Persona: 23 года, Харьков. Брюнетка, гетерохромия, брекеты, ямочки на щеках.
Esthetics: Minimal, greige, cinematic lighting.
Task: Создавать профессиональные контент-планы и промпты для генерации.

Правила выдачи СЕТА фотографий:
Если просят несколько фото для одной ситуации, КАЖДЫЙ промпт должен отличаться:
- Photo 1: Wide angle (общий план локации, Лея в полный рост).
- Photo 2: Medium shot (Лея по пояс, занята делом).
- Photo 3: Close-up portrait (крупный план лица, эмоция, фокус на глаза/брекеты).
- Photo 4: Detail/Macro (деталь: руки с кофе, фактура одежды).
- Photo 5: Alternative angle (со спины или через отражение).
"""

def get_main_keyboard():
    markup = types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    btns = ["📝 Создать пост + фото", "📸 Создать Фото-Сет", "🖼 Генератор картинок", "💾 Сохранить лор"]
    markup.add(*(types.KeyboardButton(b) for b in btns))
    return markup

@app.route('/', methods=['POST'])
def webhook():
    if request.headers.get('content-type') == 'application/json':
        json_string = request.get_data().decode('utf-8')
        update = telebot.types.Update.de_json(json_string)
        bot.process_new_updates([update])
        return ''
    return '403', 403

@bot.message_handler(commands=['start'])
def start(message):
    bot.send_message(message.chat.id, "Привет, Саша! Я твой Контент-Завод для Леи. Что будем делать сегодня?", reply_markup=get_main_keyboard())

# --- РЕЖИМ БРИФА (Фото-сет и Посты) ---

@bot.message_handler(func=lambda message: message.text in ["📝 Создать пост + фото", "📸 Создать Фото-Сет"])
def start_briefing(message):
    is_set = (message.text == "📸 Создать Фото-Сет")
    user_states[message.chat.id] = {'is_set': is_set, 'step': 1}
    
    bot.send_message(message.chat.id, "Отлично. Давай настроим атмосферу.\n\n📍 Шаг 1/3: Опиши локацию или ситуацию (Например: 'Пьет кофе на балконе, утренний свет').", reply_markup=types.ReplyKeyboardRemove())
    bot.register_next_step_handler(message, process_brief_step_1)

def process_brief_step_1(message):
    user_states[message.chat.id]['idea'] = message.text
    bot.send_message(message.chat.id, "🎨 Шаг 2/3: Какое настроение и эстетика? (Например: 'уютная меланхолия', 'бодрое утро', 'fashion minimal').")
    bot.register_next_step_handler(message, process_brief_step_2)

def process_brief_step_2(message):
    user_states[message.chat.id]['mood'] = message.text
    is_set = user_states[message.chat.id]['is_set']
    
    if is_set:
        markup = types.ReplyKeyboardMarkup(row_width=3, resize_keyboard=True, one_time_keyboard=True)
        markup.add("3 фото", "5 фото", "7 фото")
        bot.send_message(message.chat.id, "🔢 Шаг 3/3: Сколько промптов (ракурсов) делаем для этого сета?", reply_markup=markup)
        bot.register_next_step_handler(message, finish_briefing)
    else:
        user_states[message.chat.id]['count'] = "1" # Для одиночного поста всегда 1 фото
        finish_briefing(message)

def finish_briefing(message):
    state = user_states.get(message.chat.id, {})
    count = message.text if state['is_set'] else "1 фото"
    idea = state.get('idea', '')
    mood = state.get('mood', '')
    
    bot.send_message(message.chat.id, "⚙️ Бриф принят! Иду генерировать контент. Это займет секунд 15-20...", reply_markup=get_main_keyboard())
    
    task = f"""
    Ситуация: {idea}
    Настроение/Эстетика: {mood}
    Задача: 
    1. Напиши пост для Instagram (текст на RU, затем перевод на EN).
    2. Сгенерируй {count} профессиональных VISUAL PROMPT(s) на английском для этой ситуации.
    Если промптов больше одного, обязательно меняй ракурсы, крупность плана (от общего к макро) и позы Леи!
    """
    
    try:
        res = supabase.table('leya_lore').select('*').order('created_at', desc=True).limit(3).execute()
        hist = "\n".join([f"- {i['event_description']}" for i in res.data[::-1]]) if res.data else "Начало."
        
        ai_res = client_ai.chat.completions.create(
            model="gpt-5.5",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT}, 
                {"role": "user", "content": f"Память:\n{hist}\n\n{task}"}
            ]
        )
        final_text = ai_res.choices[0].message.content
        user_states[message.chat.id]['last_content'] = final_text
        bot.send_message(message.chat.id, final_text)
    except Exception as e:
        bot.reply_to(message, f"❌ Ошибка генерации: {e}")

# --- ВИЗУАЛИЗАТОР (Со шкалой) ---

@bot.message_handler(func=lambda message: message.text == "🖼 Генератор картинок")
def start_photo_chain(message):
    msg = bot.send_message(message.chat.id, "📝 Вставь промпт для фото на английском (скопируй из сгенерированных выше):", reply_markup=types.ReplyKeyboardRemove())
    bot.register_next_step_handler(msg, get_prompt_step)

def get_prompt_step(message):
    if not message.text:
        bot.send_message(message.chat.id, "Отмена.", reply_markup=get_main_keyboard())
        return
    user_states[message.chat.id] = {'temp_prompt': message.text}
    msg = bot.send_message(message.chat.id, "📸 Пришли фото-референс или напиши /skip")
    bot.register_next_step_handler(msg, get_photo_step)

def get_photo_step(message):
    ref_url = None
    if message.content_type == 'photo':
        f_info = bot.get_file(message.photo[-1].file_id)
        ref_url = f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{f_info.file_path}"
    elif message.text != '/skip':
        pass # Игнорим если не фото и не скип

    prompt = user_states[message.chat.id]['temp_prompt']
    
    progress_msg = bot.send_message(message.chat.id, "🎨 Обработка: [░░░░░░░░░░] 0%")
    try:
        time.sleep(1)
        bot.edit_message_text("🎨 Рендер: [▓▓▓▓░░░░░░] 40%", message.chat.id, progress_msg.message_id)
        
        response = client_ai.images.generate(
            model="gpt-image-2",
            prompt=prompt,
            extra_body={"image": ref_url} if ref_url else {}
        )
        
        bot.edit_message_text("🎨 Финализация: [▓▓▓▓▓▓▓▓▓░] 90%", message.chat.id, progress_msg.message_id)
        image_url = response.data[0].url
        bot.delete_message(message.chat.id, progress_msg.message_id)
        bot.send_photo(message.chat.id, image_url, caption="Твой контент ✨", reply_markup=get_main_keyboard())
    except Exception as e:
        bot.edit_message_text(f"❌ Сбой: {e}", message.chat.id, progress_msg.message_id)
        bot.send_message(message.chat.id, "Повторим?", reply_markup=get_main_keyboard())

# --- СОХРАНЕНИЕ ---

@bot.message_handler(func=lambda message: message.text == "💾 Сохранить лор")
def save_db(message):
    bot.reply_to(message, "✅ Событие добавлено в базу. Завтра Лея это вспомнит.")

@app.route('/', methods=['GET'])
def index():
    return "Content Factory Active"
