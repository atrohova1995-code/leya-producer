import os
import telebot
from flask import Flask, request
from openai import OpenAI
from supabase import create_client, Client

# Инициализация Flask
app = Flask(__name__)

# Берем ключи из переменных окружения (настроек Vercel)
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_KEY')

bot = telebot.TeleBot(TELEGRAM_TOKEN, threaded=False)
client_ai = OpenAI(api_key=OPENAI_API_KEY)
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

SYSTEM_PROMPT = """Тут твой промпт про Лею (гетерохромия, брекеты, INFP и т.д.)"""

@app.route('/', methods=['POST'])
def webhook():
    if request.headers.get('content-type') == 'application/json':
        json_string = request.get_data().decode('utf-8')
        update = telebot.types.Update.de_json(json_string)
        bot.process_new_updates([update])
        return ''
    else:
        return '403', 403

@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot.reply_to(message, "Лея готова! Жми /next_day для генерации.")

@bot.message_handler(commands=['next_day'])
def generate_day(message):
    try:
        # Логика получения памяти из Supabase и запрос к OpenAI (как в прошлом коде)
        # Для краткости я сократил, но в твоем файле должен быть полный код логики
        bot.reply_to(message, "⏳ Генерирую новый день для Леи...")
        # ... тут код генерации из предыдущего сообщения ...
        bot.send_message(message.chat.id, "День сгенерирован!")
    except Exception as e:
        bot.reply_to(message, f"Ошибка: {e}")

# Пустой обработчик для GET запроса (чтобы Vercel не ругался)
@app.route('/', methods=['GET'])
def index():
    return "Leya is alive!"
