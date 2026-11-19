"""Заявки, приветствие и добавление/удаление самого бота."""
import html
import logging
import os
from aiogram import F, Router
from aiogram.enums import ChatMemberStatus
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import CallbackQuery, ChatJoinRequest, ChatMemberUpdated, InlineKeyboardButton, InlineKeyboardMarkup

import config
import db
from loader import bot
from rules import get_rules

router = Router()
_ACTIVE = {ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR}
_LEFT = {ChatMemberStatus.LEFT, ChatMemberStatus.KICKED}

def mention(user) -> str:
    name = html.escape(user.full_name or user.first_name or "Участник")
    return f'<a href="tg://user?id={user.id}">{name}</a>'

async def _is_subscribed(user_id: int) -> bool:
    if not config.CHANNEL_ID: return True
    try:
        m = await bot.get_chat_member(config.CHANNEL_ID, user_id)
        return m.status in _ACTIVE
    except TelegramBadRequest: return True

async def _channel_url() -> str | None:
    if getattr(config, "CHANNEL_URL", None): return config.CHANNEL_URL
    if not config.CHANNEL_ID: return None
    try:
        chat = await bot.get_chat(config.CHANNEL_ID)
        return f"https://t.me/{chat.username}" if chat.username else chat.invite_link
    except Exception: return None

def _ask_sub_kb(chat_id: int, url: str | None) -> InlineKeyboardMarkup:
    rows = []
    if url: rows.append([InlineKeyboardButton(text="📢 Открыть канал", url=url)])
    rows.append([InlineKeyboardButton(text="✅ Я подписался", callback_data=f"chksub:{chat_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

async def _send_welcome(chat_id: int, chat_title: str | None, user):
    settings = db.get_chat_settings(chat_id)
    if not settings.get("welcome", True): return
    title = html.escape(chat_title or getattr(config, "CHAT_TITLE", "Чат"))
    text = f"👋 Добро пожаловать в <b>{title}</b>, {mention(user)}!\n\nОзнакомься с правилами, чтобы не словить мут или бан:\n{get_rules(chat_id)}"
    try: await bot.send_message(chat_id, text)
    except TelegramBadRequest: pass

@router.chat_join_request()
async def on_join_request(req: ChatJoinRequest):
    if await _is_subscribed(req.from_user.id):
        await req.approve()
        return
    try:
        await bot.send_message(req.from_user.id, f"Чтобы вступить в <b>{html.escape(req.chat.title or config.CHAT_NAME)}</b>, сначала подпишись на наш канал, затем нажми кнопку ниже:", reply_markup=_ask_sub_kb(req.chat.id, await _channel_url()))
    except (TelegramForbiddenError, TelegramBadRequest): pass

@router.callback_query(F.data.startswith("chksub:"))
async def on_check_sub(cb: CallbackQuery):
    chat_id = int(cb.data.split(":", 1)[1])
    if not await _is_subscribed(cb.from_user.id):
        await cb.answer("Подписка пока не видна. Подпишись на канал и нажми снова.", show_alert=True)
        return
    try:
        await bot.approve_chat_join_request(chat_id, cb.from_user.id)
        await cb.message.edit_text("✅ Отлично, заявка одобрена! Добро пожаловать в чат.")
    except TelegramBadRequest as e:
        await cb.message.edit_text(f"Не удалось принять заявку: {e.message}")
    await cb.answer()

@router.chat_member()
async def on_chat_member_update(event: ChatMemberUpdated):
    old_status, new_status = event.old_chat_member.status, event.new_chat_member.status
    user = event.new_chat_member.user
    if user.is_bot: return
    if old_status in _LEFT and new_status in _ACTIVE:
        await _send_welcome(event.chat.id, event.chat.title, user)
    elif old_status in _ACTIVE and new_status == ChatMemberStatus.LEFT:
        settings = db.get_chat_settings(event.chat.id)
        if settings.get("welcome", True):
            try: await bot.send_message(event.chat.id, f"👋 {mention(user)} покинул(а) чат. Удачи и всего хорошего!")
            except TelegramBadRequest: pass

@router.my_chat_member()
async def on_my_chat_member(event: ChatMemberUpdated):
    old_status, new_status = event.old_chat_member.status, event.new_chat_member.status
    chat, actor = event.chat, event.from_user
    if chat.type not in ("group", "supergroup"): return
    owner_id = os.getenv("OWNER_ID") or getattr(config, "OWNER_ID", None)

    if old_status in _LEFT and new_status in _ACTIVE:
        db.register_chat(chat.id, chat.title)
        try: await bot.send_message(chat.id, f"👋 Привет! Я <b>Хранитель чата</b>.\nВыдайте мне права администратора и напишите <code>/status</code> для проверки настроек.")
        except TelegramBadRequest: pass
        if actor and not actor.is_bot:
            try: await bot.send_message(actor.id, f"✅ Бот успешно добавлен в чат <b>{html.escape(chat.title or 'Группа')}</b> (<code>{chat.id}</code>) и синхронизирован с админ-панелью.")
            except (TelegramForbiddenError, TelegramBadRequest): pass
        if owner_id and str(owner_id) != str(getattr(actor, "id", "")):
            try: await bot.send_message(int(owner_id), f"➕ Бот добавлен в новый чат: <b>{html.escape(chat.title or 'Группа')}</b> (<code>{chat.id}</code>).")
            except (TelegramForbiddenError, TelegramBadRequest, ValueError): pass
    elif old_status in _ACTIVE and new_status in _LEFT:
        if hasattr(db, "delete_chat"): db.delete_chat(chat.id)
        if actor and not actor.is_bot:
            try: await bot.send_message(actor.id, f"🗑 Бот был удалён из чата <b>{html.escape(chat.title or 'Группа')}</b>. Чат убран из админ-панели.")
            except (TelegramForbiddenError, TelegramBadRequest): pass
