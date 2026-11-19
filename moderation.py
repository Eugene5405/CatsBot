"""Команды модераторов (с кулдаунами из тетради)."""
from aiogram import F, Router
from aiogram.dispatcher.event.bases import SkipHandler
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import Message

import config
import db
from loader import bot
from people import resolve_target
from utils import ban_user, fmt_duration, is_admin, is_admin_msg, is_creator, log_action, mute, split_duration, unmute, punish

router = Router()
router.message.filter(F.chat.type.in_({"group", "supergroup"}))

ALIASES = {
    "ban": {"бан", "ban"}, "unban": {"разбан", "unban"},
    "mute": {"мут", "mute"}, "unmute": {"размут", "анмут", "unmute"},
    "warn": {"пред", "през", "прея", "варн", "warn"}, "kick": {"кик", "kick"},
}
WORD2CMD = {w: c for c, ws in ALIASES.items() for w in ws}
COOLDOWNS = {"mute": config.CD_MUTE_H * 3600, "warn": config.CD_WARN_H * 3600, "ban": config.CD_BAN_H * 3600}
CD_NAMES = {"mute": "мут", "warn": "предупреждение", "ban": "бан"}

def parse_text_cmd(text):
    t = (text or "").strip()
    if not t: return None
    parts = t.split(None, 1)
    word = parts[0].lower()
    if word.startswith("/"): word = word[1:]
    word = word.split("@")[0].strip(".,!:;")
    rest = parts[1].strip() if len(parts) > 1 else ""
    if word == "unwarn": return "unwarn", rest
    if word == "снять":
        p2 = rest.split(None, 1)
        if p2 and p2[0].lower().strip(".,!:;") in ALIASES["warn"]: return "unwarn", (p2[1].strip() if len(p2) > 1 else "")
        return None
    cmd = WORD2CMD.get(word)
    return (cmd, rest) if cmd else None

async def run(m: Message, cmd: str, target, rest: str):
    chat_id, mod = m.chat.id, m.from_user
    punishing = cmd in ("ban", "mute", "warn", "kick")
    if punishing and target.id == mod.id:
        await m.reply("📝 Себя наказывать нельзя.")
        return
    if punishing and (target.is_bot or await is_admin(chat_id, target.id)):
        await m.reply("📝 Эту цель наказывать нельзя (бот или админ).")
        return

    cd_key = None
    if cmd in COOLDOWNS and not await is_creator(chat_id, mod.id):
        cd_key = f"adm:{chat_id}:{mod.id}:{target.id}:{cmd}"
        left = db.cooldown_left(cd_key, COOLDOWNS[cmd])
        if left:
            await m.reply(f"⏳ {CD_NAMES[cmd].capitalize()} этому человеку можно выдать снова через {fmt_duration(left)}. На другого человека можно сразу.")
            return

    try:
        if cmd == "ban":
            secs, reason = split_duration(rest, strict=True)
            if await ban_user(chat_id, target, mod, reason, secs or 0):
                term = f"на {fmt_duration(secs)}" if secs else "навсегда"
                text = f"🔴 {target.mention_html()} получает бан {term}"
                if reason: text += f"\nПричина: {reason}"
                text += f"\n👮 Модератор: {mod.mention_html()}"
                await m.answer(text)
                await log_action(text)
            else: await m.answer(f"🛡 {target.mention_html()} спасён от бана защитой (Анти-бан).")
        elif cmd == "mute":
            secs, reason = split_duration(rest)
            secs = secs or config.DEFAULT_MUTE_SECONDS
            if db.consume_item(chat_id, target.id, "anti_mute"): await m.answer(f"🛡 {target.mention_html()} спасён от мута (Анти-мут).")
            else:
                await mute(chat_id, target.id, secs)
                text = f"🔇 {target.mention_html()} получает мут на {fmt_duration(secs)}"
                if reason: text += f"\nПричина: {reason}"
                text += f"\n👮 Модератор: {mod.mention_html()}"
                await m.answer(text)
                await log_action(text)
        elif cmd == "warn":
            if db.consume_item(chat_id, target.id, "anti_warn"): await m.answer(f"🛡 {target.mention_html()} спасён от предупреждения (Анти-пред).")
            else:
                await punish(chat_id, target, rest or "нарушение правил", moderator=mod)
        elif cmd == "unban":
            await bot.unban_chat_member(chat_id, target.id, only_if_banned=True)
            await m.answer(f"✅ Пользователь {target.mention_html()} разбанен.")
        elif cmd == "unmute":
            await unmute(chat_id, target.id)
            await m.answer(f"🔊 С {target.mention_html()} снят мут.")
        elif cmd == "kick":
            await bot.ban_chat_member(chat_id, target.id)
            await bot.unban_chat_member(chat_id, target.id)
            await m.answer(f"👢 {target.mention_html()} исключён из чата.")
        elif cmd == "unwarn":
            words = rest.split()
            rows = db.list_warns(chat_id, target.id)
            number = int(words[0]) if words and words[0].isdigit() else len(rows)
            if db.remove_warn_by_number(chat_id, target.id, number):
                await m.answer(f"✅ Предупреждение №{number} у {target.mention_html()} снято. Осталось: {len(rows) - 1}/3")
            else:
                await m.reply("❌ Нет предупреждения с таким номером.")
                return
    except TelegramBadRequest as e:
        await m.reply(f"❌ Не получилось: {e.message}\nПроверь, что у бота есть права банить.")
        return
    if cd_key: db.set_cooldown(cd_key)

@router.message(F.text.func(lambda t: parse_text_cmd(t) is not None))
async def mod_cmd(m: Message):
    if not await is_admin_msg(m): raise SkipHandler
    cmd, rest = parse_text_cmd(m.text)
    target, rest, unknown = await resolve_target(m, rest)
    if unknown:
        await m.reply(f"❓ Я не знаю пользователя @{unknown} (он должен был написать в чат при мне). Ответь командой на его сообщение.")
        return
    if target is None:
        if m.text.lstrip().startswith("/"):
            await m.reply("📝 Нет информации о пользователе. Ответь командой на его сообщение или укажи @юзернейм.")
            return
        raise SkipHandler
    await run(m, cmd, target, rest)
