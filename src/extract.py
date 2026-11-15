"""חילוץ שדות מובנים מטקסט חופשי של מודעה: Gemini, עם גיבוי של regex."""
from __future__ import annotations

import json
import re
import time

import requests

FIELDS = ["type", "city", "neighborhood", "street", "rooms", "size_sqm", "floor",
          "price", "has_mamad", "parking", "elevator", "broker", "summary"]

PROMPT = """אתה מנתח מודעות נדל"ן מקבוצות פייסבוק בישראל.
לכל פוסט ברשימה החזר אובייקט JSON עם השדות הבאים (null אם לא מצוין במפורש):
- "idx": המספר של הפוסט ברשימה
- "type": אחד מ- "sale" (מכירת דירה), "rent" (השכרה), "wanted" (מחפשים דירה), "other"
- "city", "neighborhood", "street": מחרוזות בעברית
- "rooms": מספר (למשל 3.5)
- "size_sqm": מספר שלם
- "floor": מספר שלם
- "price": מחיר בש"ח כמספר שלם מלא (2.65 מיליון -> 2650000)
- "has_mamad": true אם יש ממ"ד/מרחב מוגן, false אם כתוב במפורש שאין, אחרת null
- "parking", "elevator": true/false/null
- "broker": true אם המפרסם מתווך/משרד תיווך, false אם כתוב "ללא תיווך"/"מבעלים", אחרת null
- "summary": תיאור קצר בעברית, עד 12 מילים

החזר מערך JSON בלבד, באותו סדר.

הפוסטים:
"""


def _gemini(api_key: str, model: str, posts: list[dict]) -> list[dict]:
    body = "\n\n".join(f"### פוסט {i}\n{p['text'][:2500]}" for i, p in enumerate(posts))
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    payload = {
        "contents": [{"parts": [{"text": PROMPT + body}]}],
        "generationConfig": {"responseMimeType": "application/json", "temperature": 0},
    }
    for attempt in range(4):
        r = requests.post(url, headers={"x-goog-api-key": api_key}, json=payload, timeout=120)
        if r.status_code == 429 or r.status_code >= 500:  # מגבלת קצב – מחכים ומנסים שוב
            time.sleep(20 * (attempt + 1))
            continue
        r.raise_for_status()
        text = r.json()["candidates"][0]["content"]["parts"][0]["text"]
        data = json.loads(text)
        return data if isinstance(data, list) else data.get("posts", [])
    raise RuntimeError("Gemini rate limit – giving up on this batch")


# ---------- גיבוי: regex ----------

_NUM = r"(\d+(?:[.,]\d+)?)"
_MAMAD = re.compile(r'ממ["״\']?ד|מרחב\s*מוגן')
_NO_MAMAD = re.compile(r'(אין|ללא|בלי)\s*(ממ["״\']?ד|מרחב\s*מוגן)')


def _to_float(s: str) -> float:
    return float(s.replace(",", "."))


def parse_price(text: str) -> int | None:
    t = text.replace("₪", ' ש"ח ')
    candidates = []
    for m in re.finditer(_NUM + r"\s*(?:מיליון|מליון|מלי['׳]|M\b|m\b)", t):
        candidates.append(int(_to_float(m.group(1)) * 1_000_000))
    # 2,650,000 / 2650000 – בלי לתפוס מספרי טלפון (05x-xxxxxxx)
    for m in re.finditer(r"(?<![\d\-])(\d{1,2}[,.]\d{3}[,.]\d{3}|\d{7})(?![\d\-])", t):
        candidates.append(int(re.sub(r"\D", "", m.group(1))))
    for m in re.finditer(r"(?<!\d)(\d{3,4})\s*(?:אלף|א['׳]|K\b)", t):
        candidates.append(int(m.group(1)) * 1000)
    valid = [p for p in candidates if 300_000 <= p <= 30_000_000]
    return valid[0] if valid else None


def parse_rooms(text: str) -> float | None:
    m = re.search(_NUM + r"\s*(?:חדרים|חדר|חד['׳\"״]?)", text)
    if m:
        return _to_float(m.group(1))
    m = re.search(r"דירת\s*" + _NUM + r"(?!\s*(?:מ\"ר|מטר|קומ))", text)
    return _to_float(m.group(1)) if m else None


def regex_extract(text: str) -> dict:
    t = text
    if re.search(r"להשכרה|שכירות|לשכירות", t):
        kind = "rent"
    elif re.search(r"מחפש|מחפשים|דרושה|דרוש", t) and not re.search(r"למכירה|מוכר", t):
        kind = "wanted"
    elif re.search(r"למכירה|מוכר|מוכרים|נמכרת|מכירה", t):
        kind = "sale"
    else:
        kind = None
    if _NO_MAMAD.search(t):
        mamad = False
    elif _MAMAD.search(t):
        mamad = True
    else:
        mamad = None
    m_size = re.search(r"(\d{2,3})\s*(?:מ\"ר|מ״ר|מטר|מ'ר)", t)
    m_floor = re.search(r"קומה\s*(\d{1,2})", t)
    broker = True if re.search(r"תיווך|מתווך|משרד\s*נדל", t) else None
    if re.search(r"(ללא|בלי)\s*(תיווך|מתווכים)|מבעלים|מהבעלים", t):
        broker = False
    return {
        "type": kind, "city": None, "neighborhood": None, "street": None,
        "rooms": parse_rooms(t), "size_sqm": int(m_size.group(1)) if m_size else None,
        "floor": int(m_floor.group(1)) if m_floor else None, "price": parse_price(t),
        "has_mamad": mamad, "parking": True if "חניה" in t or "חנייה" in t else None,
        "elevator": True if "מעלית" in t else None, "broker": broker,
        "summary": t.splitlines()[0][:80],
    }


def _sanitize(d: dict) -> dict:
    out = {k: d.get(k) for k in FIELDS}
    p = out.get("price")
    if isinstance(p, (int, float)) and p:
        if p < 100:          # נכתב במיליונים
            p *= 1_000_000
        elif p < 100_000:    # נכתב באלפים
            p *= 1000
        out["price"] = int(p)
    for k in ("rooms",):
        if isinstance(out.get(k), str):
            try:
                out[k] = _to_float(out[k])
            except ValueError:
                out[k] = None
    return out


def extract_all(posts: list[dict], api_key: str | None, model: str, batch_size: int = 10) -> None:
    """ממלא post['data'] לכל פוסט. אם אין מפתח או שהמודל נכשל – regex."""
    for start in range(0, len(posts), batch_size):
        batch = posts[start:start + batch_size]
        results = None
        if api_key:
            try:
                results = _gemini(api_key, model, batch)
            except Exception as e:  # noqa: BLE001
                print(f"[extract] Gemini failed, using regex: {e}")
        by_idx = {r.get("idx", i): r for i, r in enumerate(results or [])}
        for i, post in enumerate(batch):
            fallback = regex_extract(post["text"])
            llm = by_idx.get(i)
            if llm:
                data = _sanitize(llm)
                for k, v in fallback.items():  # השלמת חורים מה-regex
                    if data.get(k) is None and k != "summary":
                        data[k] = v
                post["data"] = data
                post["source"] = "llm"
            else:
                post["data"] = _sanitize(fallback)
                post["source"] = "regex"
        if api_key and start + batch_size < len(posts):
            time.sleep(5)  # נשארים בתוך מגבלת הבקשות לדקה
