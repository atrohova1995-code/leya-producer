import os
import time

import telebot
from flask import Flask, request
from openai import OpenAI
from supabase import Client, create_client
from telebot import types


app = Flask(__name__)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

REQUIRED_ENV_VARS = {
    "TELEGRAM_TOKEN": TELEGRAM_TOKEN,
    "OPENAI_API_KEY": OPENAI_API_KEY,
    "SUPABASE_URL": SUPABASE_URL,
    "SUPABASE_KEY": SUPABASE_KEY,
}

bot = telebot.TeleBot(TELEGRAM_TOKEN or "missing-token", threaded=False)
client_ai = OpenAI(api_key=OPENAI_API_KEY or "missing-key", base_url="https://codex.sale/v1")
supabase: Client | None = None
if SUPABASE_URL and SUPABASE_KEY:
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

user_states = {}

BTN_CREATE_POST = "📝 Создать пост + фото"
BTN_CREATE_SET = "📸 Создать Фото-Сет"
BTN_IMAGE_GENERATOR = "🖼 Генератор картинок"
BTN_SAVE_LORE = "💾 Сохранить лор"

SYSTEM_PROMPT = """
Role: Ты - Арт-Директор и Продюсер AI-инфлюенсера Leya.
Persona: 23 года, Харьков. Брюнетка, гетерохромия, брекеты, ямочки на щеках.
Esthetics: Minimal, greige, cinematic lighting.
Task: Создавать профессиональные контент-планы и промпты для генерации.

Правила выдачи сета фотографий:
Если просят несколько фото для одной ситуации, каждый промпт должен отличаться:
- Photo 1: Wide angle (общий план локации, Лея в полный рост).
- Photo 2: Medium shot (Лея по пояс, занята делом).
- Photo 3: Close-up portrait (крупный план лица, эмоция, фокус на глаза/брекеты).
- Photo 4: Detail/Macro (деталь: руки с кофе, фактура одежды).
- Photo 5: Alternative angle (со спины или через отражение).
"""


def get_main_keyboard():
    markup = types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    markup.add(
        types.KeyboardButton(BTN_CREATE_POST),
        types.KeyboardButton(BTN_CREATE_SET),
        types.KeyboardButton(BTN_IMAGE_GENERATOR),
        types.KeyboardButton(BTN_SAVE_LORE),
    )
    return markup


def get_state(chat_id):
    return user_states.setdefault(chat_id, {})


def get_missing_env_vars():
    return [name for name, value in REQUIRED_ENV_VARS.items() if not value]


def ensure_configured(message=None):
    missing_env_vars = get_missing_env_vars()
    if not missing_env_vars:
        return True

    error_text = "Не настроены переменные окружения: " + ", ".join(missing_env_vars)
    if message:
        bot.reply_to(message, f"❌ {error_text}")
    return False


@app.route("/", methods=["POST"])
def webhook():
    if get_missing_env_vars():
        return "Missing environment variables", 500

    if not request.is_json:
        return "Expected JSON", 403

    update = telebot.types.Update.de_json(request.get_data().decode("utf-8"))
    bot.process_new_updates([update])
    return ""


@app.route("/", methods=["GET"])
def index():
    missing_env_vars = get_missing_env_vars()
    if missing_env_vars:
        return f"Content Factory needs setup: {', '.join(missing_env_vars)}"
    return "Content Factory Active"


@bot.message_handler(commands=["start"])
def start(message):
    if not ensure_configured(message):
        return

    bot.send_message(
        message.chat.id,
        "Привет, Саша! Я твой Контент-Завод для Леи. Что будем делать сегодня?",
        reply_markup=get_main_keyboard(),
    )


@bot.message_handler(func=lambda message: message.text in [BTN_CREATE_POST, BTN_CREATE_SET])
def start_briefing(message):
    if not ensure_configured(message):
        return

    user_states[message.chat.id] = {
        "is_set": message.text == BTN_CREATE_SET,
        "step": 1,
    }

    bot.send_message(
        message.chat.id,
        "Отлично. Давай настроим атмосферу.\n\n"
        "📍 Шаг 1/3: Опиши локацию или ситуацию "
        "(например: 'Пьет кофе на балконе, утренний свет').",
        reply_markup=types.ReplyKeyboardRemove(),
    )
    bot.register_next_step_handler(message, process_brief_step_1)


def process_brief_step_1(message):
    state = get_state(message.chat.id)
    state["idea"] = message.text or ""

    bot.send_message(
        message.chat.id,
        "🎨 Шаг 2/3: Какое настроение и эстетика? "
        "(например: 'уютная меланхолия', 'бодрое утро', 'fashion minimal').",
    )
    bot.register_next_step_handler(message, process_brief_step_2)


def process_brief_step_2(message):
    state = get_state(message.chat.id)
    state["mood"] = message.text or ""

    if state.get("is_set"):
        markup = types.ReplyKeyboardMarkup(row_width=3, resize_keyboard=True, one_time_keyboard=True)
        markup.add("3 фото", "5 фото", "7 фото")
        bot.send_message(
            message.chat.id,
            "🔢 Шаг 3/3: Сколько промптов (ракурсов) делаем для этого сета?",
            reply_markup=markup,
        )
        bot.register_next_step_handler(message, finish_briefing)
        return

    state["count"] = "1 фото"
    finish_briefing(message)


def finish_briefing(message):
    state = get_state(message.chat.id)
    count = message.text if state.get("is_set") else "1 фото"
    idea = state.get("idea", "")
    mood = state.get("mood", "")

    bot.send_message(
        message.chat.id,
        "⚙️ Бриф принят! Иду генерировать контент. Это займет 15-20 секунд...",
        reply_markup=get_main_keyboard(),
    )

    task = f"""
Ситуация: {idea}
Настроение/эстетика: {mood}

Задача:
1. Напиши пост для Instagram: текст на русском, затем перевод на английский.
2. Сгенерируй {count} профессиональных VISUAL PROMPT(s) на английском для этой ситуации.

Если промптов больше одного, обязательно меняй ракурсы, крупность плана
(от общего к макро) и позы Леи.
"""

    try:
        res = supabase.table("leya_lore").select("*").order("created_at", desc=True).limit(3).execute()
        history = "\n".join(
            f"- {item.get('event_description', '')}" for item in reversed(res.data or [])
        )
        if not history:
            history = "Начало."

        ai_res = client_ai.chat.completions.create(
            model="gpt-5.5",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": f"Память:\n{history}\n\n{task}"},
            ],
        )

        final_text = ai_res.choices[0].message.content
        state["last_content"] = final_text
        bot.send_message(message.chat.id, final_text)
    except Exception as error:
        bot.reply_to(message, f"❌ Ошибка генерации: {error}")


@bot.message_handler(func=lambda message: message.text == BTN_IMAGE_GENERATOR)
def start_photo_chain(message):
    if not ensure_configured(message):
        return

    msg = bot.send_message(
        message.chat.id,
        "📝 Вставь промпт для фото на английском "
        "(скопируй из сгенерированных выше):",
        reply_markup=types.ReplyKeyboardRemove(),
    )
    bot.register_next_step_handler(msg, get_prompt_step)


def get_prompt_step(message):
    if not message.text:
        bot.send_message(message.chat.id, "Отмена.", reply_markup=get_main_keyboard())
        return

    user_states[message.chat.id] = {"temp_prompt": message.text}
    msg = bot.send_message(message.chat.id, "📸 Пришли фото-референс или напиши /skip")
    bot.register_next_step_handler(msg, get_photo_step)


def get_photo_step(message):
    state = get_state(message.chat.id)
    prompt = state.get("temp_prompt")
    if not prompt:
        bot.send_message(
            message.chat.id,
            "Промпт не найден. Давай начнем генерацию заново.",
            reply_markup=get_main_keyboard(),
        )
        return

    ref_url = None
    if message.content_type == "photo":
        file_info = bot.get_file(message.photo[-1].file_id)
        ref_url = f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{file_info.file_path}"

    progress_msg = bot.send_message(message.chat.id, "🎨 Обработка: [░░░░░░░░░░] 0%")

    try:
        time.sleep(1)
        bot.edit_message_text(
            "🎨 Рендер: [▓▓▓▓░░░░░░] 40%",
            message.chat.id,
            progress_msg.message_id,
        )

        response = client_ai.images.generate(
            model="gpt-image-2",
            prompt=prompt,
            extra_body={"image": ref_url} if ref_url else {},
        )

        bot.edit_message_text(
            "🎨 Финализация: [▓▓▓▓▓▓▓▓▓░] 90%",
            message.chat.id,
            progress_msg.message_id,
        )
        image_url = response.data[0].url
        bot.delete_message(message.chat.id, progress_msg.message_id)
        bot.send_photo(message.chat.id, image_url, caption="Твой контент ✨", reply_markup=get_main_keyboard())
    except Exception as error:
        bot.edit_message_text(f"❌ Сбой: {error}", message.chat.id, progress_msg.message_id)
        bot.send_message(message.chat.id, "Повторим?", reply_markup=get_main_keyboard())


@bot.message_handler(func=lambda message: message.text == BTN_SAVE_LORE)
def save_db(message):
    if not ensure_configured(message):
        return

    state = get_state(message.chat.id)
    last_content = state.get("last_content")

    if not last_content:
        bot.reply_to(message, "Пока нечего сохранять. Сначала сгенерируй пост или фото-сет.")
        return

    try:
        supabase.table("leya_lore").insert({"event_description": last_content}).execute()
        bot.reply_to(message, "✅ Событие добавлено в базу. Завтра Лея это вспомнит.")
    except Exception as error:
        bot.reply_to(message, f"❌ Не удалось сохранить лор: {error}")
