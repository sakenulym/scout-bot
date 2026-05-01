"""
report_parser.py — распознаёт три типа сообщений скаутов:
  1. Парковка  — выгрузка самокатов
  2. Порядок   — расстановка на парковке
  3. Обед/Ужин — перерыв (не шлём алерт пока не истечёт)
"""

import re
from typing import Optional

REPORT_TYPE_PARKING = "парковка"
REPORT_TYPE_ORDER   = "порядок"
REPORT_TYPE_BREAK   = "перерыв"  # обед или ужин


def parse_report(text: str, has_media: bool = False) -> Optional[dict]:
    if not text:
        text = ""
    text = text.strip()
    lower = text.lower()

    # Обед / ужин
    if re.search(r"\b(обед|ужин)\b", lower):
        break_type = "ужин" if "ужин" in lower else "обед"
        return {"type": REPORT_TYPE_BREAK, "break_type": break_type, "address": "—", "scooters": 0}

    # Порядок
    if re.search(r"\bпорядок\b", lower):
        address = "—"
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        for line in lines:
            if not re.match(r"порядок", line, re.IGNORECASE):
                address = line; break
        return {"type": REPORT_TYPE_ORDER, "address": address, "scooters": 0}

    # Парковка
    if re.search(r"\bпарковка\b", lower):
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        address = "—"
        for i, line in enumerate(lines):
            if re.match(r"парковка", line, re.IGNORECASE) and i + 1 < len(lines):
                nxt = lines[i + 1]
                if not re.match(r"^(s\.\d|evin|итого)", nxt, re.IGNORECASE):
                    address = nxt; break
        m = re.search(r"итого\s*:\s*(\d+)", text, re.IGNORECASE)
        return {"type": REPORT_TYPE_PARKING, "address": address, "scooters": int(m.group(1)) if m else 0}

    # Fallback: фото + "Итого: N"
    if has_media and re.search(r"итого\s*:\s*\d+", lower):
        m = re.search(r"итого\s*:\s*(\d+)", text, re.IGNORECASE)
        return {"type": REPORT_TYPE_PARKING, "address": "—", "scooters": int(m.group(1)) if m else 0}

    return None
