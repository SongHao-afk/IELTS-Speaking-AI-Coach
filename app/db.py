"""Local SQLite persistence, including automatic v1 -> v2 schema migration."""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any


class Database:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA busy_timeout=10000')
        conn.execute('PRAGMA foreign_keys=ON')
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def initialize(self) -> None:
        with self.connect() as conn:
            conn.execute('PRAGMA journal_mode=WAL')
            conn.execute('''CREATE TABLE IF NOT EXISTS attempts (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                question_id TEXT NOT NULL,
                part INTEGER NOT NULL,
                topic TEXT NOT NULL,
                prompt TEXT NOT NULL,
                transcript TEXT NOT NULL,
                transcription_source TEXT NOT NULL,
                duration_seconds REAL NOT NULL,
                metrics_json TEXT NOT NULL,
                evaluation_json TEXT,
                ai_error TEXT,
                cloud_audio_used INTEGER NOT NULL DEFAULT 0,
                estimated_band REAL,
                language_estimate_band REAL
            )''')
            columns = {row['name'] for row in conn.execute('PRAGMA table_info(attempts)')}
            if 'language_estimate_band' not in columns:
                conn.execute('ALTER TABLE attempts ADD COLUMN language_estimate_band REAL')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_attempts_created ON attempts(created_at DESC)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_attempts_session ON attempts(session_id)')

    @staticmethod
    def _decode(row: sqlite3.Row) -> dict[str, Any]:
        result = dict(row)
        result['metrics'] = json.loads(result.pop('metrics_json'))
        raw = result.pop('evaluation_json')
        result['evaluation'] = json.loads(raw) if raw else None
        result['cloud_audio_used'] = bool(result['cloud_audio_used'])
        return result

    def add(self, attempt: dict[str, Any]) -> None:
        with self.connect() as conn:
            conn.execute('''INSERT INTO attempts (
                id, session_id, created_at, question_id, part, topic, prompt,
                transcript, transcription_source, duration_seconds, metrics_json,
                evaluation_json, ai_error, cloud_audio_used, estimated_band,
                language_estimate_band
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''', (
                attempt['id'], attempt['session_id'], attempt['created_at'],
                attempt['question_id'], attempt['part'], attempt['topic'], attempt['prompt'],
                attempt['transcript'], attempt['transcription_source'], attempt['duration_seconds'],
                json.dumps(attempt['metrics'], ensure_ascii=False),
                json.dumps(attempt['evaluation'], ensure_ascii=False) if attempt['evaluation'] else None,
                attempt['ai_error'], int(attempt['cloud_audio_used']), attempt.get('estimated_band'),
                attempt.get('language_estimate_band'),
            ))

    def update_feedback(self, attempt_id: str, evaluation: dict | None, ai_error: str | None) -> bool:
        with self.connect() as conn:
            cursor = conn.execute('''UPDATE attempts SET evaluation_json=?, ai_error=?,
                language_estimate_band=? WHERE id=?''', (
                json.dumps(evaluation, ensure_ascii=False) if evaluation else None,
                ai_error, evaluation.get('language_estimate_band') if evaluation else None,
                attempt_id,
            ))
            return cursor.rowcount > 0

    def list(self, limit: int = 30, offset: int = 0) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute('SELECT * FROM attempts ORDER BY created_at DESC, rowid DESC LIMIT ? OFFSET ?',
                                (limit, offset)).fetchall()
            return [self._decode(r) for r in rows]

    def get(self, attempt_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute('SELECT * FROM attempts WHERE id=?', (attempt_id,)).fetchone()
            return self._decode(row) if row else None

    def delete_all(self) -> int:
        with self.connect() as conn:
            count = conn.execute('SELECT COUNT(*) FROM attempts').fetchone()[0]
            conn.execute('DELETE FROM attempts')
            return count

    def stats(self) -> dict[str, Any]:
        with self.connect() as conn:
            summary = conn.execute('''SELECT COUNT(*) AS total_attempts,
                COALESCE(ROUND(SUM(duration_seconds) / 60.0, 1), 0) AS total_minutes,
                ROUND(AVG(estimated_band), 2) AS average_estimated_band,
                ROUND(AVG(language_estimate_band), 2) AS average_language_estimate
                FROM attempts''').fetchone()
            recent = conn.execute('''SELECT DATE(created_at) AS day, COUNT(*) AS count
                FROM attempts GROUP BY DATE(created_at) ORDER BY day DESC LIMIT 60''').fetchall()
            parts = conn.execute('''SELECT part, COUNT(*) AS count FROM attempts GROUP BY part''').fetchall()
            trend = conn.execute('''SELECT created_at, language_estimate_band AS estimated_band
                FROM attempts WHERE language_estimate_band IS NOT NULL
                ORDER BY created_at DESC LIMIT 20''').fetchall()
        by_day = {r['day']: r['count'] for r in recent}
        today = datetime.now(timezone.utc).date()
        last7 = [
            {'day': (today - timedelta(days=6-i)).isoformat(),
             'count': by_day.get((today - timedelta(days=6-i)).isoformat(), 0)}
            for i in range(7)
        ]
        return {
            **dict(summary),
            'last7': last7,
            'by_part': {str(r['part']): r['count'] for r in parts},
            'band_trend': [dict(r) for r in reversed(trend)],
        }
