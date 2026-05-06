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

user_states = {}

# Промпт для Instagram-продюсера
SYSTEM_PROMPT = """
Role: Ты — Продюсер AI-инфлюенсера Leya. 
Persona: 23 года, Харьков, брюнетка, гетерохромия (зеленый/голубой глаз), брекеты. 
Эстетика: Минимализм, "greige" (серо-бежевый), современный уют. 
Task: Создавать контент для Instagram. Тексты постов строго на Русском и Украинском языках.

Format:
📸 СОБЫТИЕ: [Краткое описание]
📝 ПОСТ (RU): [Текст поста]
📝 ПОСТ (UA): [Текст поста]
🖼 VISUAL PROMPT (EN): [Детальный промпт для фото: внешность Леи, одежда, локация, свет].
"""

def get_main_keyboard():
    markup = types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    btns = ["🎭 Новое событие", "📅 План на неделю", "🖼 Генерировать фото", "💾 В память"]
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
    bot.send_message(message.chat.id, "Привет! Просто напиши мне, что сейчас делает Лея, или нажми на кнопку.", reply_markup=get_main_keyboard())

# --- УНИВЕРСАЛЬНЫЙ ОБРАБОТЧИК (Текст напрямую) ---

@bot.message_handler(func=lambda message: message.text not in ["🎭 Новое событие", "📅 План на неделю", "🖼 Генерировать фото", "💾 В память"])
def handle_direct_wish(message):
    generate_content(message, f"Реализуй пожелание пользователя: {message.text}")

# --- КНОПКИ ---

@bot.message_handler(func=lambda message: message.text == "🎭 Новое событие")
def daily_auto(message):
    generate_content(message, "Придумай случайное эстетичное событие из жизни Леи.")

@bot.message_handler(func=lambda message: message.text == "📅 План на неделю")
def week_auto(message):
    bot.send_message(message.chat.id, "🗓 Готовлю сетку постов на неделю...")
    generate_content(message, "Создай план на 7 дней. Для каждого дня: Событие, Пост (RU/UA) и Visual Prompt.")

def generate_content(message, task):
    bot.send_message(message.chat.id, "⏳ Пишу сценарий и промпт...")
    try:
        res = supabase.table('leya_lore').select('*').order('created_at', desc=True).limit(3).execute()
        hist = "\n".join([f"- {i['event_description']}" for i in res.data[::-1]]) if res.data else "Начало."
        
        ai_res = client_ai.chat.completions.create(
            model="gpt-5.5",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT}, 
                {"role": "user", "content": f"Память:\n{hist}\n\nЗадача: {task}"}
            ]
        )
        answer = ai_res.choices[0].message.content
        
        v_prompt = answer.split("VISUAL PROMPT (EN):")[1].strip() if "VISUAL PROMPT (EN):" in answer else ""
        user_states[message.chat.id] = {'last_res': answer, 'last_v': v_prompt}
        
        bot.send_message(message.chat.id, answer, reply_markup=get_main_keyboard())
    except Exception as e:
        bot.reply_to(message, f"Ошибка: {e}")

# --- ФОТО И СОХРАНЕНИЕ ---

@bot.message_handler(func=lambda message: message.text == "🖼 Генерировать фото")
def make_photo(message):
    prompt = user_states.get(message.chat.id, {}).get('last_v')
    if not prompt:
        bot.send_message(message.chat.id, "Сначала напиши сюжет или нажми 'Новое событие'.")
        return
    bot.send_message(message.chat.id, "🎨 Генерирую фото... Пришли референс или нажми /skip")
    bot.register_next_step_handler(message, process_photo_final)

def process_photo_final(message):
    ref = None
    if message.content_type == 'photo':
        f_info = bot.get_file(message.photo[-1].file_id)
        ref = f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{f_info.file_path}"
    
    prompt = user_states[message.chat.id]['last_v']
    try:
        response = client_ai.images.generate(
            model="gpt-image-2",
            prompt=prompt,
            extra_body={"image": ref} if ref else {}
        )
        bot.send_photo(message.chat.id, response.data[0].url, caption="Фото для Instagram готово! ✨")
    except Exception as e:
        bot.reply_to(message, f"Ошибка фото: {e}")

@bot.message_handler(func=lambda message: message.text == "💾 В память")
def save_db(message):
    last = user_states.get(message.chat.id, {}).get('last_res')
    if last:
        lore = last.split("📝")[0].replace("📸 СОБЫТИЕ:", "").strip()
        supabase.table('leya_lore').insert({"event_description": lore}).execute()
        bot.reply_to(message, "✅ Лея запомнила этот момент.")

@app.route('/', methods=['GET'])
def index():
    return "Leya Direct Studio Active"
