"""
report_parser.py
────────────────
Распознаёт два типа отчётов скаутов:

  Тип 1 — ПАРКОВКА (выгрузка самокатов):
    Парковка
    Жандосова 126

    S.258652, eVIN: 110108058164, Ninebot SL 90

    Итого: 1

  Тип 2 — ПОРЯДОК (расстановка на существующей парковке):
    [фото] + текст "Порядок"

Возвращает dict или None если не отчёт.
"""

import re
from typing import Optional


REPORT_TYPE_PARKING = "парковка"
REPORT_TYPE_ORDER   = "порядок"


def parse_report(text: str, has_media: bool = False) -> Optional[dict]:
    """
    Пытается распознать отчёт скаута.

    Параметры:
        text      — текст сообщения (или подпись к фото)
        has_media — True если к сообщению прикреплено фото

    Возвращает dict:
        {
            "type":     "парковка" | "порядок",
            "address":  str,
            "scooters": int,
            "raw_text": str,
        }
    или None если не похоже на отчёт.
    """
    if not text:
        text = ""
    text = text.strip()
    text_lower = text.lower()

    # ── Тип 2: Порядок ────────────────────────────────────────────────────────
    if re.search(r"\bпорядок\b", text_lower):
        address = _extract_address_order(text)
        return {
            "type":     REPORT_TYPE_ORDER,
            "address":  address,
            "scooters": 0,
            "raw_text": text,
        }

    # ── Тип 1: Парковка ───────────────────────────────────────────────────────
    if re.search(r"\bпарковка\b", text_lower):
        address  = _extract_address_parking(text)
        scooters = _extract_total(text)
        return {
            "type":     REPORT_TYPE_PARKING,
            "address":  address,
            "scooters": scooters,
            "raw_text": text,
        }

    # ── Fallback: фото с подписью содержащей "итого: N" ──────────────────────
    if has_media and re.search(r"итого\s*:\s*\d+", text_lower):
        address  = _extract_address_parking(text)
        scooters = _extract_total(text)
        return {
            "type":     REPORT_TYPE_PARKING,
            "address":  address,
            "scooters": scooters,
            "raw_text": text,
        }

    return None


# ── Вспомогательные функции ────────────────────────────────────────────────────

def _extract_address_parking(text: str) -> str:
    """Строка сразу после слова 'Парковка' — это адрес."""
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    for i, line in enumerate(lines):
        if re.match(r"парковка", line, re.IGNORECASE):
            if i + 1 < len(lines):
                candidate = lines[i + 1]
                if not re.match(r"(s\.\d|evin|итого)", candidate, re.IGNORECASE):
                    return candidate
    return "—"


def _extract_address_order(text: str) -> str:
    """Если есть строка кроме 'Порядок' — берём как адрес."""
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    for line in lines:
        if not re.match(r"порядок", line, re.IGNORECASE):
            return line
    return "—"


def _extract_total(text: str) -> int:
    """Извлекает число из строки вида 'Итого: 3'."""
    m = re.search(r"итого\s*:\s*(\d+)", text, re.IGNORECASE)
    return int(m.group(1)) if m else 0
