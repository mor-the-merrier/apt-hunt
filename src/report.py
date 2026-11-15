"""שליחה לטלגרם: הודעת טקסט קצרה + קובץ ה-HTML."""
from __future__ import annotations

import html

import requests



def _e(s) -> str:
    return html.escape(str(s)) if s is not None else ""


def _price(p) -> str:
    if not p:
        return "מחיר ?"
    return f"{p / 1_000_000:.2f}".rstrip("0").rstrip(".") + "M ₪"


def _link(p: dict, label: str = "לפוסט") -> str:
    return f'<a href="{_e(p["url"])}">{label}</a>' if p.get("url") else ""


def send_telegram(token: str, chat_id: str, messages: list[str]) -> None:
    for m in messages:
        r = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": m, "parse_mode": "HTML",
                  "disable_web_page_preview": True},
            timeout=30,
        )
        if not r.ok:
            raise RuntimeError(f"Telegram error {r.status_code}: {r.text}")


def short_summary(date_str: str, stats: dict, matches, maybes) -> str:
    """הודעת טקסט קצרה שמלווה את קובץ ה-HTML."""
    lines = [f"🏠 <b>דירות לפי הפילטר – {date_str}</b>",
             f"נסרקו {stats['unique']} פוסטים חדשים",
             f"⭐ {len(matches)} מתאימות | 🤔 {len(maybes)} אולי (חסר מידע)"]
    for p in matches[:5]:
        d = p["data"]
        rooms = f'{d["rooms"]:g} חד\'' if d.get("rooms") else "? חד'"
        loc = d.get("city") or d.get("neighborhood") or ""
        lines.append(" | ".join(x for x in (f"• {rooms} {_e(loc)}".strip(), _price(d.get("price")), _link(p)) if x))
    lines.append("\nהדוח המלא בקובץ המצורף 👇")
    return "\n".join(lines)


def send_document(token: str, chat_id: str, filename: str, content: str, caption: str = "") -> None:
    r = requests.post(
        f"https://api.telegram.org/bot{token}/sendDocument",
        data={"chat_id": chat_id, "caption": caption},
        files={"document": (filename, content.encode("utf-8"), "text/html")},
        timeout=60,
    )
    if not r.ok:
        raise RuntimeError(f"Telegram error {r.status_code}: {r.text}")
