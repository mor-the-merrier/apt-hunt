"""מדפיס את ה-chat id של מי ששלח הודעה לבוט. מריצים פעם אחת בזמן ההתקנה."""
import os
import sys

import requests

token = os.environ.get("TELEGRAM_BOT_TOKEN")
if not token:
    sys.exit("חסר TELEGRAM_BOT_TOKEN ב-Secrets")
r = requests.get(f"https://api.telegram.org/bot{token}/getUpdates", timeout=30)
data = r.json()
if not data.get("ok"):
    sys.exit(f"שגיאה מטלגרם: {data.get('description')} (בדוק שהטוקן נכון)")
chats = {}
for u in data["result"]:
    msg = u.get("message") or u.get("channel_post") or u.get("my_chat_member") or {}
    chat = msg.get("chat")
    if chat:
        chats[chat["id"]] = chat.get("title") or chat.get("first_name") or chat.get("username")
if not chats:
    sys.exit("לא נמצאו הודעות. שלח לבוט הודעה בטלגרם והרץ שוב.")
for cid, name in chats.items():
    print(f"TELEGRAM_CHAT_ID = {cid}   ({name})")
