import os
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError: pass

def _int(name: str, default: int = 0) -> int:
    v = os.getenv(name, "").strip()
    return int(v) if v else default

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
if not BOT_TOKEN: raise SystemExit("Не задан BOT_TOKEN")

CHANNEL_ID = _int("CHANNEL_ID")
CHANNEL_LINK = os.getenv("CHANNEL_LINK", "").strip()
CHANNEL_URL = CHANNEL_LINK
LOG_CHAT_ID = _int("LOG_CHAT_ID")
OWNER_ID = _int("OWNER_ID")

CHAT_NAME = os.getenv("CHAT_NAME", "подвал Евы")
CHAT_TITLE = CHAT_NAME

WARN_TTL_DAYS = _int("WARN_TTL_DAYS", 30)
DEFAULT_MUTE_SECONDS = _int("DEFAULT_MUTE_SECONDS", 3600)

# Кулдауны админов (из тетради: мут/пред - 3 часа, бан - 8 часов)
CD_MUTE_H = _int("CD_MUTE_H", 3)
CD_WARN_H = _int("CD_WARN_H", 3)
CD_BAN_H = _int("CD_BAN_H", 8)

SPAM_COUNT = _int("SPAM_COUNT", 3)
SPAM_WINDOW = _int("SPAM_WINDOW", 20)
FLOOD_COUNT = _int("FLOOD_COUNT", 6)
FLOOD_WINDOW = _int("FLOOD_WINDOW", 8)
REPEAT_COUNT = _int("REPEAT_COUNT", 3)

FILTER_LABELS = {
    "mat": "Мат (п.9)", "spam": "Спам (п.1)", "ad": "Реклама (п.6)", "flood": "Флуд (п.2)", "inline": "Инлайн-боты (п.11)",
}
ALLOWED_LINKS = set()
