"""איסוף פוסטים מקבוצות פייסבוק ציבוריות דרך Apify."""
from __future__ import annotations

import time

import requests

API = "https://api.apify.com/v2"


def run_actor(token: str, cfg: dict, groups: list[dict]) -> list[dict]:
    """מריץ את ה-Actor, מחכה לסיום ומחזיר את הפריטים הגולמיים."""
    c = cfg["collector"]
    actor_input = {
        "startUrls": [{"url": g["url"]} for g in groups],
        "viewOption": "CHRONOLOGICAL",
        "onlyPostsNewerThanHours": int(c.get("hours_back", 26)),
        "maxItems": int(c.get("max_posts_per_group", 60)),
        "includeComments": False,
    }
    params = {"token": token}
    r = requests.post(f"{API}/acts/{c['actor']}/runs", params=params, json=actor_input, timeout=60)
    r.raise_for_status()
    run = r.json()["data"]
    run_id, dataset_id = run["id"], run["defaultDatasetId"]
    print(f"[apify] started run {run_id} for {len(groups)} groups", flush=True)
    started = time.time()

    deadline = time.time() + 60 * int(c.get("run_timeout_minutes", 20))
    status = run["status"]
    while status in ("READY", "RUNNING"):
        if time.time() > deadline:
            raise TimeoutError(f"Apify run {run_id} did not finish in time")
        time.sleep(15)
        r = requests.get(f"{API}/actor-runs/{run_id}", params=params, timeout=60)
        r.raise_for_status()
        status = r.json()["data"]["status"]
        print(f"[apify] {status} – {int(time.time() - started)}s", flush=True)
    if status != "SUCCEEDED":
        raise RuntimeError(f"Apify run {run_id} ended with status {status}")

    r = requests.get(
        f"{API}/datasets/{dataset_id}/items",
        params={**params, "clean": "true", "format": "json"},
        timeout=120,
    )
    r.raise_for_status()
    items = r.json()
    print(f"[apify] done: {len(items)} items in {int(time.time() - started)}s", flush=True)
    return items


def normalize(item: dict, groups: list[dict]) -> dict | None:
    """ממיר פריט גולמי לפורמט אחיד. מחזיר None לפריטים בלי טקסט."""
    text = (item.get("text") or item.get("message") or item.get("postText") or "").strip()
    if not text:
        return None
    url = item.get("url") or item.get("postUrl") or item.get("facebookUrl") or ""
    post_id = str(item.get("legacyId") or item.get("postId") or item.get("id") or url)
    group = item.get("groupTitle") or ""
    if not group:
        src = item.get("inputUrl") or item.get("facebookUrl") or ""
        group = next((g["name"] for g in groups if g["name"] and g["url"].rstrip("/") in src), "")
    user = item.get("user") or {}
    return {
        "id": post_id,
        "text": text,
        "url": url,
        "time": item.get("time") or item.get("date") or item.get("timestamp"),
        "group": group,
        "author": user.get("name") if isinstance(user, dict) else None,
    }
