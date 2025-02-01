import sqlite3
from datetime import datetime
from typing import List, Tuple

class DatabaseManager:
    def __init__(self, db_name: str = 'tracks.db'):
        self.conn = sqlite3.connect(db_name)
        self._init_db()

    def _init_db(self):
        """Инициализация таблиц"""
        with self.conn:
            self.conn.execute('''
                CREATE TABLE IF NOT EXISTS tracks (
                    id INTEGER PRIMARY KEY,
                    user_id INTEGER,
                    file_id TEXT,
                    likes INTEGER DEFAULT 0,
                    created_at TEXT
                )''')
            self.conn.execute('''
                CREATE TABLE IF NOT EXISTS likes (
                    user_id INTEGER,
                    track_id INTEGER,
                    UNIQUE(user_id, track_id)
                )''')

    def add_track(self, user_id: int, file_id: str) -> int:
        """Добавление трека в БД"""
        with self.conn:
            cursor = self.conn.execute(
                'INSERT INTO tracks (user_id, file_id, created_at) VALUES (?, ?, ?)',
                (user_id, file_id, datetime.now().isoformat())
            )
            return cursor.lastrowid

    def like_track(self, user_id: int, track_id: int) -> bool:
        """Добавление лайка"""
        try:
            with self.conn:
                self.conn.execute(
                    'INSERT INTO likes (user_id, track_id) VALUES (?, ?)',
                    (user_id, track_id)
                )
                self.conn.execute(
                    'UPDATE tracks SET likes = likes + 1 WHERE id = ?',
                    (track_id,)
                )
            return True
        except sqlite3.IntegrityError:
            return False

    def get_top_tracks(self, limit: int = 10) -> List[Tuple]:
        """Получение топа треков"""
        with self.conn:
            cursor = self.conn.execute(
                'SELECT id, file_id, likes FROM tracks ORDER BY likes DESC LIMIT ?',
                (limit,)
            )
            return cursor.fetchall()

    def close(self):
        """Закрытие соединения"""
        self.conn.close()