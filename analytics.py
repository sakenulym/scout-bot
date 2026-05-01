from datetime import datetime, timezone, timedelta, date
import logging

logger = logging.getLogger(__name__)

REPORT_TYPE_PARKING = "парковка"
REPORT_TYPE_ORDER   = "порядок"
REPORT_TYPE_BREAK   = "перерыв"
ALMATY_TZ = timezone(timedelta(hours=5))
BREAK_DURATION_MINUTES = 60


def _parse_ts(ts_str: str) -> datetime:
    dt = datetime.fromisoformat(ts_str)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(ALMATY_TZ)


def _is_on_break(last_row) -> tuple[bool, str]:
    if (last_row["report_type"] or "").lower() == REPORT_TYPE_BREAK:
        last_ts = _parse_ts(last_row["ts"])
        now = datetime.now(ALMATY_TZ)
        elapsed = (now - last_ts).total_seconds() / 60
        if elapsed < BREAK_DURATION_MINUTES:
            return True, last_row.get("address", "обед")
    return False, ""


def _fmt_mins(minutes: int) -> str:
    """Форматирует минуты в '1ч 25мин' или '45мин'."""
    if minutes <= 0:
        return "0мин"
    h = minutes // 60
    m = minutes % 60
    if h > 0 and m > 0:
        return f"{h}ч {m}мин"
    elif h > 0:
        return f"{h}ч"
    else:
        return f"{m}мин"


def check_missing_reports(db, timeout_minutes: int = 20) -> list[dict]:
    now    = datetime.now(ALMATY_TZ)
    cutoff = now - timedelta(minutes=timeout_minutes)
    alerts = []
    for row in db.get_last_report_per_scout():
        on_break, _ = _is_on_break(row)
        if on_break:
            continue
        last_ts = _parse_ts(row["ts"])
        if last_ts < cutoff:
            silent_minutes = int((now - last_ts).total_seconds() / 60)
            alerts.append({
                "scout_id":       row["scout_id"],
                "name":           row["scout_name"],
                "last_report":    last_ts.strftime("%H:%M"),
                "silent_minutes": silent_minutes,
            })
    return alerts


def build_daily_report(db, timeout_minutes: int = 20) -> str:
    now   = datetime.now(ALMATY_TZ)
    today = now.strftime("%Y-%m-%d")
    all_reports = db.get_today_reports(day=today)

    if not all_reports:
        return "📋 <b>Итог дня</b>\n\nСегодня отчётов не поступало."

    scouts: dict[int, dict] = {}
    for row in all_reports:
        sid = row["scout_id"]
        if sid not in scouts:
            scouts[sid] = {
                "name":           row["scout_name"],
                "events":         [],  # список (ts, report_type)
                "parking_count":  0,
                "scooters_total": 0,
                "order_count":    0,
                "last_row":       None,
            }
        ts = _parse_ts(row["ts"])
        rtype = (row["report_type"] or "").lower()
        scouts[sid]["events"].append((ts, rtype))
        scouts[sid]["last_row"] = row
        if rtype == REPORT_TYPE_PARKING:
            scouts[sid]["parking_count"]  += 1
            scouts[sid]["scooters_total"] += (row["scooter_count"] or 0)
        elif rtype == REPORT_TYPE_ORDER:
            scouts[sid]["order_count"] += 1

    sorted_scouts = sorted(scouts.items(), key=lambda x: x[1]["scooters_total"], reverse=True)
    medals = {1: "🥇", 2: "🥈", 3: "🥉"}
    lines = [f"📋 <b>Итог дня — {today}</b>\n"]

    for rank, (sid, data) in enumerate(sorted_scouts, start=1):
        events = sorted(data["events"], key=lambda x: x[0])
        times  = [e[0] for e in events]
        first, last = times[0], times[-1]

        # Общее время смены (от первого до последнего отчёта)
        total_shift_min = int((last - first).total_seconds() / 60)

        # Считаем время перерывов и простоев
        break_min   = 0
        downtime_min = 0
        gap_details  = []  # для отображения простоев

        for i in range(1, len(events)):
            gap_start_ts, prev_type = events[i - 1]
            gap_end_ts,   curr_type = events[i]
            gap_min = int((gap_end_ts - gap_start_ts).total_seconds() / 60)

            if gap_min <= 0:
                continue

            if prev_type == REPORT_TYPE_BREAK:
                # Время после "обед/ужин" до следующего отчёта = перерыв
                actual_break = min(gap_min, BREAK_DURATION_MINUTES)
                break_min += actual_break
                leftover = gap_min - actual_break
                if leftover > timeout_minutes:
                    downtime_min += leftover
                    gap_details.append(
                        f"{gap_start_ts.strftime('%H:%M')}–{gap_end_ts.strftime('%H:%M')} "
                        f"(перерыв + {_fmt_mins(leftover)} простой)"
                    )
            elif gap_min > timeout_minutes:
                downtime_min += gap_min
                gap_details.append(
                    f"{gap_start_ts.strftime('%H:%M')}–{gap_end_ts.strftime('%H:%M')} "
                    f"({_fmt_mins(gap_min)})"
                )

        # Чистое рабочее время = смена - перерывы - простои
        work_min = max(0, total_shift_min - break_min - downtime_min)

        on_break, break_type = _is_on_break(data["last_row"])
        break_label = f"  🍽 На {break_type}" if on_break else ""

        medal = medals.get(rank, f"#{rank}")
        lines.append(
            f"{medal} <b>{data['name']}</b>{break_label}\n"
            f"   🕐 {first.strftime('%H:%M')} → {last.strftime('%H:%M')}\n"
            f"   ⏱ Смена: <b>{_fmt_mins(total_shift_min)}</b>  "
            f"Работа: <b>{_fmt_mins(work_min)}</b>  "
            f"Перерыв: {_fmt_mins(break_min)}  "
            f"Простой: {_fmt_mins(downtime_min)}\n"
            f"   🛴 Выгрузок: <b>{data['parking_count']}</b>  "
            f"Самокатов: <b>{data['scooters_total']}</b>  "
            f"Порядков: <b>{data['order_count']}</b>"
        )

        if gap_details:
            lines.append(f"   ⏸ Простои: {' | '.join(gap_details)}")
        else:
            lines.append("   ✅ Без простоев")

        lines.append("")

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
