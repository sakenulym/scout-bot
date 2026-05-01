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


@dp.message(Command("test"))
async def cmd_test(msg: Message):
    await msg.answer(f"✅ Бот работает! Chat ID: {msg.chat.id}")


@dp.message(Command("report"))
async def cmd_report(msg: Message):
    if str(msg.chat.id) != str(MANAGER_CHAT_ID):
        return
    text = build_daily_report(db, timeout_minutes=REPORT_TIMEOUT_MINUTES)
    await msg.answer(text, parse_mode="HTML")


@dp.message(Command("status"))
async def cmd_status(msg: Message):
    if str(msg.chat.id) != str(MANAGER_CHAT_ID):
        return
    alerts = check_missing_reports(db, timeout_minutes=REPORT_TIMEOUT_MINUTES)
    rows = db.get_last_report_per_scout()
    if not rows:
        await msg.answer("📭 Сегодня отчётов ещё не было.")
        return
    silent_ids = {a["scout_id"] for a in alerts}
    lines = ["📊 <b>Статус скаутов</b>\n"]
    for row in rows:
        ts = row["ts"][:16].replace("T", " ")
        icon = "🔴" if row["scout_id"] in silent_ids else "🟢"
        lines.append(f"{icon} <b>{row['scout_name']}</b>\n   Последний: {ts} | {row['report_type']} | {row['address']}")
    await msg.answer("\n".join(lines), parse_mode="HTML")


@dp.message()
async def handle_any_message(msg: Message):
    logger.info(f"Сообщение из чата {msg.chat.id} (группа скаутов: {SCOUT_GROUP_ID})")
    if str(msg.chat.id) != str(SCOUT_GROUP_ID):
        return
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
    logger.info(f"Отчёт сохранён: {scout_name} | {parsed['type']} | {parsed['address']}")


async def job_check_reports():
    alerts = check_missing_reports(db, timeout_minutes=REPORT_TIMEOUT_MINUTES)
    for alert in alerts:
        await bot.send_message(
            chat_id=MANAGER_CHAT_ID,
            text=f"⚠️ <b>Нет отчёта</b>\nСкаут: <b>{alert['name']}</b>\nПоследний: {alert['last_report']}\nМолчит: <b>{alert['silent_minutes']} мин</b>",
            parse_mode="HTML",
        )


async def job_daily_report():
    text = build_daily_report(db, timeout_minutes=REPORT_TIMEOUT_MINUTES)
    await bot.send_message(chat_id=MANAGER_CHAT_ID, text=text, parse_mode="HTML")
    db.close_day()


async def main():
    db.init()

    # Регистрируем команды только для чата менеджеров
    from aiogram.types import BotCommand, BotCommandScopeChat
    commands = [
        BotCommand(command="status", description="Статус скаутов (кто активен/молчит)"),
        BotCommand(command="report", description="Итоговый отчёт за сегодня"),
        BotCommand(command="test", description="Проверить работу бота"),
    ]
    await bot.set_my_commands(
        commands,
        scope=BotCommandScopeChat(chat_id=int(MANAGER_CHAT_ID))
    )
    # Убираем команды из всех остальных чатов
    from aiogram.types import BotCommandScopeDefault
    await bot.delete_my_commands(scope=BotCommandScopeDefault())

    scheduler.add_job(job_check_reports, "interval", minutes=5, id="check_reports")
    scheduler.add_job(job_daily_report, CronTrigger(hour=DAY_END_HOUR, minute=DAY_END_MINUTE), id="daily_report")
    scheduler.start()
    await dp.start_polling(bot, skip_updates=True)


if __name__ == "__main__":
    asyncio.run(main())
