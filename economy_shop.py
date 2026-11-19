"""Валюта и Магазин (13 товаров)."""
import asyncio
import html
import random
import re
from aiogram import F, Router
from aiogram.enums import ChatMemberStatus, ChatType
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, Message, InlineKeyboardButton, InlineKeyboardMarkup

import db
from catalog import SHOP, ITEM_NAMES, NO_ARGS, BY_N
from people import Person, cmd_arg, resolve_target, vip_mention

router = Router()
router.message.filter(F.chat.type.in_({ChatType.GROUP, ChatType.SUPERGROUP}))
COIN = "🪙"

@router.message(F.text.func(lambda t: t is not None and t.strip().lower() in {"мешок", "/bag", "/profile"}))
async def cmd_bag(message: Message):
    if not message.from_user: return
    stats = db.get_user_stats(message.chat.id, message.from_user.id)
    inv = stats["inventory"]
    inv_lines = [f"• {ITEM_NAMES.get(k, k)}: <b>{v} шт.</b>" for k, v in inv.items() if v > 0]
    inv_text = "\n".join(inv_lines) if inv_lines else "<i>Пусто</i>"
    vip_line = "👑 <b>Активен</b>" if stats["vip"] else "Обычный"
    prefix_line = f"\n🏷 Префикс: <b>{html.escape(stats['prefix'])}</b>" if stats.get("prefix") else ""
    await message.reply(f"🎒 <b>Профиль</b>\n\n🪙 Баланс: <b>{stats['balance']} Алиби</b>\n🏅 Репутация: <b>{stats['reputation']}</b>\n✨ Статус: {vip_line}{prefix_line}\n\n<b>Инвентарь:</b>\n{inv_text}")

@router.message(F.text.func(lambda t: cmd_arg(t, {"setcreds"}) is not None))
async def cmd_setcreds(message: Message):
    if not message.from_user: return
    member = await message.bot.get_chat_member(message.chat.id, message.from_user.id)
    if member.status not in {ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR}: return
    target, rest, _ = await resolve_target(message, cmd_arg(message.text, {"setcreds"}))
    mt = re.search(r"\d+", rest)
    if not target or not mt:
        await message.reply("Формат: /setcreds 500 (ответом на сообщение)")
        return
    amount = int(mt.group())
    bal = db.set_balance(message.chat.id, target.id, amount)
    await message.reply(f"💰 Баланс {target.mention_html()} установлен на <b>{bal} Алиби</b>.")

@router.message(F.text.func(lambda t: cmd_arg(t, {"give", "дать"}) is not None))
async def cmd_give(message: Message):
    if not message.from_user: return
    target, rest, _ = await resolve_target(message, cmd_arg(message.text, {"give", "дать"}))
    mt = re.search(r"\d+", rest)
    if not target or not mt:
        await message.reply("Формат: «дать 50» ответом на сообщение.")
        return
    amount = int(mt.group())
    if amount <= 0 or target.id == message.from_user.id: return
    sender_stats = db.get_user_stats(message.chat.id, message.from_user.id)
    if sender_stats["balance"] < amount:
        await message.reply(f"❌ Недостаточно Алиби (у вас <b>{sender_stats['balance']}</b>).")
        return
    db.add_balance(message.chat.id, message.from_user.id, -amount)
    db.add_balance(message.chat.id, target.id, amount)
    await message.reply(f"💸 {message.from_user.mention_html()} передал(а) <b>{amount} Алиби</b> участнику {target.mention_html()}!")

@router.message(F.text.func(lambda t: t is not None and t.strip().lower() in {"магазин", "/shop"}))
async def cmd_shop(message: Message):
    if not message.from_user: return
    lines = ["🏪 <b>Магазин чата (валюта: Алиби)</b>\n"]
    for n, key, name, price, desc in SHOP:
        lines.append(f"<b>{n}. {name}</b> — <code>{price}</code> Алиби\n<i>{desc}</i>")
    lines.append("\nНажмите на кнопку ниже, чтобы купить товар:")
    rows, row = [], []
    for n in sorted(NO_ARGS):
        row.append(InlineKeyboardButton(text=f"{n}. {BY_N[n][2]}", callback_data=f"buy:{n}"))
        if len(row) == 2: rows.append(row); row = []
    if row: rows.append(row)
    await message.reply("\n".join(lines), reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))

@router.callback_query(F.data.startswith("buy:"))
async def on_buy_item(cb: CallbackQuery):
    n = int(cb.data.split(":")[1])
    item = BY_N.get(n)
    if not item:
        await cb.answer("Товар не найден.", show_alert=True)
        return
    _, key, name, price, _ = item
    chat_id = cb.message.chat.id
    user_id = cb.from_user.id
    stats = db.get_user_stats(chat_id, user_id)
    if stats["balance"] < price:
        await cb.answer(f"Не хватает Алиби! Нужно {price}, у вас {stats['balance']}.", show_alert=True)
        return
    db.add_balance(chat_id, user_id, -price)
    if key == "unwarn":
        left = db.remove_last_warn(chat_id, user_id)
        await cb.message.answer(f"🧹 {cb.from_user.mention_html()} купил(а) снятие преда! Активных варнов: <b>{left}/3</b>.")
    elif key == "vip":
        db.activate_vip(chat_id, user_id, days=30)
        await cb.message.answer(f"👑 {cb.from_user.mention_html()} активировал(а) <b>VIP-статус на 30 дней</b>!")
    elif key == "gift":
        roll = random.choice(["coins_100", "coins_350", "shield_mute", "shield_warn", "swear_pass"])
        if roll == "coins_100": db.add_balance(chat_id, user_id, 100); prize = "💰 100 Алиби"
        elif roll == "coins_350": db.add_balance(chat_id, user_id, 350); prize = "💎 Джекпот 350 Алиби"
        elif roll == "shield_mute": db.add_item(chat_id, user_id, "anti_mute", 1); prize = "🛡 Анти-мут"
        elif roll == "shield_warn": db.add_item(chat_id, user_id, "anti_warn", 1); prize = "🛡 Анти-пред"
        else: db.add_item(chat_id, user_id, "swear_pass", 1); prize = "🤬 Swear pass"
        await cb.message.answer(f"🎁 {cb.from_user.mention_html()} открыл(а) тайный подарок и получил(а): <b>{prize}</b>!")
    else:
        db.add_item(chat_id, user_id, key, 1)
        await cb.message.answer(f"✅ {cb.from_user.mention_html()} купил(а) <b>{name}</b>! Предмет добавлен в мешок (<code>мешок</code>).")
    await cb.answer("Покупка совершена!")
