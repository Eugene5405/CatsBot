"""Апелляции на бан: обращение с номером -> ЛС админам."""
import html
from aiogram import F, Router
from aiogram.dispatcher.event.bases import SkipHandler
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

import config
import db
from loader import bot
from people import Person
from utils import get_mods, is_admin

router = Router()
KIND_TITLE = {"appeal": "Апелляция", "admin_apply": "Заявка на админа"}
INSTRUCTIONS = "📨 <b>Апелляция</b>\n\nНапиши одним сообщением:\n1. Причину, по которой тебя забанили\n2. Кто был модератор\n3. Твой юзернейм (@username)\n\nОтмена: /cancel"

async def _send(chat_id: int, text: str, rows: list) -> bool:
    try:
        await bot.send_message(chat_id, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
        return True
    except TelegramBadRequest:
        try:
            await bot.send_message(chat_id, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows[1:]) if rows[1:] else None)
            return True
        except Exception: return False
    except Exception: return False

async def notify_mods(chat_id: int, ticket_id: int, kind: str, user: Person, text: str) -> int:
    try: title = (await bot.get_chat(chat_id)).title or "чат"
    except Exception: title = "чат"
    who = user.mention_html() + (f" (@{user.username})" if user.username else "")
    body = f"📨 <b>{KIND_TITLE[kind]} №{ticket_id}</b>\nЧат: {html.escape(title)}\nОт: {who}\n\n{html.escape(text)}"
    rows = [[InlineKeyboardButton(text="💬 Связаться", url=f"tg://user?id={user.id}")]]
    if kind == "appeal": rows.append([InlineKeyboardButton(text="✅ Разбанить", callback_data=f"unb:{chat_id}:{user.id}:{ticket_id}")])
    delivered = 0
    for uid in await get_mods(chat_id):
        if await _send(uid, body, rows): delivered += 1
    if config.LOG_CHAT_ID: await _send(config.LOG_CHAT_ID, body, rows)
    return delivered

@router.callback_query(F.data.startswith("ap:"))
async def on_appeal_button(cb: CallbackQuery):
    chat_id = int(cb.data.split(":", 1)[1])
    db.set_pending(cb.from_user.id, "appeal", chat_id)
    await cb.message.answer(INSTRUCTIONS)
    await cb.answer()

@router.message(F.chat.type == "private", F.text)
async def on_private_text(m: Message):
    if m.text.startswith("/"):
        if m.text.split()[0].lower().split("@")[0] == "/cancel":
            db.pop_pending(m.from_user.id)
            await m.answer("Отменено.")
            return
        raise SkipHandler
    pending = db.pop_pending(m.from_user.id)
    if not pending: raise SkipHandler
    kind, chat_id = pending
    tid = db.add_ticket(kind, chat_id, m.from_user.id, m.text)
    delivered = await notify_mods(chat_id, tid, kind, Person.from_user(m.from_user), m.text)
    text = f"✅ Обращение №{tid} принято. В скором времени с тобой свяжется админ."
    if not delivered and not config.LOG_CHAT_ID: text += "\n(Админы пока не открывали бота в личке, поэтому обращение ждёт их в списке /tickets.)"
    await m.answer(text)

@router.callback_query(F.data.startswith("unb:"))
async def on_unban_button(cb: CallbackQuery):
    _, chat_id, user_id, tid = cb.data.split(":")
    chat_id, user_id = int(chat_id), int(user_id)
    if not await is_admin(chat_id, cb.from_user.id):
        await cb.answer("Только для админов чата.", show_alert=True)
        return
    try: await bot.unban_chat_member(chat_id, user_id, only_if_banned=True)
    except Exception as e:
        await cb.answer(f"Не вышло: {e}", show_alert=True)
        return
    db.close_ticket(int(tid))
    await cb.message.edit_text((cb.message.html_text or "") + f"\n\n✅ Разбанен ({html.escape(cb.from_user.full_name)})")
    try: await bot.send_message(user_id, "✅ Твоя апелляция одобрена: бан снят, можно вернуться в чат.")
    except Exception: pass
    await cb.answer("Разбанен")

@router.message(F.text.func(lambda t: (t or "").split()[:1] and (t or "").split()[0].lower().split("@")[0] == "/tickets"))
async def cmd_tickets(m: Message):
    lines = []
    for tid, kind, chat_id, user_id, text in db.open_tickets():
        if await is_admin(chat_id, m.from_user.id):
            lines.append(f"№{tid} · {KIND_TITLE.get(kind, kind)} · <a href=\"tg://user?id={user_id}\">человек</a>\n{html.escape(text[:150])}")
    await m.answer("\n\n".join(lines) if lines else "Открытых обращений нет.")
