import os
import telebot
from flask import Flask, request
from openai import OpenAI
from supabase import create_client, Client

# Инициализация Flask
app = Flask(__name__)

# Берем ключи из настроек Vercel
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_KEY')

bot = telebot.TeleBot(TELEGRAM_TOKEN, threaded=False)

# Подключение к ИИ (настроено под Codex)
client_ai = OpenAI(
    api_key=OPENAI_API_KEY,
    base_url='https://api.codex.sale/v1' 
)

# Подключение к базе данных
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

SYSTEM_PROMPT = """
Role: Ты — Креативный ИИ-Продюсер и Сценарист. Твоя задача — управлять жизнью digital-persona по имени Leya.

Character Context:
- 23 года, славянка, брюнетка, волосы средней длины.
- Внешность: гетерохромия (один глаз зеленый, другой голубой), эстетичные брекеты, ямочки на щеках.
- Эстетика: Soft cyber vibe, cozy realism. Уютные худи, неоновый свет, дождь, музыка.
- Характер (INFP/INFJ): Эмоционально глубокая, мягкая, спокойная, наблюдательная. Скрывает легкую уязвимость и тревожность. Не "идеальная кукла", а живая девушка.

Instructions:
На основе предыдущих событий сгенерируй контент-план на текущий день строго в формате:
1. Событие дня (Lore): [жизненное событие]
2. Промпт для поста: [инструкция для написания поста от лица Леи]
3. Visual Prompt: [строго на английском: подробное описание для генерации фото/видео с указанием внешности Леи, одежды, окружения и освещения].
"""

@app.route('/', methods=['POST'])
def webhook():
    if request.headers.get('content-type') == 'application/json':
        json_string = request.get_data().decode('utf-8')
        update = telebot.types.Update.de_json(json_string)
        bot.process_new_updates([update])
        return ''
    else:
        return '403', 403

@app.route('/', methods=['GET'])
def index():
    return "Leya is alive!"

@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot.reply_to(message, "Лея готова! Жми /next_day для генерации.")

@bot.message_handler(commands=['next_day'])
def generate_day(message):
    bot.reply_to(message, "⏳ Читаю память Леи и придумываю новый день (это может занять секунд 10-15)...")
    
    try:
        # 1. Читаем память из Supabase
        response = supabase.table('leya_lore').select('*').order('created_at', desc=True).limit(3).execute()
        history = response.data
        
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        
        if history:
            history_text = "\n".join([f"- {item['event_description']}" for item in history[::-1]])
            user_prompt = f"Вот что происходило с Леей в последние дни:\n{history_text}\n\nСгенерируй логичное событие на сегодня."
        else:
            user_prompt = "Это первый день истории. Сгенерируй стартовое событие."
            
        messages.append({"role": "user", "content": user_prompt})
        
        # 2. Запрашиваем нейросеть
        ai_response = client_ai.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages
        )
        
        result_text = ai_response.choices[0].message.content
        
        # 3. Отправляем результат в чат
        bot.send_message(message.chat.id, result_text)
        
    except Exception as e:
        bot.reply_to(message, f"❌ Ошибка генерации: {e}")
