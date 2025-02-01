import logging
from pydub import AudioSegment
from pydub.effects import low_pass_filter
from telegram import Update, ReplyKeyboardRemove, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackContext,
    filters,
    ConversationHandler,
    CallbackQueryHandler
)
import os
import tempfile
import sqlite3
from datetime import datetime

# Инициализация базы данных
def init_db():
    conn = sqlite3.connect('tracks.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS tracks 
                 (id INTEGER PRIMARY KEY, 
                  user_id INTEGER, 
                  file_id TEXT, 
                  likes INTEGER DEFAULT 0, 
                  created_at TEXT)''')  # Исправлен тип даты
    c.execute('''CREATE TABLE IF NOT EXISTS likes 
                 (user_id INTEGER, 
                  track_id INTEGER,
                  UNIQUE(user_id, track_id))''')
    conn.commit()
    conn.close()

init_db()

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

UPLOAD, SET_SPEED, SET_REVERB, SET_BASS, CONFIRM = range(5)

def get_track_keyboard(track_id, likes=0):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"❤️ {likes}", callback_data=f"like_{track_id}")],
        [InlineKeyboardButton("Топ треков", callback_data="top")]
    ])

async def start(update: Update, context: CallbackContext) -> int:
    await update.message.reply_text(
        '🎧 Отправь мне аудиофайл для обработки\n'
        'Поддерживаемые форматы: MP3, WAV, OGG',
        reply_markup=ReplyKeyboardRemove()
    )
    return UPLOAD

async def handle_audio(update: Update, context: CallbackContext) -> int:
    try:
        audio_file = update.message.audio
        context.user_data['original_filename'] = audio_file.file_name  # Сохраняем имя файла
        
        with tempfile.NamedTemporaryFile(suffix='.ogg', delete=False) as tmp:
            input_path = tmp.name
            file = await audio_file.get_file()
            await file.download_to_drive(input_path)
        
        context.user_data['input_path'] = input_path
        
        await update.message.reply_text(
            '🎛️ <b>Сейчас настроим звук! Вот что нужно сделать:</b>\n\n'
            '1. Замедление/ускорение\n'
            '2. Эффект эха\n'
            '3. Коррекция басов\n\n'
            'На каждом шаге я буду объяснять параметры. '
            'Можете использовать готовые примеры!',
            parse_mode='HTML'
        )
        return await set_speed(update, context)

    except Exception as e:
        logger.error(f"Ошибка загрузки: {e}")
        await update.message.reply_text('❌ Ошибка загрузки файла')
        return ConversationHandler.END

# ... (функции set_speed, set_reverb, set_bass остаются без изменений) ...

async def process_audio(update: Update, context: CallbackContext) -> int:
    try:
        user_data = context.user_data
        original_filename = user_data.get('original_filename', 'Обработанный трек')
        
        audio = AudioSegment.from_file(user_data['input_path'])
        audio = apply_slow(audio, user_data['speed'])
        audio = apply_reverb(audio, *user_data['reverb'])
        audio = adjust_bass(audio, user_data['bass'])
        
        with tempfile.NamedTemporaryFile(suffix='.ogg', delete=False) as tmp:
            output_path = tmp.name
            audio.export(output_path, format="ogg", bitrate="192k")
        
        with open(output_path, 'rb') as audio_file:
            msg = await update.message.reply_audio(
                audio=audio_file,
                title=original_filename,  # Используем оригинальное имя
                performer="Обработано ботом",
                duration=int(len(audio)/1000)
            )
            
            conn = sqlite3.connect('tracks.db')
            c = conn.cursor()
            c.execute('''INSERT INTO tracks 
                      (user_id, file_id, created_at) 
                      VALUES (?, ?, ?)''',
                      (update.effective_user.id, 
                       msg.audio.file_id, 
                       datetime.now().isoformat()))  # Исправленный формат даты
            track_id = c.lastrowid
            conn.commit()
            conn.close()

            await update.message.reply_text(
                '✅ Готово! Трек опубликован.\n'
                '❤️ Лайкайте треки в /top',
                reply_markup=get_track_keyboard(track_id)
            )

    except Exception as e:
        logger.error(f"Ошибка обработки: {e}")
        await update.message.reply_text('❌ Произошла ошибка при обработке')

    finally:
        cleanup(user_data)
        context.user_data.clear()
    
    return ConversationHandler.END

async def handle_like(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    track_id = int(query.data.split('_')[1])
    
    conn = sqlite3.connect('tracks.db')
    c = conn.cursor()
    
    try:
        c.execute('INSERT INTO likes (user_id, track_id) VALUES (?, ?)', (user_id, track_id))
        c.execute('UPDATE tracks SET likes = likes + 1 WHERE id = ?', (track_id,))
        conn.commit()
        
        c.execute('SELECT likes FROM tracks WHERE id = ?', (track_id,))
        new_likes = c.fetchone()[0]
        
        await query.message.edit_reply_markup(
            reply_markup=get_track_keyboard(track_id, new_likes)
        )
        
    except sqlite3.IntegrityError:
        await query.answer('Вы уже лайкали этот трек!')
    except Exception as e:
        logger.error(f"Ошибка лайка: {e}")
        await query.answer('Ошибка при обработке лайка')
    finally:
        conn.close()

async def show_top(update: Update, context: CallbackContext):
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
                    reply_markup=get_track_keyboard(track_id, likes)
                )
            except Exception as e:
                logger.error(f"Ошибка отправки трека {track_id}: {e}")
                
    except Exception as e:
        logger.error(f"Ошибка топа: {e}")
        await update.message.reply_text('❌ Не удалось загрузить топ')
    finally:
        conn.close()

async def set_speed(update: Update, context: CallbackContext) -> int:
    """Обработка скорости с примерами"""
    if 'speed_guide_shown' not in context.user_data:
        await update.message.reply_text(
            '🐢 <b>Шаг 1/3: Скорость воспроизведения</b>\n\n'
            'Введите число:\n'
            '▫️ 0.5 — замедлить в 2 раза\n'
            '▫️ 0.7 — оптимально для музыки\n'
            '▫️ 1.0 — оригинальная скорость\n'
            '▫️ 1.3 — ускорение на 30%\n\n'
            '<i>Пример: 0.8</i>',
            parse_mode='HTML'
        )
        context.user_data['speed_guide_shown'] = True
        return SET_SPEED

    try:
        speed = float(update.message.text)
        if not 0.1 <= speed <= 2.0:
            raise ValueError
        
        context.user_data['speed'] = speed
        del context.user_data['speed_guide_shown']
        return await set_reverb(update, context)

    except:
        await update.message.reply_text(
            '❌ Не понял. Введите число между 0.1 и 2.0.\n'
            'Например: 0.7'
        )
        return SET_SPEED

async def set_reverb(update: Update, context: CallbackContext) -> int:
    """Обработка реверберации с примерами"""
    if 'reverb_guide_shown' not in context.user_data:
        await update.message.reply_text(
            '🏔️ <b>Шаг 2/3: Эффект эха</b>\n\n'
            'Введите два числа через пробел:\n'
            '1. Задержка (мс): 50-500\n'
            '2. Уровень: 0.1-1.0\n\n'
            '<i>Примеры:\n'
            '• 150 0.4 — легкое эхо\n'
            '• 300 0.7 — эффект пещеры</i>',
            parse_mode='HTML'
        )
        context.user_data['reverb_guide_shown'] = True
        return SET_REVERB

    try:
        delay, decay = map(float, update.message.text.split())
        if not (10 <= delay <= 1000) or not (0 <= decay <= 1):
            raise ValueError
        
        context.user_data['reverb'] = (int(delay), decay)
        del context.user_data['reverb_guide_shown']
        return await set_bass(update, context)

    except:
        await update.message.reply_text(
            '❌ Ошибка формата! Введите два числа через пробел.\n'
            'Пример: 200 0.5'
        )
        return SET_REVERB

async def set_bass(update: Update, context: CallbackContext) -> int:
    """Обработка басов с примерами"""
    if 'bass_guide_shown' not in context.user_data:
        await update.message.reply_text(
            '🔊 <b>Шаг 3/3: Коррекция басов</b>\n\n'
            'Введите число от -20 до +20:\n'
            '▫️ -10 — мало басов\n'
            '▫️ 0 — без изменений\n'
            '▫️ +10 — мощные басы\n\n'
            '<i>Пример: -5</i>',
            parse_mode='HTML'
        )
        context.user_data['bass_guide_shown'] = True
        return SET_BASS

    try:
        bass = float(update.message.text)
        if not -20 <= bass <= 20:
            raise ValueError
        
        context.user_data['bass'] = bass
        del context.user_data['bass_guide_shown']
        await update.message.reply_text(
            '✅ Все готово! Отправьте /process чтобы начать обработку\n'
            '🔄 /cancel — начать заново'
        )
        return CONFIRM

    except:
        await update.message.reply_text(
            '❌ Некорректное значение! Введите число от -20 до 20.\n'
            'Пример: -7'
        )
        return SET_BASS

async def process_audio(update: Update, context: CallbackContext) -> int:
    try:
        user_data = context.user_data
        audio = AudioSegment.from_file(user_data['input_path'])
        
        # Применяем эффекты
        audio = apply_slow(audio, user_data['speed'])
        audio = apply_reverb(audio, *user_data['reverb'])
        audio = adjust_bass(audio, user_data['bass'])
        
        # Сохраняем результат
        with tempfile.NamedTemporaryFile(suffix='.ogg', delete=False) as tmp:
            output_path = tmp.name
            audio.export(output_path, format="ogg", bitrate="192k")
        
        await update.message.reply_audio(audio=output_path)
        await update.message.reply_text('✅ Готово! Новый файл выше\n\n/start Новый ремиксик 0_o')

    except Exception as e:
        logger.error(f"Ошибка обработки: {e}")
        await update.message.reply_text('❌ Произошла ошибка при обработке')

    finally:
        cleanup(user_data)
        context.user_data.clear()
    
    return ConversationHandler.END

def apply_slow(audio: AudioSegment, speed: float) -> AudioSegment:
    return audio._spawn(
        audio.raw_data,
        overrides={"frame_rate": int(audio.frame_rate * speed)}
    ).set_frame_rate(audio.frame_rate)

def apply_reverb(audio: AudioSegment, delay: int, decay: float) -> AudioSegment:
    delayed = audio[-delay:].append(
        AudioSegment.silent(duration=delay),
        crossfade=0
    ).apply_gain(decay * 20)
    return audio.overlay(delayed, times=2, position=delay//2)

def adjust_bass(audio: AudioSegment, gain_db: float) -> AudioSegment:
    """Коррекция низких частот через low-pass фильтр"""
    if gain_db < 0:
        # Уменьшаем басы
        return low_pass_filter(audio, cutoff=200).apply_gain(gain_db)
    elif gain_db > 0:
        # Усиливаем басы
        return audio.low_pass_filter(150).apply_gain(gain_db) + audio
    return audio

def cleanup(user_data: dict):
    for path in [user_data.get('input_path')]:
        if path and os.path.exists(path):
            try: os.remove(path)
            except: pass

async def process_audio(update: Update, context: CallbackContext) -> int:
    try:
        user_data = context.user_data
        
        # Проверка наличия необходимых данных
        if 'input_path' not in user_data:
            await update.message.reply_text('❌ Файл не найден. Начните заново /start')
            return ConversationHandler.END

        # Загрузка и обработка аудио
        try:
            audio = AudioSegment.from_file(user_data['input_path'])
            audio = apply_slow(audio, user_data['speed'])
            audio = apply_reverb(audio, *user_data['reverb'])
            audio = adjust_bass(audio, user_data['bass'])
        except Exception as processing_error:
            logger.error(f"Ошибка обработки аудио: {processing_error}")
            await update.message.reply_text('❌ Ошибка при обработке аудио')
            return ConversationHandler.END

        # Экспорт во временный файл
        output_path = None
        try:
            with tempfile.NamedTemporaryFile(suffix='.ogg', delete=False) as tmp:
                output_path = tmp.name
                audio.export(output_path, 
                           format="ogg",
                           bitrate="192k",
                           parameters=["-acodec", "libvorbis"])
                
                # Проверка размера файла
                file_size = os.path.getsize(output_path)
                if file_size > 50 * 1024 * 1024:
                    await update.message.reply_text('❌ Файл слишком большой (максимум 50 МБ)')
                    return
        except Exception as export_error:
            logger.error(f"Ошибка экспорта: {export_error}")
            await update.message.reply_text('❌ Ошибка при сохранении файла')
            return

        # Попытка отправки файла
        try:
            with open(output_path, 'rb') as audio_file:
                msg = await update.message.reply_audio(
                    audio=audio_file,
                    title="Обработанный трек",
                    performer="AudioBot",
                    duration=int(len(audio)/1000),
                    parse_mode='HTML'
                )
                
                if not msg.audio:
                    raise ValueError("Пустой ответ от Telegram API")
                
                # Сохранение в базу данных
                conn = sqlite3.connect('tracks.db')
                c = conn.cursor()
                c.execute('''INSERT INTO tracks 
                          (user_id, file_id, created_at) 
                          VALUES (?, ?, ?)''',
                        (update.effective_user.id, msg.audio.file_id, datetime.now()))
                track_id = c.lastrowid
                conn.commit()
                conn.close()

                await update.message.reply_text(
                    '✅ Трек успешно обработан и опубликован!\n'
                    '❤️ Лайкните его в /top',
                    reply_markup=get_track_keyboard(track_id)
                )

        except Exception as send_error:
            logger.error(f"Ошибка отправки: {send_error}")
            await update.message.reply_text('❌ Не удалось отправить файл. Попробуйте другой формат.')

    except Exception as global_error:
        logger.error(f"Критическая ошибка: {global_error}", exc_info=True)
        await update.message.reply_text('🚨 Произошла непредвиденная ошибка')

    finally:
        # Очистка временных файлов
        if 'input_path' in user_data:
            try:
                os.remove(user_data['input_path'])
            except Exception as e:
                logger.warning(f"Ошибка удаления входного файла: {e}")
        
        if output_path and os.path.exists(output_path):
            try:
                os.remove(output_path)
            except Exception as e:
                logger.warning(f"Ошибка удаления выходного файла: {e}")
        
        context.user_data.clear()
    
    return ConversationHandler.END

async def publish_track(update: Update, context: CallbackContext):
    # Логика публикации трека
    pass

async def show_top(update: Update, context: CallbackContext):
    conn = sqlite3.connect('tracks.db')
    c = conn.cursor()
    c.execute('SELECT id, file_id, likes FROM tracks ORDER BY likes DESC LIMIT 10')
    tracks = c.fetchall()
    
    response = "🏆 Топ треков:\n\n"
    for idx, (track_id, file_id, likes) in enumerate(tracks, 1):
        response += f"{idx}. Лайков: {likes}\n"
        await context.bot.send_audio(
            chat_id=update.effective_chat.id,
            audio=file_id,
            reply_markup=get_track_keyboard(track_id)
        )
    
    conn.close()
    await update.message.reply_text(response)

async def handle_like(update: Update, context: CallbackContext):
    query = update.callback_query
    user_id = query.from_user.id
    track_id = int(query.data.split('_')[1])
    
    conn = sqlite3.connect('tracks.db')
    c = conn.cursor()
    
    try:
        c.execute('INSERT INTO likes (user_id, track_id) VALUES (?, ?)', (user_id, track_id))
        c.execute('UPDATE tracks SET likes = likes + 1 WHERE id = ?', (track_id,))
        conn.commit()
        await query.answer('Ваш лайк учтен!')
    except sqlite3.IntegrityError:
        await query.answer('Вы уже лайкали этот трек!')
    finally:
        conn.close()
    
    # Обновляем клавиатуру
    await query.message.edit_reply_markup(reply_markup=get_track_keyboard(track_id))

def main():
    token = 'bot_token'
    application = ApplicationBuilder().token(token).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            UPLOAD: [MessageHandler(filters.AUDIO, handle_audio)],
            SET_SPEED: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_speed)],
            SET_REVERB: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_reverb)],
            SET_BASS: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_bass)],
            CONFIRM: [CommandHandler('process', process_audio)]
        },
        fallbacks=[CommandHandler('cancel', lambda u,c: ConversationHandler.END)],
    )

    application.add_handler(conv_handler)
    application.add_handler(CommandHandler('top', show_top))
    application.add_handler(CallbackQueryHandler(handle_like, pattern='^like_'))
    
    application.run_polling()

if __name__ == '__main__':
    main()