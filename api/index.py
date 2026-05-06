import os
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

# Хранилище сессий
user_states = {}

# Личность Леи и инструкции (на базе User Summary)
SYSTEM_PROMPT = """
Role: Ты — Старший Продюсер и Сценарист AI-инфлюенсера Leya.
Persona: 23 года, Харьков. Брюнетка, гетерохромия (зеленый/голубой глаз), брекеты, ямочки на щеках.
Esthetics: Minimalist, "greige" palette, cozy realism.
Task: Создавать контент для Instagram на Русском и Английском языках.

Format for Output:
📸 СОБЫТИЕ: [Краткое описание ситуации]

📝 POST (RU): [Текст поста]
📝 POST (EN): [Professional English translation]

🖼 VISUAL PROMPTS (EN):
Если это сет, пронумеруй каждый ракурс (Wide shot, Medium shot, Close-up, Detail). 
Описывай свет, позы, одежду и локации Харькова (или интерьер в стиле грейдж).
"""

def get_main_keyboard():
    markup = types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    # Оставили только контентные кнопки
    btns = ["📝 Пост + Промпт", "📸 Фото-Сет (Пакет)", "📅 План на неделю", "⚙️ Настройки", "💾 В память"]
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
    bot.send_message(message.chat.id, "Контент-центр Leya: Prompt Engineering Mode. Что планируем сегодня?", reply_markup=get_main_keyboard())

# --- НАСТРОЙКИ МОДЕЛЕЙ ---

@bot.message_handler(func=lambda message: message.text == "⚙️ Настройки")
def settings(message):
    current = user_states.get(message.chat.id, {}).get('model', 'gpt-5.5')
    markup = types.InlineKeyboardMarkup(row_width=1)
    models = {
        "gpt-5.5": "🔥 GPT-5.5 (Максимальное качество)",
        "gpt-5.4": "⚡️ GPT-5.4 (Сбалансированная)",
        "gpt-5.4-mini": "🚀 GPT-5.4 Mini (Быстрая)"
    }
    for m_id, m_name in models.items():
        prefix = "✅ " if current == m_id else ""
        markup.add(types.InlineKeyboardButton(f"{prefix}{m_name}", callback_data=f"set_{m_id}"))
    bot.send_message(message.chat.id, f"Текущая модель для текстов: **{current}**", reply_markup=markup, parse_mode="Markdown")

@bot.callback_query_handler(func=lambda call: call.data.startswith('set_'))
def set_model(call):
    new_m = call.data.replace('set_', '')
    if call.message.chat.id not in user_states: user_states[call.message.chat.id] = {}
    user_states[call.message.chat.id]['model'] = new_m
    bot.answer_callback_query(call.id, f"Выбрана {new_m}")
    settings(call.message)

# --- ПРЯМОЙ ВВОД И БРИФИНГ ---

@bot.message_handler(func=lambda message: message.text not in ["📝 Пост + Промпт", "📸 Фото-Сет (Пакет)", "📅 План на неделю", "⚙️ Настройки", "💾 В память"])
def direct_input(message):
    generate_content(message, f"Реализуй идею: {message.text}")

@bot.message_handler(func=lambda message: message.text in ["📝 Пост + Промпт", "📸 Фото-Сет (Пакет)"])
def start_brief(message):
    is_set = "Фото-Сет" in message.text
    user_states[message.chat.id] = {'is_set': is_set}
    msg = bot.send_message(message.chat.id, "📍 Опиши ситуацию (локация, действие):", reply_markup=types.ReplyKeyboardRemove())
    bot.register_next_step_handler(msg, get_idea)

def get_idea(message):
    user_states[message.chat.id]['idea'] = message.text
    if user_states[message.chat.id]['is_set']:
        markup = types.ReplyKeyboardMarkup(row_width=3, resize_keyboard=True, one_time_keyboard=True)
        markup.add("3 промпта", "5 промптов", "7 промптов")
        msg = bot.send_message(message.chat.id, "🔢 Сколько вариантов ракурсов нужно в сете?", reply_markup=markup)
        bot.register_next_step_handler(msg, finish_batch)
    else:
        finish_batch(message)

def finish_batch(message):
    state = user_states[message.chat.id]
    count = message.text if state['is_set'] else "1"
    model = state.get('model', 'gpt-5.5')
    
    bot.send_message(message.chat.id, f"⚙️ Генерирую промпты... [{model}]", reply_markup=get_main_keyboard())
    
    task = f"Событие: {state['idea']}. Сделай пост (RU/EN) и {count} детальных Visual Prompts (EN) с разными ракурсами и планами."
    generate_content(message, task, model)

def generate_content(message, task, model='gpt-5.5'):
    try:
        res = supabase.table('leya_lore').select('*').order('created_at', desc=True).limit(3).execute()
        hist = "\n".join([f"- {i['event_description']}" for i in res.data[::-1]]) if res.data else "Начало."
        
        ai_res = client_ai.chat.completions.create(
            model=model,
            messages=[{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": f"Память:\n{hist}\n\n{task}"}]
        )
        final_text = ai_res.choices[0].message.content
        user_states[message.chat.id]['last_content'] = final_text
        bot.send_message(message.chat.id, final_text)
    except Exception as e:
        bot.reply_to(message, f"Ошибка: {e}")

@bot.message_handler(func=lambda message: message.text == "📅 План на неделю")
def week_plan(message):
    generate_content(message, "План на 7 дней (RU/EN) с промптами для каждого дня.")

@bot.message_handler(func=lambda message: message.text == "💾 В память")
def save_memory(message):
    last = user_states.get(message.chat.id, {}).get('last_content')
    if last:
        lore = last.split("📝")[0].replace("📸 СОБЫТИЕ:", "").strip()
        supabase.table('leya_lore').insert({"event_description": lore}).execute()
        bot.reply_to(message, "✅ История обновлена.")

@app.route('/', methods=['GET'])
def index():
    return "Leya Prompt Factory Active"
