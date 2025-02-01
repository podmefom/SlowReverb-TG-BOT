import logging
import os
import tempfile
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackContext,
    filters,
    ConversationHandler,
    CallbackQueryHandler
)

from bot.audio_processor import AudioProcessor
from bot.database import DatabaseManager
from pydub import AudioSegment
import sqlite3

# Загрузка переменных окружения
load_dotenv()

# Конфигурация логов
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Состояния диалога
UPLOAD, SET_SPEED, SET_REVERB, SET_BASS, CONFIRM = range(5)

class MusicBot:
    def __init__(self):
        self.token = ('BOT_TOKEN')
        self.db = DatabaseManager()
        self.audio_processor = AudioProcessor()

    async def start(self, update: Update, context: CallbackContext) -> int:
        """Обработка команды /start"""
        await update.message.reply_text(
            '🎧 Отправь аудиофайл (MP3/WAV/OGG)',
            reply_markup=InlineKeyboardMarkup([])
        )
        return UPLOAD

    async def _handle_audio(self, update: Update, context: CallbackContext) -> int:
        try:
            audio_file = update.message.audio
            logger.info(f"Начало обработки файла: {audio_file.file_name}")
            
            # Сохраняем оригинальное имя файла
            context.user_data['original_filename'] = audio_file.file_name
            logger.debug("Имя файла сохранено")
            
            # Проверка размера файла
            if audio_file.file_size > 50 * 1024 * 1024:
                logger.warning("Файл слишком большой")
                await update.message.reply_text("❌ Файл превышает 50 МБ")
                return ConversationHandler.END

            # Создаем временный файл
            with tempfile.NamedTemporaryFile(suffix='.ogg', delete=False) as tmp:
                input_path = tmp.name
                logger.debug(f"Временный файл создан: {input_path}")
                
                # Скачиваем файл
                file = await audio_file.get_file()
                await file.download_to_drive(input_path)
                logger.info("Файл успешно скачан")

            context.user_data['input_path'] = input_path
            logger.debug("Переход к настройке скорости")
            
            # Отправляем инструкцию
            await update.message.reply_text(
                "🐢 **Шаг 1/3: Укажите скорость (0.1-2.0):**\n"
                "Пример: 0.7 — умеренное замедление",
                parse_mode="Markdown"
            )
            return SET_SPEED

        except Exception as e:
            logger.error(f"Ошибка: {e}", exc_info=True)
            await update.message.reply_text("🚨 Произошла ошибка при загрузке файла")
            return ConversationHandler.END

    async def _set_speed(self, update: Update, context: CallbackContext) -> int:
        """Обработка скорости воспроизведения"""
        try:
            speed = float(update.message.text)
            if not 0.1 <= speed <= 2.0:
                raise ValueError
            
            context.user_data['speed'] = speed
            await update.message.reply_text(
                "🏔️ **Шаг 2/3: Укажите параметры реверберации (задержка и уровень):**\n"
                "Пример: 150 0.5 — среднее эхо",
                parse_mode="Markdown"
            )
            return SET_REVERB

        except ValueError:
            await update.message.reply_text(
                "❌ Некорректное значение! Введите число от 0.1 до 2.0.\n"
                "Пример: 0.7"
            )
            return SET_SPEED

    async def _set_reverb(self, update: Update, context: CallbackContext) -> int:
        """Обработка параметров реверберации"""
        try:
            delay, decay = map(float, update.message.text.split())
            if not (10 <= delay <= 1000) or not (0 <= decay <= 1):
                raise ValueError
            
            context.user_data['reverb'] = (int(delay), decay)
            await update.message.reply_text(
                "🔊 **Шаг 3/3: Укажите коррекцию басов (-20 до +20):**\n"
                "Пример: -5 — уменьшить басы",
                parse_mode="Markdown"
            )
            return SET_BASS

        except:
            await update.message.reply_text(
                "❌ Некорректный ввод! Используйте формат: <задержка> <уровень>\n"
                "Пример: 200 0.5"
            )
            return SET_REVERB

    async def _set_bass(self, update: Update, context: CallbackContext) -> int:
        """Обработка коррекции басов"""
        try:
            bass = float(update.message.text)
            if not -20 <= bass <= 20:
                raise ValueError
            
            context.user_data['bass'] = bass
            await update.message.reply_text(
                "✅ Все параметры установлены! Отправьте /process для обработки."
            )
            return CONFIRM

        except ValueError:
            await update.message.reply_text(
                "❌ Некорректное значение! Введите число от -20 до 20.\n"
                "Пример: -5"
            )
            return SET_BASS

    async def _process_audio(self, update: Update, context: CallbackContext) -> int:
        """Обработка и публикация трека"""
        try:
            user_data = context.user_data
            original_filename = user_data.get('original_filename', 'Обработанный трек')
            
            # Загрузка и обработка аудио
            audio = AudioSegment.from_file(user_data['input_path'])
            audio = self.audio_processor.apply_slow(audio, user_data['speed'])
            audio = self.audio_processor.apply_reverb(audio, *user_data['reverb'])
            audio = self.audio_processor.adjust_bass(audio, user_data['bass'])
            
            # Экспорт во временный файл
            with tempfile.NamedTemporaryFile(suffix='.ogg', delete=False) as tmp:
                output_path = tmp.name
                audio.export(output_path, format="ogg", bitrate="192k")
            
            # Отправка аудио
            with open(output_path, 'rb') as audio_file:
                msg = await update.message.reply_audio(
                    audio=audio_file,
                    title=original_filename,
                    performer="Обработано ботом",
                    duration=int(len(audio) / 1000)
                )
                
                # Сохранение в БД
                track_id = self.db.add_track(update.effective_user.id, msg.audio.file_id)
                await update.message.reply_text(
                    '✅ Трек готов!\n\n Пиши /start, чтобы сделать еще один!',
                )

        except Exception as e:
            logger.error(f"Ошибка обработки: {e}", exc_info=True)
            await update.message.reply_text('❌ Произошла ошибка при обработке аудио')
        
        finally:
            # Очистка временных файлов
            if 'input_path' in user_data:
                try:
                    os.remove(user_data['input_path'])
                except Exception as e:
                    logger.error(f"Ошибка удаления входного файла: {e}")
            if 'output_path' in locals():
                try:
                    os.remove(output_path)
                except Exception as e:
                    logger.error(f"Ошибка удаления выходного файла: {e}")
            context.user_data.clear()
        
        return ConversationHandler.END

    async def _handle_like(self, update: Update, context: CallbackContext) -> None:
        """Обработка лайков"""
        query = update.callback_query
        await query.answer()
        
        user_id = query.from_user.id
        track_id = int(query.data.split('_')[1])
        
        if self.db.like_track(user_id, track_id):
            likes = self.db.get_track_likes(track_id)
        else:
            await query.answer("Вы уже лайкали этот трек!")
    
    async def show_top(self, update: Update, context: CallbackContext):
        conn = sqlite3.connect('tracks.db')
        c = conn.cursor()
        
        try:
            c.execute('SELECT id, file_id, likes FROM tracks ORDER BY likes DESC LIMIT 10')
            tracks = c.fetchall()
            
            if not tracks:
                await update.message.reply_text('😔 В топе пока нет треков. Будьте первым!')
                return
                
            await update.message.reply_text('🏆 Топ 10 треков:')
            
            for idx, (track_id, file_id, likes) in enumerate(tracks, 1):
                try:
                    await context.bot.send_audio(
                        chat_id=update.effective_chat.id,
                        audio=file_id,
                        caption=f"#{idx} 🎵 Лайков: {likes}",
                        reply_markup=self._get_track_keyboard(track_id, likes)
                    )
                except Exception as e:
                    logger.error(f"Ошибка отправки трека {track_id}: {e}")
                    
        except Exception as e:
            logger.error(f"Ошибка топа: {e}")
            await update.message.reply_text('❌ Не удалось загрузить топ')
        finally:
            conn.close()

    def run(self):
        app = ApplicationBuilder().token(self.token).build()

        conv_handler = ConversationHandler(
            entry_points=[CommandHandler('start', self.start)],
            states={
                UPLOAD: [MessageHandler(filters.AUDIO, self._handle_audio)],
                SET_SPEED: [MessageHandler(filters.TEXT & ~filters.COMMAND, self._set_speed)],  # Исправлено
                SET_REVERB: [MessageHandler(filters.TEXT & ~filters.COMMAND, self._set_reverb)],  # Исправлено
                SET_BASS: [MessageHandler(filters.TEXT & ~filters.COMMAND, self._set_bass)],  # Исправлено
                CONFIRM: [CommandHandler('process', self._process_audio)]  # Исправлено
            },
            fallbacks=[CommandHandler('cancel', lambda u,c: ConversationHandler.END)],
        )

        app.add_handler(conv_handler)
        app.add_handler(CallbackQueryHandler(self._handle_like, pattern='^like_'))
        app.add_handler(CommandHandler('top', self.show_top))
        
        logger.info("Бот запущен")
        app.run_polling()

if __name__ == '__main__':
    MusicBot().run()