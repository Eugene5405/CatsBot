"""Общие функции: проверка админа/подписки, мут, наказание, разбор сроков, логи."""
import re
import time
from datetime import timedelta
from aiogram.enums import ChatMemberStatus
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import ChatPermissions, Message
import config
import db
from loader import bot

_admin_cache: dict[int, tuple[float, set[int], set[int]]] = {}

async def _load_admins(chat_id: int) -> tuple[set[int], set[int]]:
    now = time.time()
    cached = _admin_cache.get(chat_id)
    if cached and now - cached[0] < 60: return cached[1], cached[2]
    mods, creators = set(), set()
    for a in await bot.get_chat_administrators(chat_id):
        if a.status == ChatMemberStatus.CREATOR:
            creators.add(a.user.id)
            mods.add(a.user.id)
        elif getattr(a, "can_restrict_members", False) or getattr(a, "can_delete_messages", False):
            mods.add(a.user.id)
    _admin_cache[chat_id] = (now, mods, creators)
    return mods, creators

async def get_mods(chat_id: int) -> set[int]:
    return (await _load_admins(chat_id))[0]

async def is_admin(chat_id: int, user_id: int) -> bool:
    return user_id in await get_mods(chat_id)

async def is_creator(chat_id: int, user_id: int) -> bool:
    return user_id in (await _load_admins(chat_id))[1]

async def is_admin_msg(m: Message) -> bool:
    if m.sender_chat and m.sender_chat.id == m.chat.id: return True
    return bool(m.from_user) and await is_admin(m.chat.id, m.from_user.id)

_DUR_RE = re.compile(r"^\s*(\d+)\s*([a-zа-яё]+)?", re.I)
_UNITS = ((r"м|мин|минут[аыу]?|m|min", 60), (r"ч|час|часа|часов|h|hr", 3600), (r"д|дн|дня|дней|день|d", 86400), (r"н|нед|неделя|недели|недель|неделю|w", 604800))

def split_duration(text: str, strict: bool = False) -> tuple[int | None, str]:
    mt = _DUR_RE.match(text or "")
    if not mt: return None, (text or "").strip()
    n, word = int(mt.group(1)), (mt.group(2) or "").lower()
    for pattern, mult in _UNITS:
        if re.fullmatch(pattern, word): return n * mult, text[mt.end():].strip()
    if strict: return None, text.strip()
    return n * 3600, (text[mt.start(2):].strip() if word else "")

def fmt_duration(secs: int) -> str:
    d, rem = divmod(int(secs), 86400)
    h, rem = divmod(rem, 3600)
    mnt = rem // 60
    parts = [f"{d} д." if d else "", f"{h} ч." if h else "", f"{mnt} мин." if mnt and not d else ""]
    return " ".join(p for p in parts if p) or "меньше минуты"

async def log_action(text: str):
    if config.LOG_CHAT_ID:
        try: await bot.send_message(config.LOG_CHAT_ID, text)
        except Exception: pass

async def mute(chat_id: int, user_id: int, seconds: int):
    await bot.restrict_chat_member(chat_id, user_id, ChatPermissions(can_send_messages=False), until_date=timedelta(seconds=max(seconds, 60)))

async def unmute(chat_id: int, user_id: int):
    chat = await bot.get_chat(chat_id)
    perms = chat.permissions or ChatPermissions(can_send_messages=True, can_send_other_messages=True)
    await bot.restrict_chat_member(chat_id, user_id, perms)

async def notify_ban(chat_id: int, user, moderator, reason: str, seconds: int):
    try: title = (await bot.get_chat(chat_id)).title or "чат"
    except Exception: title = "чат"
    term = f"на {fmt_duration(seconds)}" if seconds else "навсегда"
    mod = moderator.mention_html() if moderator else "автомодерация"
    text = f"⛔ Вас забанили в чате «{title}»\n⏱ Срок: {term}\n👮 Модератор: {mod}\n📝 Причина: {reason or 'не указана'}\n\nЕсли вы не согласны, подайте апелляцию."
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="📨 Подать апелляцию", callback_data=f"ap:{chat_id}")]])
    try: await bot.send_message(user.id, text, reply_markup=kb)
    except Exception: pass

async def ban_user(chat_id: int, user, moderator=None, reason: str = "", seconds: int = 0) -> bool:
    if db.use_item(chat_id, user.id, "anti_ban"): return False
    await bot.ban_chat_member(chat_id, user.id, until_date=timedelta(seconds=seconds) if seconds else None)
    await notify_ban(chat_id, user, moderator, reason, seconds)
    return True

async def punish(chat_id: int, user, reason: str, mute_seconds: int = 0, warn: bool = True, moderator=None):
    lines = [f"⚠️ {user.mention_html()}: {reason}"]
    if mute_seconds:
        await mute(chat_id, user.id, mute_seconds)
        lines.append(f"🔇 Мут на {fmt_duration(mute_seconds)}")
    if warn:
        count, bans = db.add_warn(chat_id, user.id, reason, moderator.id if moderator else 0)
        if count == 0:
            secs = 3 * 86400 if bans == 1 else 0
            if await ban_user(chat_id, user, moderator, "3 предупреждения", secs):
                lines.append("⛔ 3 предупреждения — бан на 3 дня." if secs else "⛔ 3 предупреждения — бан навсегда.")
            else: lines.append("🛡 3 предупреждения, но защита от бана сработала.")
        else: lines.append(f"Предупреждений: {count}/3 (каждое сгорает через {config.WARN_TTL_DAYS} дн.)")
    if moderator: lines.append(f"👮 Модератор: {moderator.mention_html()}")
    text = "\n".join(lines)
    await bot.send_message(chat_id, text)
    await log_action(text)
