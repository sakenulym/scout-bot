import asyncio
import logging
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from config import (
    BOT_TOKEN, SCOUT_GROUP_ID, MANAGER_CHAT_ID,
    REPORT_TIMEOUT_MINUTES, DAY_END_HOUR, DAY_END_MINUTE, TIMEZONE,
)
from database import Database
from report_parser import parse_report
from analytics import build_daily_report, check_missing_reports

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
db = Database()
scheduler = AsyncIOScheduler(timezone=TIMEZONE)


@dp.message(F.chat.id == int(SCOUT_GROUP_ID))
async def handle_group_message(msg: Message):
    text = msg.text or msg.caption or ""
    has_media = bool(msg.photo or msg.document)
    parsed = parse_report(text, has_media=has_media)
    if not parsed:
        return
    scout_id = msg.from_user.id
    scout_name = msg.from_user.full_name or msg.from_user.username or str(scout_id)
    db.save_report(
        scout_id=scout_id, scout_name=scout_name,
        report_type=parsed["type"], address=parsed["address"],
        scooter_count=parsed["scooters"], raw_text=text, timestamp=msg.date,
    )
    logger.info(f"Отчёт: {scout_name} | {parsed['type']} | {parsed['address']} | {parsed['scooters']} шт")


@dp.message(Command("report"))
async def cmd_report(msg: Message):
    """Ручной запрос итогового отчёта за сегодня — только из чата менеджеров."""
    if str(msg.chat.id) != str(MANAGER_CHAT_ID):
        return
    text = build_daily_report(db, timeout_minutes=REPORT_TIMEOUT_MINUTES)
    await msg.answer(text, parse_mode="HTML")


@dp.message(Command("status"))
async def cmd_status(msg: Message):
    """Текущий статус всех скаутов — кто онлайн, кто молчит."""
    if str(msg.chat.id) != str(MANAGER_CHAT_ID):
        return
    alerts = check_missing_reports(db, timeout_minutes=REPORT_TIMEOUT_MINUTES)
    rows = db.get_last_report_per_scout()
    if not rows:
        await msg.answer("📭 Сегодня отчётов ещё не было.")
        return
    lines = ["📊 <b>Статус скаутов</b>\n"]
    silent_ids = {a["scout_id"] for a in alerts}
    for row in rows:
        ts = row["ts"][:16].replace("T", " ")
        icon = "🔴" if row["scout_id"] in silent_ids else "🟢"
        lines.append(
            f"{icon} <b>{row['scout_name']}</b>\n"
            f"   Последний: {ts} | {row['report_type']} | {row['address']}"
        )
    await msg.answer("\n".join(lines), parse_mode="HTML")


async def job_check_reports():
    alerts = check_missing_reports(db, timeout_minutes=REPORT_TIMEOUT_MINUTES)
    for alert in alerts:
        await bot.send_message(
            chat_id=MANAGER_CHAT_ID,
            text=(
                f"⚠️ <b>Нет отчёта</b>\n"
                f"Скаут: <b>{alert['name']}</b>\n"
                f"Последний отчёт: {alert['last_report']}\n"
                f"Молчит уже: <b>{alert['silent_minutes']} мин</b>"
            ),
            parse_mode="HTML",
        )


async def job_daily_report():
    report_text = build_daily_report(db, timeout_minutes=REPORT_TIMEOUT_MINUTES)
    await bot.send_message(chat_id=MANAGER_CHAT_ID, text=report_text, parse_mode="HTML")
    db.close_day()
    logger.info("Итоговый отчёт отправлен, день закрыт.")


async def main():
    db.init()
    scheduler.add_job(job_check_reports, "interval", minutes=5, id="check_reports")
    scheduler.add_job(job_daily_report, CronTrigger(hour=DAY_END_HOUR, minute=DAY_END_MINUTE), id="daily_report")
    scheduler.start()
    await dp.start_polling(bot, skip_updates=True)


if __name__ == "__main__":
    asyncio.run(main())
