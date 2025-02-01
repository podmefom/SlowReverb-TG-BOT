# SlowRevert Music Bot 🎵

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue)](https://python.org)
[![Telegram](https://img.shields.io/badge/Telegram-Bot-0088CC)](https://core.telegram.org/bots)

Бот для обработки аудио с эффектами:
    - Замедление/ускорение
    - Реверберация
    - Коррекция басов
    - Система лайков и топ треков

## 🚀 Быстрый старт

1. Клонировать репозиторий:
    ```bash
    git clone https://github.com/ваш-логин/SlowRevertBot.git

2. Установить зависимости:
    t

3. Настроить окружение:
    cp .env.example .env
    # Заполнить BOT_TOKEN=ваш_токен_бота

4. Запустить бота:
    python -m bot.main


🌟 Особенности
    - Обработка аудио в реальном времени

    - Интерактивное меню настроек

    - Рейтинговая система треков

    - Поддержка форматов MP3/WAV/OGG


Основные модули
    - AudioProcessor - обработка аудио:

    - Изменение скорости

    - Добавление реверберации

    - Коррекция частот

DatabaseManager - работа с БД:

    - Хранение треков

    - Учет лайков

    - Формирование топа

MusicBot - ядро бота:

    - Обработка команд

    - Управление состояниями

    - Взаимодействие с API Telegram