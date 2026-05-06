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
DEFAULT_TEXT_MODEL = os.getenv("DEFAULT_TEXT_MODEL", "gpt-5.5")

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
user_settings = {}

BTN_CREATE_POST = "📝 Создать пост + фото"
BTN_CREATE_SET = "📸 Создать Фото-Сет"
BTN_IMAGE_GENERATOR = "🖼 Генератор картинок"
BTN_REFERENCE_JSON = "🧩 JSON из референса"
BTN_SAVE_LORE = "💾 Сохранить лор"
BTN_SETTINGS = "⚙️ Настройки"
BTN_BACK = "⬅️ Назад"

TEXT_MODELS = {
    "GPT-5.5": "gpt-5.5",
    "GPT-5.4": "gpt-5.4",
    "GPT-5.4 Mini": "gpt-5.4-mini",
    "GPT-5.3 Codex": "gpt-5.3-codex",
}

MODEL_BUTTONS = {f"🤖 {label}" for label in TEXT_MODELS}

SYSTEM_PROMPT = """
Role: Ты - Арт-Директор и Продюсер AI-инфлюенсера Leya.
Persona: 23 года, Харьков. Брюнетка, гетерохромия, брекеты, ямочки на щеках.
Esthetics: Minimal, greige, cinematic lighting.
Task: Создавать профессиональные контент-планы и промпты для генерации.

Единый стандарт VISUAL PROMPT:
Каждый визуальный промпт должен быть не коротким описанием, а полноценной инструкцией для генерации изображения.
Структура промпта:
1. Если используется загруженный референс: "Загруженное изображение - строгий референс лица (identity lock), сохранить лицо, черты, форму глаз, губ, носа и пропорции 1:1 без изменений."
2. Формат фото: ультрареалистичное RAW фото, устройство/камера, фотореализм, без AI look.
3. Кадр и композиция: крупность плана, угол камеры, перспектива, расположение объекта в кадре.
4. Поза и действие: конкретно, без общих фраз.
5. Одежда: цвет, материал, посадка, складки, фактура.
6. Волосы, макияж, маникюр: если уместно, описывать детально и практически.
7. Фон и окружение: предметы, глубина, что в фокусе и вне фокуса.
8. Свет: источник, направление, мягкость, тени, объем.
9. Качество: фотореализм, RAW, высокая детализация кожи/материалов, естественная текстура, Pinterest aesthetic, живой кадр.
10. Negative prompt: без пластика, без AI look, без искажений лица/рук, без лишних пальцев, без размытого лица, без изменения идентичности при identity lock.

Визуальные промпты должны быть на русском, подробные, готовые к копированию в генератор.

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
        types.KeyboardButton(BTN_REFERENCE_JSON),
        types.KeyboardButton(BTN_SAVE_LORE),
        types.KeyboardButton(BTN_SETTINGS),
    )
    return markup


def get_settings_keyboard():
    markup = types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    markup.add(*(types.KeyboardButton(f"🤖 {label}") for label in TEXT_MODELS))
    markup.add(types.KeyboardButton(BTN_BACK))
    return markup


def get_state(chat_id):
    return user_states.setdefault(chat_id, {})


def get_settings(chat_id):
    return user_settings.setdefault(chat_id, {"text_model": DEFAULT_TEXT_MODEL})


def get_selected_text_model(chat_id):
    settings = get_settings(chat_id)
    model = settings.get("text_model", DEFAULT_TEXT_MODEL)
    if model not in TEXT_MODELS.values():
        model = DEFAULT_TEXT_MODEL
        settings["text_model"] = model
    return model


def get_model_label(model_id):
    for label, current_model_id in TEXT_MODELS.items():
        if current_model_id == model_id:
            return label
    return model_id


def normalize_image_prompt(prompt, has_reference=False):
    reference_rule = ""
    if has_reference:
        reference_rule = (
            "Загруженное изображение - строгий референс лица (identity lock), "
            "сохранить лицо, черты, форму глаз, губ, носа и пропорции 1:1 без изменений.\n"
        )

    return f"""
{reference_rule}{prompt.strip()}

Обязательный стандарт генерации:
Ультрареалистичное RAW фото, фотореализм, высокая детализация кожи и материалов, естественная текстура, живой кадр, Pinterest aesthetic.
Подробно соблюдать кадр, ракурс, композицию, позу, одежду, волосы, макияж, маникюр, фон, свет и атмосферу из промпта.
Без AI look, без пластика, без размытого лица, без искажений лица и рук, без лишних пальцев, без артефактов, без пересвета, без изменения идентичности при identity lock.
""".strip()


def get_telegram_file_url(file_id):
    file_info = bot.get_file(file_id)
    return f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{file_info.file_path}"


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


@bot.message_handler(func=lambda message: message.text == BTN_SETTINGS)
def show_settings(message):
    if not ensure_configured(message):
        return

    model_id = get_selected_text_model(message.chat.id)
    bot.send_message(
        message.chat.id,
        "Настройки\n\n"
        f"Текущая модель текста: {get_model_label(model_id)} ({model_id})\n"
        "Модель картинок: GPT Image 2 (gpt-image-2)",
        reply_markup=get_settings_keyboard(),
    )


@bot.message_handler(func=lambda message: message.text in MODEL_BUTTONS)
def change_text_model(message):
    label = message.text.replace("🤖 ", "", 1)
    model_id = TEXT_MODELS.get(label)
    if not model_id:
        bot.send_message(message.chat.id, "Не знаю такую модель.", reply_markup=get_settings_keyboard())
        return

    settings = get_settings(message.chat.id)
    settings["text_model"] = model_id
    bot.send_message(
        message.chat.id,
        f"Готово. Для текстовой генерации выбрана {label} ({model_id}).",
        reply_markup=get_main_keyboard(),
    )


@bot.message_handler(func=lambda message: message.text == BTN_BACK)
def back_to_main_menu(message):
    bot.send_message(message.chat.id, "Главное меню.", reply_markup=get_main_keyboard())


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
        f"⚙️ Бриф принят! Генерирую через {get_model_label(get_selected_text_model(message.chat.id))}. "
        "Это займет 15-20 секунд...",
        reply_markup=get_main_keyboard(),
    )

    task = f"""
Ситуация: {idea}
Настроение/эстетика: {mood}

Задача:
1. Напиши пост для Instagram: текст на русском, затем перевод на английский.
2. Сгенерируй {count} профессиональных VISUAL PROMPT(s) на русском для этой ситуации.
3. Каждый VISUAL PROMPT должен быть подробным и готовым к генерации: identity/character lock при необходимости, RAW photo style, кадр, поза, одежда, волосы, макияж, маникюр, фон, свет, качество и negative prompt.

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
            model=get_selected_text_model(message.chat.id),
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
        "📝 Вставь промпт для фото. Я автоматически добавлю стандарт генерации: "
        "RAW, фотореализм, кадр, свет, детализацию и negative prompt.",
        reply_markup=types.ReplyKeyboardRemove(),
    )
    bot.register_next_step_handler(msg, get_prompt_step)


@bot.message_handler(func=lambda message: message.text == BTN_REFERENCE_JSON)
def start_reference_json_chain(message):
    if not ensure_configured(message):
        return

    msg = bot.send_message(
        message.chat.id,
        "Пришли фото-референс. Я соберу JSON-промпт по стандартам генерации: "
        "identity lock, кадр, поза, одежда, свет, фон, камера, реализм и negative prompt.",
        reply_markup=types.ReplyKeyboardRemove(),
    )
    bot.register_next_step_handler(msg, generate_reference_json_prompt)


def generate_reference_json_prompt(message):
    if message.content_type != "photo":
        bot.send_message(
            message.chat.id,
            "Нужно отправить именно фото-референс. Попробуй еще раз.",
            reply_markup=get_main_keyboard(),
        )
        return

    ref_url = get_telegram_file_url(message.photo[-1].file_id)
    progress_msg = bot.send_message(message.chat.id, "🧩 Анализирую референс и собираю JSON...")

    instruction = """
Analyze the reference image and create a production-ready JSON prompt for image generation.

Important:
- Treat the uploaded image as the strict face and identity reference.
- Preserve the face, identity, facial features, eye shape, lips, nose, facial proportions, hair, makeup, manicure, and visible styling from the uploaded reference.
- Build a complete prompt according to image-generation standards: identity lock, photo format, shot type, camera, pose, clothing, hair, makeup, manicure, background, lighting, realism, details, and negative prompt.
- If a detail is not visible in the image, infer a tasteful generation-ready option that matches the reference style, but do not invent brand names.
- Return valid JSON only. Do not wrap it in markdown.
- The "ready_prompt" field must be a polished Russian prompt in the style of a professional image-generation prompt, similar to this structure: "Загруженное изображение — строгий референс лица (identity lock)..."

Use this schema:
{
  "prompt_type": "strict_reference_generation",
  "ready_prompt": "",
  "identity_lock": "",
  "photo_style": "",
  "camera": {
    "shot_type": "",
    "angle": "",
    "device_or_camera": "",
    "lens": "",
    "depth_of_field": ""
  },
  "pose": "",
  "clothing": "",
  "hair": "",
  "makeup": "",
  "manicure": "",
  "background": "",
  "lighting": "",
  "composition": "",
  "mood": "",
  "color_palette": [],
  "textures_and_materials": [],
  "props": [],
  "quality_tags": [],
  "negative_prompt": []
}
"""

    try:
        ai_res = client_ai.chat.completions.create(
            model=get_selected_text_model(message.chat.id),
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": instruction},
                        {"type": "image_url", "image_url": {"url": ref_url}},
                    ],
                }
            ],
        )
        json_prompt = ai_res.choices[0].message.content
        bot.delete_message(message.chat.id, progress_msg.message_id)
        bot.send_message(message.chat.id, json_prompt, reply_markup=get_main_keyboard())
    except Exception as error:
        bot.edit_message_text(f"❌ Не удалось собрать JSON-промпт: {error}", message.chat.id, progress_msg.message_id)
        bot.send_message(message.chat.id, "Попробуем другой референс?", reply_markup=get_main_keyboard())


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
        ref_url = get_telegram_file_url(message.photo[-1].file_id)

    prompt = normalize_image_prompt(prompt, has_reference=bool(ref_url))

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
