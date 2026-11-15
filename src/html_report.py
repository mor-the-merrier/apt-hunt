"""דוח HTML עצמאי (קובץ אחד, בלי תלויות) עם תוצאות הפילטר: מתאימים + אולי מתאימים."""
from __future__ import annotations

import html
from datetime import datetime
from urllib.parse import quote
from zoneinfo import ZoneInfo

TYPE_LABEL = {"sale": "מכירה", "rent": "השכרה", None: "לא ברור"}
STATUS_LABEL = {"match": ("מתאים", "ok"), "maybe": ("אולי", "maybe")}


def _e(s) -> str:
    return html.escape(str(s)) if s is not None else ""


def _price(d: dict) -> str:
    p = d.get("price")
    if not p:
        return "מחיר לא צוין"
    if d.get("type") == "rent" or p < 100_000:
        return f"{p:,} ₪ לחודש"
    return f"{p / 1_000_000:.2f}".rstrip("0").rstrip(".") + " מיליון ₪"


def _time(t, tz: ZoneInfo) -> str:
    if not t:
        return ""
    try:
        if isinstance(t, (int, float)):
            dt = datetime.fromtimestamp(t / 1000 if t > 1e11 else t, tz)
        else:
            dt = datetime.fromisoformat(str(t).replace("Z", "+00:00")).astimezone(tz)
        return dt.strftime("%d/%m %H:%M")
    except (ValueError, OSError):
        return ""


def _yesno(v, label: str) -> str:
    if v is True:
        return f'<span class="chip yes">✓ {label}</span>'
    if v is False:
        return f'<span class="chip no">✗ {label}</span>'
    return f'<span class="chip unk">? {label}</span>'


def _card(p: dict, tz: ZoneInfo, show_reasons: bool = False) -> str:
    d = p["data"]
    rooms = f'{d["rooms"]:g} חדרים' if d.get("rooms") else "חדרים ?"
    loc = ", ".join(_e(x) for x in (d.get("street"), d.get("neighborhood"), d.get("city")) if x) or "מיקום לא צוין"
    badges = [f'<span class="badge type-{d.get("type") or "unk"}">{TYPE_LABEL.get(d.get("type"), "אחר")}</span>']
    if p.get("status") in STATUS_LABEL:
        label, cls = STATUS_LABEL[p["status"]]
        badges.append(f'<span class="badge {cls}">{label}</span>')
    if d.get("broker") is True:
        badges.append('<span class="badge muted">תיווך</span>')
    elif d.get("broker") is False:
        badges.append('<span class="badge muted">פרטי</span>')

    facts = []
    if d.get("size_sqm"):
        facts.append(f'{d["size_sqm"]} מ"ר')
    if d.get("floor") is not None:
        facts.append(f'קומה {d["floor"]}')
    chips = _yesno(d.get("has_mamad"), 'ממ"ד')
    if d.get("parking"):
        chips += _yesno(True, "חניה")
    if d.get("elevator"):
        chips += _yesno(True, "מעלית")

    reasons = ""
    if show_reasons and p.get("reasons"):
        reasons = f'<div class="reasons">⚠️ {_e(", ".join(p["reasons"]))}</div>'
    also = f' · גם ב: {_e(", ".join(p["also_in"]))}' if p.get("also_in") else ""
    link = ""
    if p.get("url"):
        # fb:// פותח את אפליקציית פייסבוק; הקישור הרגיל נשאר כגיבוי למחשב / אם אין אפליקציה
        app = "fb://facewebmodal/f?href=" + quote(p["url"], safe="")
        link = (f'<span class="links"><a class="btn" href="{_e(app)}">פתח באפליקציה</a>'
                f'<a class="btn alt" href="{_e(p["url"])}" target="_blank" rel="noopener">בדפדפן</a></span>')
    summary = f'<p class="summary">{_e(d["summary"])}</p>' if d.get("summary") and p.get("source") == "llm" else ""

    return f"""
<article class="card">
  <div class="top">
    <div class="price">{_price(d)}</div>
    <div class="badges">{''.join(badges)}</div>
  </div>
  <div class="main">{rooms} · {loc}</div>
  <div class="facts">{' · '.join(facts)}</div>
  <div class="chips">{chips}</div>
  {summary}{reasons}
  <details><summary>טקסט המודעה המקורי</summary><p class="orig">{_e(p["text"])}</p></details>
  <div class="meta"><span>{_e(p.get("group"))}{also} · {_time(p.get("time"), tz)}</span>{link}</div>
</article>"""


def _section(title: str, posts: list[dict], tz, empty: str, reasons=False) -> str:
    body = "".join(_card(p, tz, reasons) for p in posts) if posts else f'<p class="empty">{empty}</p>'
    return f'<h2>{title} <span class="count">{len(posts)}</span></h2>{body}'


def build_html(date_str: str, stats: dict, matches, maybes, tz: ZoneInfo, filter_desc: str) -> str:
    body = (_section("מתאימים", matches, tz, "אין היום מודעות שעומדות בכל הקריטריונים.")
            + _section("אולי מתאימים – חסר מידע", maybes, tz, "אין.", reasons=True))
    warn = f'<p class="note">⚙️ {_e(" | ".join(stats["warnings"]))}</p>' if stats.get("warnings") else ""

    return f"""<!DOCTYPE html>
<html lang="he" dir="rtl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>דירות לפי הפילטר – {date_str}</title>
<style>
  :root {{ --bg:#f5f6f8; --card:#fff; --text:#1d2330; --muted:#6b7385; --line:#e3e6ec;
          --accent:#2457d6; --ok:#1b8a4b; --okbg:#e5f5ec; --maybe:#a26100; --maybebg:#fdf1dc; }}
  @media (prefers-color-scheme: dark) {{
    :root {{ --bg:#14161b; --card:#1e2128; --text:#e8eaf0; --muted:#9aa1b2; --line:#2e323c;
            --accent:#7aa2ff; --okbg:#173326; --ok:#5fd394; --maybebg:#3a2c12; --maybe:#f0b45a; }} }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; background:var(--bg); color:var(--text);
         font:15px/1.5 -apple-system, "Segoe UI", Arial, "Noto Sans Hebrew", sans-serif; }}
  .wrap {{ max-width:760px; margin:0 auto; padding:16px 14px 40px; }}
  header h1 {{ font-size:20px; margin:4px 0; }}
  .stats {{ color:var(--muted); font-size:13px; }}
  .filter {{ display:inline-block; margin:14px 0 0; padding:6px 12px; border-radius:20px;
             background:var(--card); border:1px solid var(--line); font-size:13px; }}
  h2 {{ font-size:16px; margin:18px 0 8px; }}
  .count {{ background:var(--line); border-radius:20px; padding:0 8px; font-size:13px; }}
  .card {{ background:var(--card); border:1px solid var(--line); border-radius:12px;
          padding:12px 14px; margin-bottom:10px; }}
  .top {{ display:flex; justify-content:space-between; align-items:center; gap:8px; flex-wrap:wrap; }}
  .price {{ font-size:18px; font-weight:700; }}
  .main {{ font-weight:600; margin-top:2px; }}
  .facts, .meta, .note {{ color:var(--muted); font-size:13px; }}
  .badge {{ font-size:12px; padding:2px 8px; border-radius:20px; margin-inline-start:4px;
           background:var(--line); }}
  .badge.ok {{ background:var(--okbg); color:var(--ok); }}
  .badge.maybe {{ background:var(--maybebg); color:var(--maybe); }}
  .badge.type-rent {{ background:#e8e3fb; color:#5a3fc0; }}
  .chips {{ margin:6px 0 2px; }}
  .chip {{ font-size:12px; margin-inline-end:8px; }}
  .chip.yes {{ color:var(--ok); }} .chip.no {{ color:#c0392b; }} .chip.unk {{ color:var(--muted); }}
  .summary {{ margin:6px 0 0; }}
  .reasons {{ margin-top:6px; color:var(--maybe); font-size:13px; }}
  details {{ margin-top:6px; font-size:13px; }}
  summary {{ cursor:pointer; color:var(--accent); }}
  .orig {{ white-space:pre-wrap; background:var(--bg); padding:8px; border-radius:8px; }}
  .meta {{ display:flex; justify-content:space-between; align-items:center; margin-top:8px; gap:8px; }}
  .links {{ display:flex; gap:6px; flex-shrink:0; }}
  .btn {{ background:var(--accent); color:#fff; text-decoration:none; font-weight:600; white-space:nowrap;
         padding:6px 10px; border-radius:8px; font-size:13px; }}
  .btn.alt {{ background:transparent; color:var(--accent); border:1px solid var(--line); }}
  .empty {{ color:var(--muted); }}
</style>
</head>
<body><div class="wrap">
<header>
  <h1>🏠 דירות לפי הפילטר – {date_str}</h1>
  <div class="stats">{stats['groups']} קבוצות · {stats['unique']} פוסטים חדשים נסרקו ·
    {len(matches)} מתאימים · {len(maybes)} אולי</div>
</header>
<p class="filter">{_e(filter_desc)}</p>
{body}
{warn}
</div></body></html>"""
