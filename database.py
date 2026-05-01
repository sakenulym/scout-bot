import sqlite3
import logging
from datetime import datetime, date
from typing import Optional

logger = logging.getLogger(__name__)

DB_PATH = "scout_bot.db"


class Database:
    def __init__(self):
        self.conn: Optional[sqlite3.Connection] = None

    def init(self):
        self.conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._create_tables()
        logger.info("Database initialised.")

    def _create_tables(self):
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS reports (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                scout_id      INTEGER NOT NULL,
                scout_name    TEXT    NOT NULL,
                report_type   TEXT    NOT NULL DEFAULT 'парковка',
                address       TEXT,
                scooter_count INTEGER DEFAULT 0,
                raw_text      TEXT,
                ts            DATETIME NOT NULL,
                day           DATE NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_reports_day   ON reports(day);
            CREATE INDEX IF NOT EXISTS idx_reports_scout ON reports(scout_id, day);
            CREATE INDEX IF NOT EXISTS idx_reports_ts    ON reports(scout_id, ts);

            CREATE TABLE IF NOT EXISTS closed_days (
                day DATE PRIMARY KEY
            );
        """)
        self.conn.commit()

    def save_report(
        self,
        scout_id: int,
        scout_name: str,
        report_type: str,
        address: str,
        scooter_count: int,
        raw_text: str,
        timestamp: datetime,
    ):
        day = timestamp.date().isoformat()
        self.conn.execute(
            """
            INSERT INTO reports
                (scout_id, scout_name, report_type, address, scooter_count, raw_text, ts, day)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (scout_id, scout_name, report_type, address, scooter_count,
             raw_text, timestamp.isoformat(), day),
        )
        self.conn.commit()

    def get_today_reports(self, day: Optional[str] = None) -> list[sqlite3.Row]:
        if day is None:
            day = date.today().isoformat()
        rows = self.conn.execute(
            "SELECT * FROM reports WHERE day = ? ORDER BY scout_id, ts",
            (day,),
        ).fetchall()
        return rows

    def get_last_report_per_scout(self, day: Optional[str] = None) -> list[sqlite3.Row]:
        """Returns the most recent report row for each scout active today."""
        if day is None:
            day = date.today().isoformat()
        rows = self.conn.execute(
            """
            SELECT r.*
            FROM reports r
            INNER JOIN (
                SELECT scout_id, MAX(ts) AS max_ts
                FROM reports
                WHERE day = ?
                GROUP BY scout_id
            ) latest ON r.scout_id = latest.scout_id AND r.ts = latest.max_ts
            """,
            (day,),
        ).fetchall()
        return rows

    def get_scout_reports_today(self, scout_id: int, day: Optional[str] = None) -> list[sqlite3.Row]:
        if day is None:
            day = date.today().isoformat()
        return self.conn.execute(
            "SELECT * FROM reports WHERE scout_id = ? AND day = ? ORDER BY ts",
            (scout_id, day),
        ).fetchall()

    def close_day(self, day: Optional[str] = None):
        if day is None:
            day = date.today().isoformat()
        self.conn.execute("INSERT OR IGNORE INTO closed_days (day) VALUES (?)", (day,))
        self.conn.commit()
        logger.info(f"Day {day} closed.")
