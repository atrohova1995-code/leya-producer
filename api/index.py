import os
import telebot
from flask import Flask, request
from openai import OpenAI
from supabase import create_client, Client

# Инициализация Flask для работы на Vercel
app = Flask(__name__)

# Получение ключей из настроек Vercel (Environment Variables)
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_KEY')

# Настройка бота и клиентов
bot = telebot.TeleBot(TELEGRAM_TOKEN, threaded=False)

# Клиент ИИ с настройками под Codex (согласно screencapture-codex-sale-user-instructions-2026-05-06-14_47_26.jpg)
client_ai = OpenAI(
    api_key=OPENAI_API_KEY,
    base_url='https://codex.sale/v1' 
)

# Клиент базы данных для памяти Леи
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Системный промпт с личностью Леи
SYSTEM_PROMPT = """
Role: Ты — Креативный ИИ-Продюсер и Сценарист. Твоя задача — управлять жизнью digital-persona по имени Leya.

Character Context:
- 23 года, славянка, брюнетка, волосы средней длины.
- Внешность: гетерохромия (один глаз зеленый, другой голубой), эстетичные брекеты, ямочки на щеках.
- Эстетика: Soft cyber vibe, cozy realism, cinematic. Уютные худи, неоновый свет, дождь, музыка.
- Характер (INFP/INFJ): Эмоционально глубокая, мягкая, спокойная, наблюдательная. Скрывает легкую уязвимость и тревожность. Не "идеальная кукла", а живая девушка.

Instructions:
На основе предыдущих событий сгенерируй контент-план на текущий день строго в формате:
1. Событие дня (Lore): [жизненное событие]
2. Промпт для поста: [инструкция для написания поста от лица Леи]
3. Visual Prompt: [на английском: описание для генерации фото/видео, включая внешность Леи, одежду, окружение и свет].
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
    return "Leya's brain is active!"

@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot.reply_to(message, "Лея готова! Жми /next_day для генерации нового дня в ее истории.")

@bot.message_handler(commands=['next_day'])
def generate_day(message):
    bot.reply_to(message, "⏳ Обращаюсь к памяти Леи...")
    
    try:
        # 1. Загрузка последних 3 событий из памяти Supabase
        response = supabase.table('leya_lore').select('*').order('created_at', desc=True).limit(3).execute()
        history = response.data
        
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        
        if history:
            history_text = "\n".join([f"- {item['event_description']}" for item in history[::-1]])
            user_prompt = f"Последние события:\n{history_text}\n\nПридумай логичное продолжение на сегодня."
        else:
            user_prompt = "Это начало истории. Придумай первое событие, описывающее обычный, но атмосферный день Леи."
            
        messages.append({"role": "user", "content": user_prompt})
        
        # 2. Запрос к модели gpt-5.4-mini (доступной в Codex)
        ai_response = client_ai.chat.completions.create(
            model="gpt-5.5",
            messages=messages
        )
        
        result_text = ai_response.choices[0].message.content
        
        # 3. Отправка результата пользователю
        bot.send_message(message.chat.id, result_text)
        bot.send_message(message.chat.id, "💡 Чтобы Лея запомнила этот день, сохрани его описание в базу данных.")

    except Exception as e:
        bot.reply_to(message, f"❌ Ошибка: {e}")
