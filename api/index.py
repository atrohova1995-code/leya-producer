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

# Хранилище состояний
user_states = {}

def get_main_keyboard():
    markup = types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    btn1 = types.KeyboardButton("🌅 Утро")
    btn2 = types.KeyboardButton("☀️ День")
    btn3 = types.KeyboardButton("🌆 Вечер")
    btn4 = types.KeyboardButton("🌃 Ночь")
    btn5 = types.KeyboardButton("✨ Свой сюжет")
    btn6 = types.KeyboardButton("🖼 Генерация фото")
    btn7 = types.KeyboardButton("💾 Сохранить в память")
    markup.add(btn1, btn2, btn3, btn4, btn5, btn6, btn7)
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
    bot.send_message(message.chat.id, "Панель управления Леей активирована.", reply_markup=get_main_keyboard())

# --- ЛОГИКА ГЕНЕРАЦИИ ИЗОБРАЖЕНИЙ ---

@bot.message_handler(func=lambda message: message.text == "🖼 Генерация фото")
def image_gen_start(message):
    last_visual_prompt = user_states.get(message.chat.id, {}).get('last_visual_prompt')
    
    markup = types.InlineKeyboardMarkup()
    if last_visual_prompt:
        markup.add(types.InlineKeyboardButton("Использовать последний промпт", callback_data="use_last_prompt"))
    markup.add(types.InlineKeyboardButton("Написать свой", callback_data="write_new_prompt"))
    
    bot.send_message(message.chat.id, "Давай создадим фото. Использовать промпт из последнего сценария или напишешь новый?", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data in ["use_last_prompt", "write_new_prompt"])
def handle_image_choice(call):
    if call.data == "use_last_prompt":
        prompt = user_states.get(call.message.chat.id, {}).get('last_visual_prompt')
        ask_for_reference(call.message, prompt)
    else:
        msg = bot.send_message(call.message.chat.id, "Пришли текстовое описание для фото (на английском):")
        bot.register_next_step_handler(msg, lambda m: ask_for_reference(m, m.text))

def ask_for_reference(message, prompt):
    user_states[message.chat.id] = user_states.get(message.chat.id, {})
    user_states[message.chat.id]['current_img_prompt'] = prompt
    bot.send_message(message.chat.id, "Почти готово! Теперь можешь прислать ФОТО как референс или просто нажми /skip, чтобы генерировать без него.")

@bot.message_handler(content_types=['photo'])
def handle_photo_ref(message):
    # Если мы ждем референс
    if message.chat.id in user_states and 'current_img_prompt' in user_states[message.chat.id]:
        # Получаем ссылку на фото
        file_info = bot.get_file(message.photo[-1].file_id)
        file_url = f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{file_info.file_path}"
        process_image_generation(message, user_states[message.chat.id]['current_img_prompt'], file_url)

@bot.message_handler(commands=['skip'])
def skip_reference(message):
    if message.chat.id in user_states and 'current_img_prompt' in user_states[message.chat.id]:
        process_image_generation(message, user_states[message.chat.id]['current_img_prompt'])

def process_image_generation(message, prompt, ref_url=None):
    bot.send_message(message.chat.id, "🎨 Нейросеть рисует образ... Это займет до 30 секунд.")
    try:
        # Используем модель gpt-image-2 согласно инструкции Codex
        image_params = {
            "model": "gpt-image-2",
            "prompt": prompt,
            "n": 1,
            "size": "1024x1024"
        }
        # Если есть референс, добавляем его (зависит от поддержки API прокси)
        if ref_url:
            image_params["image"] = ref_url 

        response = client_ai.images.generate(**image_params)
        image_url = response.data[0].url
        bot.send_photo(message.chat.id, image_url, caption="Готовый результат для Леи ✨")
        
        # Очищаем состояние
        del user_states[message.chat.id]['current_img_prompt']
    except Exception as e:
        bot.reply_to(message, f"❌ Ошибка визуализации: {e}")

# --- ОСТАЛЬНАЯ ЛОГИКА (Lore, Save) ---

@bot.message_handler(func=lambda message: message.text in ["🌅 Утро", "☀️ День", "🌆 Вечер", "🌃 Ночь"])
def handle_time(message):
    generate_lore(message, message.text)

def generate_lore(message, time_of_day):
    bot.send_message(message.chat.id, "⏳ Придумываю продолжение истории...")
    try:
        # Запрос истории из Supabase
        res = supabase.table('leya_lore').select('*').order('created_at', desc=True).limit(3).execute()
        history = "\n".join([f"- {i['event_description']}" for i in res.data[::-1]]) if res.data else "Начало."
        
        ai_res = client_ai.chat.completions.create(
            model="gpt-5.5",
            messages=[
                {"role": "system", "content": "Ты - продюсер Леи. Выдай: 1. Lore 2. Пост 3. Visual Prompt (EN)."},
                {"role": "user", "content": f"История:\n{history}\n\nВремя: {time_of_day}. Создай сюжет."}
            ]
        )
        answer = ai_res.choices[0].message.content
        
        # Сохраняем промпты в сессию
        v_prompt = answer.split("3. Visual Prompt:")[1].strip() if "3. Visual Prompt:" in answer else ""
        user_states[message.chat.id] = {'last_lore': answer, 'last_visual_prompt': v_prompt}
        
        bot.send_message(message.chat.id, answer, reply_markup=get_main_keyboard())
    except Exception as e:
        bot.reply_to(message, f"Ошибка: {e}")

@app.route('/', methods=['GET'])
def index():
    return "Leya's brain and eyes are active!"
