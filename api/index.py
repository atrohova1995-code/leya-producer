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

# Системный промпт (Логика Леи)
SYSTEM_PROMPT = """
Role: Ты — ИИ-Продюсер для Leya. 
Persona: 23 года, брюнетка, гетерохромия (зеленый/голубой), брекеты. Характер: INFP, меланхоличная, искренняя.
Format: 
1. Событие дня (Lore)
2. Промпт для поста
3. Visual Prompt (на английском)
"""

def get_main_keyboard():
    markup = types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    btns = ["🌅 Утро", "☀️ День", "🌆 Вечер", "🌃 Ночь", "✨ Свой сюжет", "🖼 Генерация фото", "💾 Сохранить в память"]
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
    bot.send_message(message.chat.id, "Студия контента Леи готова к работе.", reply_markup=get_main_keyboard())

# --- ОБНОВЛЕННАЯ ЛОГИКА ФОТО ---

@bot.message_handler(func=lambda message: message.text == "🖼 Генерация фото")
def image_gen_start(message):
    last_v = user_states.get(message.chat.id, {}).get('last_visual_prompt')
    markup = types.InlineKeyboardMarkup()
    if last_v:
        markup.add(types.InlineKeyboardButton("Последний промпт", callback_data="use_last_prompt"))
    markup.add(types.InlineKeyboardButton("Новый промпт", callback_data="write_new_prompt"))
    bot.send_message(message.chat.id, "Выбери текст для генерации:", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data in ["use_last_prompt", "write_new_prompt"])
def handle_image_choice(call):
    if call.data == "use_last_prompt":
        prompt = user_states.get(call.message.chat.id, {}).get('last_visual_prompt')
        ask_for_ref(call.message, prompt)
    else:
        msg = bot.send_message(call.message.chat.id, "Напиши промпт на английском:")
        bot.register_next_step_handler(msg, lambda m: ask_for_ref(m, m.text))

def ask_for_ref(message, prompt):
    user_states[message.chat.id] = {'current_img_prompt': prompt}
    bot.send_message(message.chat.id, "Пришли фото-референс или нажми /skip")

@bot.message_handler(content_types=['photo'])
def handle_photo_ref(message):
    if message.chat.id in user_states and 'current_img_prompt' in user_states[message.chat.id]:
        file_info = bot.get_file(message.photo[-1].file_id)
        file_url = f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{file_info.file_path}"
        process_gen(message, user_states[message.chat.id]['current_img_prompt'], file_url)

@bot.message_handler(commands=['skip'])
def skip_ref(message):
    if message.chat.id in user_states and 'current_img_prompt' in user_states[message.chat.id]:
        process_gen(message, user_states[message.chat.id]['current_img_prompt'])

def process_gen(message, prompt, ref_url=None):
    bot.send_message(message.chat.id, "🎨 Рисую...")
    try:
        # Используем extra_body, чтобы передать 'image' в Codex напрямую
        extra_data = {"image": ref_url} if ref_url else {}
        
        response = client_ai.images.generate(
            model="gpt-image-2",
            prompt=prompt,
            n=1,
            size="1024x1024",
            extra_body=extra_data # Вот это исправляет ошибку
        )
        bot.send_photo(message.chat.id, response.data[0].url, caption="Готово! ✨")
        del user_states[message.chat.id]['current_img_prompt']
    except Exception as e:
        bot.reply_to(message, f"❌ Ошибка: {e}")

# --- LORE & MEMORY ---

@bot.message_handler(func=lambda message: message.text in ["🌅 Утро", "☀️ День", "🌆 Вечер", "🌃 Ночь"])
def handle_time(message):
    generate_lore(message, message.text)

def generate_lore(message, time):
    bot.send_message(message.chat.id, "⏳ Генерирую сюжет...")
    try:
        res = supabase.table('leya_lore').select('*').order('created_at', desc=True).limit(3).execute()
        hist = "\n".join([f"- {i['event_description']}" for i in res.data[::-1]]) if res.data else "Начало."
        
        ai_res = client_ai.chat.completions.create(
            model="gpt-5.5",
            messages=[{"role": "system", "content": SYSTEM_PROMPT}, 
                      {"role": "user", "content": f"История:\n{hist}\n\nВремя: {time}. Создай день."}]
        )
        text = ai_res.choices[0].message.content
        v_prompt = text.split("3. Visual Prompt:")[1].strip() if "3. Visual Prompt:" in text else ""
        user_states[message.chat.id] = {'last_lore': text, 'last_visual_prompt': v_prompt}
        bot.send_message(message.chat.id, text, reply_markup=get_main_keyboard())
    except Exception as e:
        bot.reply_to(message, f"Ошибка: {e}")

@bot.message_handler(func=lambda message: message.text == "💾 Сохранить в память")
def save_mem(message):
    last = user_states.get(message.chat.id, {}).get('last_lore')
    if last:
        lore = last.split("2. Промпт")[0].replace("1. Событие дня (Lore):", "").strip()
        supabase.table('leya_lore').insert({"event_description": lore}).execute()
        bot.reply_to(message, "✅ Сохранено.")

@app.route('/', methods=['GET'])
def index():
    return "Leya's Studio is Online"
