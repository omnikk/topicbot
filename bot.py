import logging
import asyncio
import json
import os
import datetime
from collections import defaultdict, Counter
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler
from telegram.error import TimedOut, RetryAfter, NetworkError

# Настраиваем логирование
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Файлы для хранения настроек и статистики
DATA_DIR = r"C:\Users\VybornovOA1\Desktop\py\bot_topic"  # Абсолютный путь к директории
CONFIG_FILE = os.path.join(DATA_DIR, "bot_config.json")
STATS_FILE = os.path.join(DATA_DIR, "user_stats.json")

# Глобальные переменные для хранения конфигурации
BOT_TOKEN = ""
MAIN_NAME = "Главная комната"
THEMES = ["Доска", "Класс", "Новости", "Команда 1", "Команда2"]
HELLO_MESSAGES = [
    "Это тема 1",
    "Это тема 2",
    "Это тема 3",
    "Это тема 4",
    "Это тема 5"
]
TEMPLATE_MESSAGES = [
    "👋 Добро пожаловать в новую группу!",
    "📌 Правила группы:\n1. Уважайте друг друга\n2. Не спамьте\n3. Придерживайтесь темы группы",
    "💡 Чтобы начать, представьтесь в чате!"
]

# Словарь для хранения статистики пользователей
USER_STATS = defaultdict(lambda: defaultdict(Counter))

def ensure_data_directory():
    """Создает директорию для хранения данных, если она еще не существует."""
    if not os.path.exists(DATA_DIR):
        os.makedirs(DATA_DIR)
        logger.info(f"Создана директория для данных: {DATA_DIR}")

# Загрузка конфигурации
def load_config():
    ensure_data_directory()
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {
        "bot_token": "",
        "main_name": MAIN_NAME,
        "themes": THEMES,
        "hello_messages": HELLO_MESSAGES,
        "template_messages": TEMPLATE_MESSAGES
    }

# Сохранение конфигурации
def save_config(config):
    ensure_data_directory()
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=4)

# Загрузка статистики пользователей
def load_user_stats():
    global USER_STATS
    ensure_data_directory()
    if os.path.exists(STATS_FILE):
        try:
            with open(STATS_FILE, "r", encoding="utf-8") as f:
                # Преобразуем загруженные данные в формат defaultdict(lambda: defaultdict(Counter))
                data = json.load(f)
                for chat_id, chat_data in data.items():
                    for user_id, user_data in chat_data.items():
                        for content_type, count in user_data.items():
                            USER_STATS[chat_id][user_id][content_type] = count
            logger.info(f"Статистика пользователей загружена из {STATS_FILE}")
        except Exception as e:
            logger.error(f"Ошибка при загрузке статистики: {e}")
            USER_STATS = defaultdict(lambda: defaultdict(Counter))
    else:
        logger.info(f"Файл статистики {STATS_FILE} не найден, создан новый словарь статистики")
        USER_STATS = defaultdict(lambda: defaultdict(Counter))

# Сохранение статистики пользователей
def save_user_stats():
    try:
        ensure_data_directory()
        # Преобразуем defaultdict в обычный dict для сохранения
        data = {}
        for chat_id, chat_data in USER_STATS.items():
            data[chat_id] = {}
            for user_id, user_data in chat_data.items():
                data[chat_id][user_id] = dict(user_data)
        
        with open(STATS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
        logger.info(f"Статистика пользователей сохранена в {STATS_FILE}")
    except Exception as e:
        logger.error(f"Ошибка при сохранении статистики: {e}")

# Инициализация конфигурации
def init_config():
    global BOT_TOKEN, MAIN_NAME, THEMES, HELLO_MESSAGES, TEMPLATE_MESSAGES
    
    config = load_config()
    BOT_TOKEN = config.get("bot_token", "")
    MAIN_NAME = config.get("main_name", MAIN_NAME)
    THEMES = config.get("themes", THEMES)
    HELLO_MESSAGES = config.get("hello_messages", HELLO_MESSAGES)
    TEMPLATE_MESSAGES = config.get("template_messages", TEMPLATE_MESSAGES)
    
    # Загружаем статистику пользователей
    load_user_stats()
    
    return config

# Функция для безопасного вызова API с повторными попытками при таймаутах
async def safe_api_call(func, max_retries=3, delay=2, *args, **kwargs):
    """Безопасный вызов API с повторными попытками при таймаутах."""
    retries = 0
    while retries < max_retries:
        try:
            return await func(*args, **kwargs)
        except (TimedOut, NetworkError) as e:
            retries += 1
            if retries >= max_retries:
                raise
            logger.warning(f"Таймаут при выполнении запроса. Повторная попытка {retries}/{max_retries} через {delay} сек...")
            await asyncio.sleep(delay)
        except RetryAfter as e:
            retry_after = e.retry_after
            logger.warning(f"Превышен лимит запросов. Ожидание {retry_after} сек...")
            await asyncio.sleep(retry_after)
            retries += 1

# Обновление статистики пользователя
def update_user_stats(chat_id, user_id, content_type):
    """Обновляет статистику пользователя по типу контента."""
    chat_id_str = str(chat_id)
    user_id_str = str(user_id)
    USER_STATS[chat_id_str][user_id_str][content_type] += 1
    
    # Сохраняем статистику каждое обновлений (можно настроить)
    total_updates = sum(USER_STATS[chat_id_str][user_id_str].values())
    if total_updates % 1 == 0:
        save_user_stats()

# Функции для бота форумов
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Отправляет приветственное сообщение при команде /start."""
    await update.message.reply_text(
        "Привет! Я бот для Telegram форумов.\n"
        "• Создаю темы обсуждения в форумах\n"
        "• Отслеживаю активность пользователей\n\n"
        "Используйте /help для получения списка команд."
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Отправляет справочное сообщение при команде /help."""
    await update.message.reply_text(
        "📋 Команды бота:\n\n"
        "/start - Начать работу с ботом\n"
        "/help - Показать эту справку\n"
        "/create - Создать темы обсуждения по шаблону\n"
        "/settings - Настроить параметры бота\n"
        "/status - Показать текущий статус и настройки\n"
        "/stats - Показать статистику активности пользователей"
    )

async def settings_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Показывает и редактирует настройки бота с помощью интерактивного меню."""
    if not context.args:
        # Показываем интерактивное меню настроек
        keyboard = [
            [InlineKeyboardButton("Изменить токен бота", callback_data="settings_token")],
            [InlineKeyboardButton("Изменить название главной темы", callback_data="settings_main_name")],
            [InlineKeyboardButton("Управление темами", callback_data="settings_themes")],
            [InlineKeyboardButton("Управление приветственными сообщениями", callback_data="settings_hello")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        message = (
            "⚙️ Настройки бота\n\n"
            f"• Токен бота: {'настроен' if BOT_TOKEN else 'не настроен'}\n"
            f"• Название главной темы: {MAIN_NAME}\n"
            f"• Количество тем: {len(THEMES)}\n"
            f"• Шаблонных сообщений: {len(TEMPLATE_MESSAGES)}\n\n"
            "Выберите параметр для настройки или используйте команду:\n"
            "/settings set [параметр] [значение]\n\n"
            "Примеры:\n"
            "/settings set bot_token YOUR_TOKEN_HERE\n"
            "/settings set main_name Название главной темы"
        )
        
        await update.message.reply_text(message, reply_markup=reply_markup)
    elif len(context.args) >= 3 and context.args[0] == "set":
        param = context.args[1]
        value = " ".join(context.args[2:])
        
        await update_setting(update, param, value)
    else:
        await update.message.reply_text("⚠️ Некорректный формат команды. Используйте:\n/settings set [параметр] [значение]\nили просто /settings для интерактивного меню")

async def update_setting(update, param, value):
    """Обновляет указанную настройку."""
    global BOT_TOKEN, MAIN_NAME, THEMES, HELLO_MESSAGES
    
    config = load_config()
    
    # Обновление параметра
    if param == "bot_token":
        BOT_TOKEN = value
        config["bot_token"] = value
        await update.message.reply_text(f"✅ Токен бота обновлен\n⚠️ Для применения изменений требуется перезапуск бота")
    elif param == "main_name":
        MAIN_NAME = value
        config["main_name"] = value
        await update.message.reply_text(f"✅ Название главной темы изменено на: {MAIN_NAME}")
    elif param.startswith("theme_") and param[6:].isdigit():
        index = int(param[6:]) - 1
        if 0 <= index < len(THEMES):
            THEMES[index] = value
            config["themes"] = THEMES
            await update.message.reply_text(f"✅ Тема #{index+1} изменена на: {value}")
        else:
            await update.message.reply_text(f"⚠️ Неверный индекс темы. Доступные индексы: 1-{len(THEMES)}")
    elif param.startswith("hello_") and param[6:].isdigit():
        index = int(param[6:]) - 1
        if 0 <= index < len(HELLO_MESSAGES):
            HELLO_MESSAGES[index] = value
            config["hello_messages"] = HELLO_MESSAGES
            await update.message.reply_text(f"✅ Приветственное сообщение #{index+1} изменено")
        else:
            await update.message.reply_text(f"⚠️ Неверный индекс сообщения. Доступные индексы: 1-{len(HELLO_MESSAGES)}")
    else:
        await update.message.reply_text(f"⚠️ Неизвестный параметр: {param}")
        return
    
    # Сохраняем изменения
    save_config(config)

async def settings_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обрабатывает колбэки от интерактивного меню настроек."""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    
    if data == "settings_token":
        await query.message.reply_text(
            "Введите новый токен бота, используя команду:\n"
            "/settings set bot_token YOUR_TOKEN_HERE"
        )
    elif data == "settings_main_name":
        await query.message.reply_text(
            "Введите новое название главной темы, используя команду:\n"
            "/settings set main_name Новое название"
        )
    elif data == "settings_themes":
        themes_text = "📋 Текущие темы:\n\n"
        for i, theme in enumerate(THEMES, 1):
            themes_text += f"{i}. {theme}\n"
        
        themes_text += "\nДля изменения темы используйте команду:\n/settings set theme_N Новое название\n\nГде N - номер темы (1, 2, ...)"
        await query.message.reply_text(themes_text)
    elif data == "settings_hello":
        hello_text = "📋 Текущие приветственные сообщения:\n\n"
        for i, msg in enumerate(HELLO_MESSAGES, 1):
            hello_text += f"{i}. {msg}\n"
        
        hello_text += "\nДля изменения сообщения используйте команду:\n/settings set hello_N Новый текст\n\nГде N - номер сообщения (1, 2, ...)"
        await query.message.reply_text(hello_text)
    else:
        await query.message.reply_text("⚠️ Неизвестная команда")

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Показывает текущий статус бота."""
    message = (
        "📊 Статус бота:\n\n"
        f"• Бот Telegram: активен\n"
        f"• Дата и время: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"• Название главной темы: {MAIN_NAME}\n"
        f"• Количество тем: {len(THEMES)}\n"
        f"• Отслеживание активности: включено\n"
        f"• Директория данных: {DATA_DIR}\n"
    )
    
    await update.message.reply_text(message)

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Показывает статистику активности пользователей."""
    chat_id = str(update.effective_chat.id)
    
    if chat_id not in USER_STATS or not USER_STATS[chat_id]:
        await update.message.reply_text("📊 Статистика пока отсутствует для этого чата.")
        return
    
    message = "📊 Статистика активности пользователей:\n\n"
    
    # Получаем список пользователей с их статистикой
    user_stats_list = []
    for user_id, stats in USER_STATS[chat_id].items():
        try:
            # Пытаемся получить информацию о пользователе
            chat_member = await context.bot.get_chat_member(update.effective_chat.id, int(user_id))
            user_name = chat_member.user.full_name
        except Exception:
            # Если не удалось, используем ID
            user_name = f"Пользователь {user_id}"
        
        total_messages = sum(stats.values())
        user_stats_list.append((user_name, total_messages, stats))
    
    # Сортируем по общему количеству сообщений
    user_stats_list.sort(key=lambda x: x[1], reverse=True)
    
    # Формируем сообщение
    for i, (user_name, total, stats) in enumerate(user_stats_list[:10], 1):  # Показываем только топ-10
        message += f"{i}. {user_name}: {total} сообщений\n"
        message += f"   📝 Текст: {stats.get('text', 0)}, 🖼 Фото: {stats.get('photo', 0)}, "
        message += f"🎞 Видео: {stats.get('video', 0)}, 🎭 Стикеры: {stats.get('sticker', 0)}, "
        message += f"📊 GIF: {stats.get('animation', 0)}\n"
    
    if len(user_stats_list) > 10:
        message += f"\n...и еще {len(user_stats_list) - 10} пользователей"
    
    await update.message.reply_text(message)

async def create_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Создает темы обсуждения по шаблону."""
    # Проверяем, что команда отправлена в группе
    if update.effective_chat.type not in ['group', 'supergroup']:
        await update.message.reply_text("⚠️ Эта команда работает только в группах.")
        return
        
    status_message = await update.message.reply_text("Создаю темы обсуждения...")
    
    try:
        chat = await safe_api_call(context.bot.get_chat, 3, 2, update.effective_chat.id)
        
        # Проверяем, является ли группа форумом
        if not chat.is_forum:
            await safe_api_call(
                context.bot.edit_message_text,
                3, 2,
                chat_id=update.effective_chat.id,
                message_id=status_message.message_id,
                text="⚠️ Эта группа не является форумом. Включите темы обсуждения в настройках группы."
            )
            return
            
        # Пытаемся переименовать General (ID=1)
        try:
            await safe_api_call(
                context.bot.edit_forum_topic,
                3, 2,
                chat_id=update.effective_chat.id,
                message_thread_id=1,
                name=MAIN_NAME
            )
            await safe_api_call(
                context.bot.send_message,
                3, 2,
                chat_id=update.effective_chat.id,
                text=f"✅ Тема 'General' переименована в '{MAIN_NAME}'"
            )
        except Exception as e:
            logger.error(f"Ошибка при переименовании General: {e}")
            await safe_api_call(
                context.bot.send_message,
                3, 2,
                chat_id=update.effective_chat.id,
                text=f"⚠️ Не удалось переименовать тему 'General'. Возможно, она не существует или у бота недостаточно прав."
            )
        
        # Обновляем статус
        await safe_api_call(
            context.bot.edit_message_text,
            3, 2,
            chat_id=update.effective_chat.id,
            message_id=status_message.message_id,
            text="Создаю темы обсуждения... (0/{})".format(len(THEMES))
        )
        
        # Создаем новые темы
        successful_topics = 0
        for i, theme_name in enumerate(THEMES, 1):
            try:
                # Создаем тему с защищенным вызовом API
                new_topic = await safe_api_call(
                    context.bot.create_forum_topic,
                    3, 3,
                    chat_id=update.effective_chat.id,
                    name=theme_name
                )
                
                # Выбираем сообщение в зависимости от индекса темы
                hello_message = HELLO_MESSAGES[i-1] if i <= len(HELLO_MESSAGES) else f"Это тема {i}"
                
                # Получаем ID темы из результата создания
                topic_id = new_topic.message_thread_id
                
                # Отправляем сообщение в тему
                await asyncio.sleep(1)
                sent_message = await safe_api_call(
                    context.bot.send_message,
                    3, 2,
                    chat_id=update.effective_chat.id,
                    message_thread_id=topic_id,
                    text=hello_message
                )
                
                # Закрепляем сообщение
                await asyncio.sleep(1)
                await safe_api_call(
                    context.bot.pin_chat_message,
                    3, 2,
                    chat_id=update.effective_chat.id,
                    message_id=sent_message.message_id,
                    disable_notification=True
                )
                
                successful_topics += 1
                
                # Обновляем статус
                await safe_api_call(
                    context.bot.edit_message_text,
                    3, 2,
                    chat_id=update.effective_chat.id,
                    message_id=status_message.message_id,
                    text=f"Создаю темы обсуждения... ({successful_topics}/{len(THEMES)})"
                )
                
                # Задержка между созданием тем
                await asyncio.sleep(3)
                
            except Exception as e:
                logger.error(f"Ошибка при создании темы {theme_name}: {e}")
                await safe_api_call(
                    context.bot.send_message,
                    3, 2,
                    chat_id=update.effective_chat.id,
                    text=f"⚠️ Ошибка при создании темы {theme_name}: {e}"
                )
                await asyncio.sleep(5)  # Пауза после ошибки
        
        # Финальное сообщение
        await safe_api_call(
            context.bot.edit_message_text,
            3, 2,
            chat_id=update.effective_chat.id,
            message_id=status_message.message_id,
            text=f"✅ Создание тем завершено! Успешно создано: {successful_topics}/{len(THEMES)}"
        )
    except Exception as e:
        logger.error(f"Ошибка при создании тем обсуждения: {e}")
        await safe_api_call(
            context.bot.edit_message_text,
            3, 2,
            chat_id=update.effective_chat.id,
            message_id=status_message.message_id,
            text=f"⚠️ Произошла ошибка: {e}"
        )

async def handle_new_chat_members(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Реагирует на добавление бота в новую группу."""
    # Проверяем, есть ли бот среди новых участников
    new_members = update.message.new_chat_members
    bot_user = await context.bot.get_me()
    
    if not any(member.id == bot_user.id for member in new_members):
        return
        
    # Бот был добавлен в группу
    logger.info(f"Бот добавлен в группу: {update.effective_chat.title}")
    
    # Отправляем шаблонные сообщения с задержками
    for i, message in enumerate(TEMPLATE_MESSAGES):
        try:
            await safe_api_call(
                context.bot.send_message,
                3, 2,
                chat_id=update.effective_chat.id,
                text=message
            )
            # Добавляем задержку между сообщениями
            if i < len(TEMPLATE_MESSAGES) - 1:
                await asyncio.sleep(1)
        except Exception as e:
            logger.error(f"Ошибка при отправке приветственного сообщения: {e}")
        
    # Проверяем, является ли группа форумом и предлагаем создать темы
    try:
        await asyncio.sleep(1)  # Задержка перед следующим запросом
        chat = await safe_api_call(context.bot.get_chat, 3, 2, update.effective_chat.id)
        
        if chat.is_forum:
            await safe_api_call(
                context.bot.send_message,
                3, 2,
                chat_id=update.effective_chat.id,
                text="Это группа с темами обсуждения. Используйте команду /create для создания тем по шаблону."
            )
        else:
            await safe_api_call(
                context.bot.send_message,
                3, 2,
                chat_id=update.effective_chat.id,
                text="⚠️ Чтобы использовать темы обсуждения, эта группа должна быть супергруппой с включенными темами в настройках."
            )
    except Exception as e:
        logger.error(f"Ошибка при проверке типа группы: {e}")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обрабатывает все сообщения и обновляет статистику."""
    if not update.effective_user or update.effective_user.is_bot:
        return  # Пропускаем сообщения от ботов
    
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    
    # Определяем тип контента
    if update.message.text:
        update_user_stats(chat_id, user_id, "text")
    
    if update.message.photo:
        update_user_stats(chat_id, user_id, "photo")
    
    if update.message.sticker:
        update_user_stats(chat_id, user_id, "sticker")
    
    if update.message.video:
        update_user_stats(chat_id, user_id, "video")
    
    if update.message.animation:  # GIFs
        update_user_stats(chat_id, user_id, "animation")
    
    if update.message.document:
        update_user_stats(chat_id, user_id, "document")
    
    if update.message.voice:
        update_user_stats(chat_id, user_id, "voice")
    
    if update.message.audio:
        update_user_stats(chat_id, user_id, "audio")
    
    # Можно добавить другие типы контента по необходимости

def main():
    """Запускает бота."""
    # Инициализируем конфигурацию
    config = init_config()
    
    # Если токен не настроен, запрашиваем его
    global BOT_TOKEN
    if not BOT_TOKEN:
        print("⚠️ Токен бота не настроен. Введите токен бота:")
        BOT_TOKEN = input().strip()
        config["bot_token"] = BOT_TOKEN
        save_config(config)
    
    # Создаем приложение
    application = Application.builder().token(BOT_TOKEN).build()

    # Добавляем обработчики команд
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("create", create_command))
    application.add_handler(CommandHandler("settings", settings_command))
    application.add_handler(CommandHandler("status", status_command))
    application.add_handler(CommandHandler("stats", stats_command))
    
    # Добавляем обработчик для интерактивных кнопок настроек
    application.add_handler(CallbackQueryHandler(settings_callback))
    
    # Добавляем обработчик для новых участников в группе
    application.add_handler(MessageHandler(filters.ChatType.GROUPS & filters.StatusUpdate.NEW_CHAT_MEMBERS, handle_new_chat_members))
    
    # Добавляем обработчик для всех сообщений (для сбора статистики)
    application.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, handle_message))

    # Запускаем бота
    print(f"🚀 Бот запускается...")
    print(f"📁 Файлы сохраняются в директорию: {DATA_DIR}")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n🛑 Бот остановлен")
        # Сохраняем статистику перед выходом
        save_user_stats()