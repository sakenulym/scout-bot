import asyncio
import logging
from datetime import datetime, timezone, timedelta
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message, BotCommand, BotCommandScopeChat, BotCommandScopeDefault
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from config import (
    BOT_TOKEN, SCOUT_GROUP_ID, MANAGER_CHAT_ID,
    REPORT_TIMEOUT_MINUTES, DAY_END_HOUR, DAY_END_MINUTE, TIMEZONE,
)
from database import Database
from report_parser import parse_report, REPORT_TYPE_BREAK
from analytics import build_daily_report, check_missing_reports, ALMATY_TZ

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
db = Database()
scheduler = AsyncIOScheduler(timezone=TIMEZONE)

# Трекер алертов: scout_id -> время последнего алерта
alert_tracker: dict[int, datetime] = {}
ALERT_REPEAT_MINUTES = 15  # повтор алерта каждые 15 мин


@dp.message(Command("test"))
async def cmd_test(msg: Message):
    await msg.answer(f"✅ Бот работает! Chat ID: {msg.chat.id}")


@dp.message(Command("report"))
async def cmd_report(msg: Message):
    if str(msg.chat.id) != str(MANAGER_CHAT_ID):
        return
    await msg.answer(build_daily_report(db, timeout_minutes=REPORT_TIMEOUT_MINUTES), parse_mode="HTML")


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
        dt = datetime.fromisoformat(row["ts"])
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        dt_almaty = dt.astimezone(ALMATY_TZ)
        ts = dt_almaty.strftime("%H:%M")
        rtype = (row["report_type"] or "").lower()

        if rtype == REPORT_TYPE_BREAK:
            elapsed = int((datetime.now(ALMATY_TZ) - dt_almaty).total_seconds() / 60)
            remaining = 60 - elapsed
            addr = row["address"] or "обед"
            icon = "🍽"
            status = f"На {addr} (осталось ~{max(0, remaining)} мин)"
        elif row["scout_id"] in silent_ids:
            icon = "🔴"
            status = f"Последний: {ts} | {row['report_type']} | {row['address']}"
        else:
            icon = "🟢"
            status = f"Последний: {ts} | {row['report_type']} | {row['address']}"

        lines.append(f"{icon} <b>{row['scout_name']}</b>\n   {status}")
    await msg.answer("\n".join(lines), parse_mode="HTML")


@dp.message()
async def handle_any_message(msg: Message):
    if str(msg.chat.id) != str(SCOUT_GROUP_ID):
        return
    text = msg.text or msg.caption or ""
    has_media = bool(msg.photo or msg.document)
    parsed = parse_report(text, has_media=has_media)
    if not parsed:
        return

    scout_id   = msg.from_user.id
    scout_name = msg.from_user.full_name or msg.from_user.username or str(scout_id)

    # Для перерыва — сохраняем тип (обед/ужин) в поле address
    address = parsed.get("break_type", parsed.get("address", "—")) if parsed["type"] == REPORT_TYPE_BREAK else parsed.get("address", "—")

    db.save_report(
        scout_id=scout_id, scout_name=scout_name,
        report_type=parsed["type"], address=address,
        scooter_count=parsed["scooters"], raw_text=text, timestamp=msg.date,
    )

    # Уведомляем менеджеров об обеде/ужине
    if parsed["type"] == REPORT_TYPE_BREAK:
        break_type = parsed.get("break_type", "обед")
        await bot.send_message(
            chat_id=MANAGER_CHAT_ID,
            text=f"🍽 <b>{scout_name}</b> ушёл на <b>{break_type}</b> (~1 час)",
            parse_mode="HTML",
        )

    logger.info(f"Отчёт: {scout_name} | {parsed['type']} | {address}")


async def job_check_reports():
    alerts = check_missing_reports(db, timeout_minutes=REPORT_TIMEOUT_MINUTES)
    now = datetime.now(ALMATY_TZ)
    for alert in alerts:
        sid = alert["scout_id"]
        last_alert = alert_tracker.get(sid)
        # Шлём если: первый алерт ИЛИ прошло 15+ минут с последнего
        if last_alert is None or (now - last_alert).total_seconds() / 60 >= ALERT_REPEAT_MINUTES:
            await bot.send_message(
                chat_id=MANAGER_CHAT_ID,
                text=(
                    f"⚠️ <b>Нет отчёта</b>\n"
                    f"Скаут: <b>{alert['name']}</b>\n"
                    f"Последний: {alert['last_report']}\n"
                    f"Молчит: <b>{alert['silent_minutes']} мин</b>"
                ),
                parse_mode="HTML",
            )
            alert_tracker[sid] = now


async def job_daily_report():
    text = build_daily_report(db, timeout_minutes=REPORT_TIMEOUT_MINUTES)
    await bot.send_message(chat_id=MANAGER_CHAT_ID, text=text, parse_mode="HTML")
    db.close_day()
    alert_tracker.clear()


async def main():
    db.init()

    # Команды только в чате менеджеров
    commands = [
        BotCommand(command="status", description="Статус скаутов (кто активен/молчит)"),
        BotCommand(command="report", description="Итоговый отчёт за сегодня"),
        BotCommand(command="test",   description="Проверить работу бота"),
    ]
    await bot.set_my_commands(commands, scope=BotCommandScopeChat(chat_id=int(MANAGER_CHAT_ID)))
    await bot.delete_my_commands(scope=BotCommandScopeDefault())

    scheduler.add_job(job_check_reports, "interval", minutes=5, id="check_reports")
    scheduler.add_job(job_daily_report, CronTrigger(hour=DAY_END_HOUR, minute=DAY_END_MINUTE), id="daily_report")
    scheduler.start()
    await dp.start_polling(bot, skip_updates=True)


if __name__ == "__main__":
    asyncio.run(main())
