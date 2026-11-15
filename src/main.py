"""סוכן יומי: איסוף → ניקוי כפילויות → חילוץ → פילטר → סיכום לטלגרם.

הרצה:
  python src/main.py                         # ריצה מלאה (ב-GitHub Actions)
  python src/main.py --input samples/sample_posts.json --dry-run --no-llm
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

sys.path.insert(0, str(Path(__file__).parent))
from collect import normalize, run_actor  # noqa: E402
from extract import could_match, extract_all  # noqa: E402
from filters import evaluate  # noqa: E402
from html_report import build_html  # noqa: E402
from report import send_document, send_telegram, short_summary  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
STATE = ROOT / "state" / "seen.json"
KEEP_DAYS = 45


def fingerprint(text: str) -> str:
    """טביעת אצבע לטקסט – לזיהוי אותה מודעה שפורסמה בכמה קבוצות."""
    t = re.sub(r"[^\w]", "", text.lower())[:300]
    return hashlib.sha1(t.encode()).hexdigest()[:16]


def load_state() -> dict:
    if STATE.exists():
        return json.loads(STATE.read_text(encoding="utf-8"))
    return {"ids": {}, "fps": {}}


def save_state(state: dict, today: str) -> None:
    cutoff = (datetime.fromisoformat(today) - timedelta(days=KEEP_DAYS)).date().isoformat()
    for key in ("ids", "fps"):
        state[key] = {k: v for k, v in state[key].items() if v >= cutoff}
    STATE.parent.mkdir(exist_ok=True)
    STATE.write_text(json.dumps(state, ensure_ascii=False, indent=0), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=str(ROOT / "config.yaml"))
    ap.add_argument("--input", help="קובץ JSON של פוסטים גולמיים במקום Apify (לבדיקות)")
    ap.add_argument("--dry-run", action="store_true", help="הדפסה במקום שליחה, בלי לעדכן state")
    ap.add_argument("--no-llm", action="store_true", help="חילוץ ב-regex בלבד")
    args = ap.parse_args()

    cfg = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))
    groups = []
    for g in cfg.get("groups") or []:
        if isinstance(g, (int, str)):  # אפשר לרשום רק ID או קישור
            g = {"id": g} if str(g).isdigit() else {"url": g}
        if not g.get("url") and g.get("id"):
            g["url"] = f"https://www.facebook.com/groups/{g['id']}"
        if g.get("url") and "REPLACE_ME" not in g["url"]:
            g.setdefault("name", "")
            groups.append(g)
    tz = ZoneInfo(cfg["report"].get("timezone", "Asia/Jerusalem"))
    now = datetime.now(tz)
    today = now.date().isoformat()
    tg_token, tg_chat = os.getenv("TELEGRAM_BOT_TOKEN"), os.getenv("TELEGRAM_CHAT_ID")
    warnings: list[str] = []

    def notify_error(msg: str) -> None:
        print(msg, file=sys.stderr)
        if tg_token and tg_chat and not args.dry_run:
            send_telegram(tg_token, tg_chat, [f"❗ סוכן הדירות נכשל: {msg}"])

    # 1. איסוף
    try:
        if args.input:
            raw = json.loads(Path(args.input).read_text(encoding="utf-8"))
        else:
            if not groups:
                notify_error("לא הוגדרו קבוצות ב-config.yaml")
                return 1
            raw = run_actor(os.environ["APIFY_TOKEN"], cfg, groups)
    except Exception as e:  # noqa: BLE001
        notify_error(f"שגיאה באיסוף מ-Apify: {e}")
        return 1
    posts = [p for p in (normalize(i, groups) for i in raw) if p]

    # 2. כפילויות: מול ריצות קודמות ובין קבוצות
    state = load_state()
    unique: dict[str, dict] = {}
    for p in posts:
        fp = fingerprint(p["text"])
        if p["id"] in state["ids"]:
            continue
        if fp in unique:  # אותה מודעה בכמה קבוצות היום
            first = unique[fp]
            if p["group"] and p["group"] != first["group"]:
                first.setdefault("also_in", []).append(p["group"])
            continue
        if fp in state["fps"]:  # פורסמה מחדש (bump) – כבר דווחה
            state["ids"][p["id"]] = today
            continue
        p["fp"] = fp
        unique[fp] = p
    new_posts = list(unique.values())

    # 3. סינון מקדים (regex) – רק מועמדים אמיתיים נשלחים ל-Gemini
    candidates = [p for p in new_posts if could_match(p["text"], cfg["filter"])]
    print(f"[filter] {len(candidates)} candidates out of {len(new_posts)} new posts", flush=True)

    # 4. חילוץ
    api_key = None if args.no_llm else os.getenv("GEMINI_API_KEY")
    if not args.no_llm and not api_key:
        warnings.append("אין GEMINI_API_KEY – חילוץ בסיסי בלבד")
    extract_all(candidates, api_key, cfg["extractor"]["model"], cfg["extractor"].get("batch_size", 20))
    n_regex = sum(p.get("source") == "regex" for p in candidates)
    if n_regex and api_key:
        warnings.append(f"{n_regex} פוסטים נותחו בחילוץ בסיסי (Gemini לא היה זמין)")

    # 5. פילטר
    matches, maybes = [], []
    for p in candidates:
        status, reasons = evaluate(p["data"], cfg["filter"])
        p["status"], p["reasons"] = status, reasons
        if status == "match":
            matches.append(p)
        elif status == "maybe":
            maybes.append(p)
    key = lambda p: p["data"].get("price") or 10**9  # noqa: E731
    matches.sort(key=key)
    maybes.sort(key=key)

    # 6. דוח HTML + הודעה קצרה
    f = cfg["filter"]
    filter_desc = (f"{f['rooms_min']:g}–{f['rooms_max']:g} חדרים · עד {f['price_max']:,} ₪"
                   + (' · ממ"ד חובה' if f.get("require_mamad") else "")
                   + (f" · ערים: {', '.join(f['cities'])}" if f.get("cities") else ""))
    stats = {"groups": len(groups) or "?", "raw": len(posts), "unique": len(new_posts),
             "warnings": warnings}
    date_str = now.strftime("%d/%m/%Y")
    page = build_html(date_str, stats, matches, maybes, tz, filter_desc)
    out = ROOT / "out" / f"apartments-{today}.html"
    out.parent.mkdir(exist_ok=True)
    out.write_text(page, encoding="utf-8")
    text = short_summary(date_str, stats, matches, maybes)

    if args.dry_run:
        print(text)
        print(f"\n[dry-run] HTML saved to {out}")
        return 0
    send_telegram(tg_token, tg_chat, [text])
    send_document(tg_token, tg_chat, out.name, page)

    for p in posts:
        state["ids"][p["id"]] = today
    for p in new_posts:
        state["fps"][p["fp"]] = today
    save_state(state, today)
    return 0


if __name__ == "__main__":
    sys.exit(main())
