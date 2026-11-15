"""הפילטר: מסווג כל מודעה ל-match / maybe / no, עם הסבר."""
from __future__ import annotations


def evaluate(data: dict, f: dict) -> tuple[str, list[str]]:
    """מחזיר (סטטוס, סיבות). סיבות ב-maybe = מה חסר."""
    if data.get("type") not in ("sale", None):
        return "no", ["לא מודעת מכירה"]

    missing: list[str] = []
    if data.get("type") is None:
        missing.append("לא ברור שזו מכירה")

    rooms = data.get("rooms")
    if rooms is None:
        missing.append("מס' חדרים לא צוין")
    elif not (f["rooms_min"] <= rooms <= f["rooms_max"]):
        return "no", [f"{rooms:g} חדרים"]

    price = data.get("price")
    if price is None:
        missing.append("מחיר לא צוין")
    elif price > f["price_max"]:
        return "no", [f"מחיר {price:,}"]

    if f.get("require_mamad"):
        mamad = data.get("has_mamad")
        if mamad is False:
            return "no", ['אין ממ"ד']
        if mamad is None:
            missing.append('ממ"ד לא צוין')

    cities = f.get("cities") or []
    if cities:
        city = data.get("city")
        if city is None:
            missing.append("עיר לא צוינה")
        elif not any(c in city or city in c for c in cities):
            return "no", [f"עיר: {city}"]

    if f.get("exclude_brokers") and data.get("broker") is True:
        return "no", ["תיווך"]

    return ("maybe", missing) if missing else ("match", [])
