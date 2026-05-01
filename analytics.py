"""
analytics.py
────────────
Две публичные функции:
  • check_missing_reports(db, timeout_minutes) → list[dict]  — алерты о молчащих скаутах
  • build_daily_report(db, timeout_minutes)    → str HTML    — итог дня с детальной статистикой
"""

from datetime import datetime, timezone, timedelta, date
from collections import defaultdict
import logging

logger = logging.getLogger(__name__)

REPORT_TYPE_PARKING = "парковка"
REPORT_TYPE_ORDER   = "порядок"


# ─── Алерты: скауты которые молчат ───────────────────────────────────────────

def check_missing_reports(db, timeout_minutes: int = 20) -> list[dict]:
    """
    Возвращает список скаутов у которых последний отчёт старше timeout_minutes.
    Учитываем только тех кто уже писал сегодня.
    """
    now    = datetime.now(timezone.utc)
    cutoff = now - timedelta(minutes=timeout_minutes)

    alerts = []
    for row in db.get_last_report_per_scout():
        last_ts = _parse_ts(row["ts"])
        if last_ts < cutoff:
            silent_minutes = int((now - last_ts).total_seconds() / 60)
            alerts.append({
                "scout_id":      row["scout_id"],
                "name":          row["scout_name"],
                "last_report":   last_ts.strftime("%H:%M"),
                "silent_minutes": silent_minutes,
            })
    return alerts


# ─── Итоговый отчёт за день ───────────────────────────────────────────────────

def build_daily_report(db, timeout_minutes: int = 20) -> str:
    today      = date.today().isoformat()
    all_reports = db.get_today_reports(day=today)

    if not all_reports:
        return "📋 <b>Итог дня</b>\n\nСегодня отчётов не поступало."

    # Группируем по скауту
    scouts: dict[int, dict] = {}
    for row in all_reports:
        sid = row["scout_id"]
        if sid not in scouts:
            scouts[sid] = {
                "name":           row["scout_name"],
                "times":          [],
                "parking_count":  0,   # кол-во выгрузок (тип: парковка)
                "scooters_total": 0,   # сумма самокатов из поля Итого:
                "order_count":    0,   # кол-во порядков
            }
        ts = _parse_ts(row["ts"])
        scouts[sid]["times"].append(ts)

        rtype = (row["report_type"] or "").lower()
        if rtype == REPORT_TYPE_PARKING:
            scouts[sid]["parking_count"]  += 1
            scouts[sid]["scooters_total"] += (row["scooter_count"] or 0)
        elif rtype == REPORT_TYPE_ORDER:
            scouts[sid]["order_count"] += 1

    lines = [f"📋 <b>Итог дня — {today}</b>\n"]

    # Сортируем по кол-ву выгруженных самокатов (топ сверху)
    sorted_scouts = sorted(
        scouts.items(),
        key=lambda x: x[1]["scooters_total"],
        reverse=True,
    )

    for rank, (sid, data) in enumerate(sorted_scouts, start=1):
        times = sorted(data["times"])
        name  = data["name"]
        first = times[0]
        last  = times[-1]
        total_minutes = int((last - first).total_seconds() / 60)
        hours = total_minutes // 60
        mins  = total_minutes % 60

        # Простои
        gaps = []
        for i in range(1, len(times)):
            gap_min = int((times[i] - times[i - 1]).total_seconds() / 60)
            if gap_min > timeout_minutes:
                gaps.append({
                    "from":    times[i - 1].strftime("%H:%M"),
                    "to":      times[i].strftime("%H:%M"),
                    "minutes": gap_min,
                })

        medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(rank, f"#{rank}")

        lines.append(
            f"{medal} <b>{name}</b>\n"
            f"   🕐 {first.strftime('%H:%M')} → {last.strftime('%H:%M')}  "
            f"({hours}ч {mins}мин)\n"
            f"   🛴 Выгрузок: <b>{data['parking_count']}</b>  "
            f"Самокатов: <b>{data['scooters_total']}</b>  "
            f"Порядков: <b>{data['order_count']}</b>"
        )

        if gaps:
            gap_strs = "  ".join(f"{g['from']}–{g['to']} ({g['minutes']} мин)" for g in gaps)
            lines.append(f"   ⏸ Простои: {gap_strs}")
        else:
            lines.append("   ✅ Без простоев")

        lines.append("")  # пустая строка между скаутами

    # Итоговая строка по всей команде
    total_scooters = sum(d["scooters_total"] for _, d in scouts.items())
    total_parkings = sum(d["parking_count"]  for _, d in scouts.items())
    total_orders   = sum(d["order_count"]    for _, d in scouts.items())
    lines.append(
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"👥 Скаутов: {len(scouts)}  "
        f"🛴 Всего самокатов: <b>{total_scooters}</b>  "
        f"Выгрузок: {total_parkings}  Порядков: {total_orders}"
    )

    return "\n".join(lines)


# ─── Хелпер ───────────────────────────────────────────────────────────────────

def _parse_ts(ts_str: str) -> datetime:
    dt = datetime.fromisoformat(ts_str)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt
