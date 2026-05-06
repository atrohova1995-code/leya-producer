import os
import telebot
from telebot import types
from flask import Flask, request
from openai import OpenAI
from supabase import create_client, Client

app = Flask(__name__)

# Ключи из настроек Vercel
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_KEY')

bot = telebot.TeleBot(TELEGRAM_TOKEN, threaded=False)
client_ai = OpenAI(api_key=OPENAI_API_KEY, base_url='https://codex.sale/v1')
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Глобальный словарь для временного хранения выбора пользователя (в рамках сессии)
user_states = {}

SYSTEM_PROMPT = """
Role: Ты — Креативный ИИ-Продюсер для digital-persona Leya.
Character: 23 года, брюнетка, гетерохромия (зеленый/голубой глаз), брекеты, ямочки. Стиль: soft cyber, cinematic. Характер: INFP, глубокая, меланхоличная, но теплая.
Format:
1. Событие дня (Lore): [описание]
2. Промпт для поста: [инструкция]
3. Visual Prompt: [English description for image generation]
"""

def get_main_keyboard():
    markup = types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    btn1 = types.KeyboardButton("🌅 Утро")
    btn2 = types.KeyboardButton("☀️ День")
    btn3 = types.KeyboardButton("🌆 Вечер")
    btn4 = types.KeyboardButton("🌃 Ночь")
    btn5 = types.KeyboardButton("✨ Свой сюжет")
    btn6 = types.KeyboardButton("💾 Сохранить в память")
    markup.add(btn1, btn2, btn3, btn4, btn5, btn6)
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
    bot.send_message(message.chat.id, "Привет! Я пульт управления Леей. Выбери время суток или нажми 'Свой сюжет', чтобы задать направление.", reply_markup=get_main_keyboard())

@bot.message_handler(func=lambda message: message.text in ["🌅 Утро", "☀️ День", "🌆 Вечер", "🌃 Ночь"])
def handle_time_selection(message):
    time_of_day = message.text
    generate_content(message, time_of_day)

@bot.message_handler(func=lambda message: message.text == "✨ Свой сюжет")
def custom_wish_start(message):
    msg = bot.send_message(message.chat.id, "Что сегодня должно произойти с Леей? Напиши кратко свои пожелания:")
    bot.register_next_step_handler(msg, handle_custom_wish)

def handle_custom_wish(message):
    wish = message.text
    generate_content(message, "Любое", wish)

@bot.message_handler(func=lambda message: message.text == "💾 Сохранить в память")
def save_to_memory(message):
    last_text = user_states.get(message.chat.id, {}).get('last_lore')
    if not last_text:
        bot.reply_to(message, "Сначала сгенерируй что-нибудь!")
        return
    
    try:
        # Извлекаем только блок Lore
        lore_to_save = last_text.split("2. Промпт")[0].replace("1. Событие дня (Lore):", "").strip()
        supabase.table('leya_lore').insert({"event_description": lore_to_save}).execute()
        bot.reply_to(message, "✅ Лея запомнила это событие!")
    except Exception as e:
        bot.reply_to(message, f"Ошибка сохранения: {e}")

def generate_content(message, time_of_day, wish=None):
    bot.send_message(message.chat.id, f"⏳ Работаю над образом... (Время: {time_of_day})")
    try:
        # Память
        response = supabase.table('leya_lore').select('*').order('created_at', desc=True).limit(3).execute()
        history = response.data
        history_text = "\n".join([f"- {i['event_description']}" for i in history[::-1]]) if history else "Начало истории."

        prompt = f"Контекст прошлых дней:\n{history_text}\n\n"
        prompt += f"Задача: Опиши событие, которое происходит в это время суток: {time_of_day}. "
        if wish:
            prompt += f"Учти пожелание пользователя: {wish}"

        ai_response = client_ai.chat.completions.create(
            model="gpt-5.5",
            messages=[{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": prompt}]
        )
        
        full_text = ai_response.choices[0].message.content
        # Сохраняем в сессию, чтобы кнопка 'Сохранить' знала, что записывать
        user_states[message.chat.id] = {'last_lore': full_text}
        
        bot.send_message(message.chat.id, full_text, reply_markup=get_main_keyboard())
    except Exception as e:
        bot.reply_to(message, f"❌ Ошибка: {e}")

@app.route('/', methods=['GET'])
def index():
    return "Leya Admin Panel Active"
