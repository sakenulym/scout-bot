import os

# ── Required env vars ──────────────────────────────────────────────────────────
BOT_TOKEN = os.environ["BOT_TOKEN"]          # токен от @BotFather
SCOUT_GROUP_ID = os.environ["SCOUT_GROUP_ID"]  # ID группы скаутов (отрицательное число)
MANAGER_CHAT_ID = os.environ["MANAGER_CHAT_ID"]  # ID чата менеджеров

# ── Tunable settings ───────────────────────────────────────────────────────────
REPORT_TIMEOUT_MINUTES = int(os.getenv("REPORT_TIMEOUT_MINUTES", "20"))
DAY_END_HOUR = int(os.getenv("DAY_END_HOUR", "22"))
DAY_END_MINUTE = int(os.getenv("DAY_END_MINUTE", "0"))
TIMEZONE = os.getenv("TIMEZONE", "Asia/Almaty")
