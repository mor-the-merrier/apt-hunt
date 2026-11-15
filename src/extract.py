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


class QuotaExhausted(Exception):
    """המכסה היומית של Gemini נגמרה – אין טעם לנסות שוב היום."""


def _gemini(api_key: str, model: str, posts: list[dict]) -> list[dict]:
    body = "\n\n".join(f"### פוסט {i}\n{p['text'][:2500]}" for i, p in enumerate(posts))
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    payload = {
        "contents": [{"parts": [{"text": PROMPT + body}]}],
        "generationConfig": {"responseMimeType": "application/json", "temperature": 0},
    }
    for attempt in range(3):
        r = requests.post(url, headers={"x-goog-api-key": api_key}, json=payload, timeout=180)
        if r.status_code == 429:
            if "PerDay" in r.text or "per day" in r.text.lower():
                raise QuotaExhausted(r.text[:300])
            print(f"[extract] rate limited (per-minute), waiting – attempt {attempt + 1}", flush=True)
            time.sleep(30 * (attempt + 1))
            continue
        if r.status_code >= 500:
            time.sleep(10)
            continue
        if not r.ok:
            raise RuntimeError(f"Gemini {r.status_code}: {r.text[:300]}")
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


def price_candidates(text: str) -> list[int]:
    t = text.replace("₪", ' ש"ח ')
    candidates = []
    for m in re.finditer(_NUM + r"\s*(?:מיליון|מליון|מלי['׳]|M\b|m\b)", t):
        candidates.append(int(_to_float(m.group(1)) * 1_000_000))
    # 2,650,000 / 2650000 – בלי לתפוס מספרי טלפון (05x-xxxxxxx)
    for m in re.finditer(r"(?<![\d\-])(\d{1,2}[,.]\d{3}[,.]\d{3}|\d{7})(?![\d\-])", t):
        candidates.append(int(re.sub(r"\D", "", m.group(1))))
    for m in re.finditer(r"(?<!\d)(\d{3,4})\s*(?:אלף|א['׳]|K\b)", t):
        candidates.append(int(m.group(1)) * 1000)
    return [p for p in candidates if 300_000 <= p <= 30_000_000]


def parse_price(text: str) -> int | None:
    c = price_candidates(text)
    return c[0] if c else None


def rooms_candidates(text: str) -> list[float]:
    out = [_to_float(m.group(1)) for m in re.finditer(_NUM + r"\s*(?:חדרים|חדר|חד['׳\"״]?)(?!\s*(?:רחצה|שינה|שירותים))", text)]
    out += [_to_float(m.group(1)) for m in re.finditer(r"דירת\s*" + _NUM + r"(?!\s*(?:מ\"ר|מטר|קומ))", text)]
    return [r for r in out if 1 <= r <= 12]


# ---------- מיקום ----------

CITIES = {
    "כפר סבא": ["כפר סבא", "כפר-סבא", 'כ"ס', "כ״ס"], "רעננה": ["רעננה"], "הוד השרון": ["הוד השרון", 'הוד"ש'],
    "הרצליה": ["הרצליה"], "רמת השרון": ["רמת השרון"], "נתניה": ["נתניה"], "פתח תקווה": ["פתח תקווה", "פתח תקוה", 'פ"ת', "פ״ת"],
    "ראש העין": ["ראש העין"], "כוכב יאיר": ["כוכב יאיר", "צור יגאל"], "תל אביב": ["תל אביב", 'ת"א', "ת״א", "תל-אביב"],
    "רמת גן": ["רמת גן", 'ר"ג', "ר״ג"], "גבעתיים": ["גבעתיים"], "ראשון לציון": ["ראשון לציון", 'ראשל"צ', "ראשל״צ"],
    "חולון": ["חולון"], "בת ים": ["בת ים"], "רחובות": ["רחובות"], "נס ציונה": ["נס ציונה"], "מודיעין": ["מודיעין"],
    "ירושלים": ["ירושלים"], "חיפה": ["חיפה"], "באר שבע": ["באר שבע"], "אשדוד": ["אשדוד"], "אשקלון": ["אשקלון"],
    "בני ברק": ["בני ברק"], "גבעת שמואל": ["גבעת שמואל"], "קריית אונו": ["קריית אונו", "קרית אונו"], "יהוד": ["יהוד"],
    "אור יהודה": ["אור יהודה"], "לוד": ["לוד"], "רמלה": ["רמלה"], "טייבה": ["טייבה"], "קדימה": ["קדימה", "קדימה צורן"],
    "אבן יהודה": ["אבן יהודה"], "צור יצחק": ["צור יצחק"], "אלפי מנשה": ["אלפי מנשה"], "שוהם": ["שוהם"], "יבנה": ["יבנה"],
}
_STOP = {"עם", "קומה", "דירה", "דירת", "למכירה", "מחיר", "במחיר", "חדרים", "ליד", "קרוב", "מול", "יש", "של",
         "מוכרים", "מוכר", "בבניין", "בניין", "בית", "פרטי", "ללא", "בלי", "גדולה", "משופצת", "מרווחת", "חדשה"}
_WORD = r"[א-ת][א-ת'׳\"״\-]*"


def _city_aliases():
    for city, aliases in CITIES.items():
        for a in aliases:
            yield city, a


def _take_words(rest: str, max_words: int) -> str | None:
    words = []
    for w in rest.split():
        w = w.strip(",.!:;()")
        if not re.fullmatch(_WORD, w) or w in _STOP or any(w == a.split()[0] or w == "ב" + a.split()[0]
                                                          for _, a in _city_aliases()):
            break
        words.append(w)
        if len(words) == max_words or re.search(r"[,.!\n]", rest.split(w, 1)[1][:1] or ""):
            break
    return " ".join(words) or None


def parse_location(text: str) -> tuple[str | None, str | None, str | None]:
    city = None
    for name, alias in _city_aliases():
        if re.search(r"(?<![א-ת])[בלמ]?" + re.escape(alias) + r"(?![א-ת])", text):
            city = name
            break
    hood = None
    m = re.search(r"(?:שכונת|שכ['׳])\s*([^\n]{0,40})", text)
    if m:
        hood = _take_words(m.group(1), 2)
    elif re.search(r"במרכז\s+(?:ה?עיר|" + "|".join(re.escape(a) for _, a in _city_aliases()) + ")", text):
        hood = "מרכז"
    street = None
    m = re.search(r"(?:ברחוב|רחוב|ברח['׳]|רח['׳])\s*([^\n]{0,40})", text)
    if m:
        street = _take_words(m.group(1), 2)
    return city, hood, street


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
    city, hood, street = parse_location(t)
    return {
        "type": kind, "city": city, "neighborhood": hood, "street": street,
        "rooms": (rooms_candidates(t) or [None])[0], "size_sqm": int(m_size.group(1)) if m_size else None,
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


def could_match(text: str, f: dict) -> bool:
    """סינון מקדים זהיר ב-regex: פוסל רק כשברור שהמודעה לא מתאימה.

    כך רק מועמדים אמיתיים נשלחים ל-Gemini, וחוסכים במכסה. במקרה של ספק – לא פוסל.
    """
    d = regex_extract(text)
    if d["type"] in ("rent", "wanted"):
        return False
    if f.get("require_mamad") and d["has_mamad"] is False:
        return False
    rooms = rooms_candidates(text)
    if rooms and not any(f["rooms_min"] <= r <= f["rooms_max"] for r in rooms):
        return False
    prices = price_candidates(text)
    if prices and min(prices) > f["price_max"]:
        return False
    return True


def extract_all(posts: list[dict], api_key: str | None, model: str, batch_size: int = 20) -> None:
    """ממלא post['data'] לכל פוסט. אם אין מפתח או שהמודל נכשל – regex."""
    for start in range(0, len(posts), batch_size):
        batch = posts[start:start + batch_size]
        print(f"[extract] posts {start + 1}-{start + len(batch)} of {len(posts)}", flush=True)
        results = None
        if api_key:
            try:
                results = _gemini(api_key, model, batch)
            except QuotaExhausted as e:
                print(f"[extract] Gemini daily quota exhausted – regex for the rest: {e}", flush=True)
                api_key = None
            except Exception as e:  # noqa: BLE001
                print(f"[extract] Gemini failed, using regex: {e}", flush=True)
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
            time.sleep(8)  # נשארים בתוך מגבלת הבקשות לדקה
