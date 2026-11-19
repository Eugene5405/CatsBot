"""Люди: объект Person, поиск цели (ответ / @username / id)."""
import html
import db

class Person:
    def __init__(self, id: int, name: str | None, username: str | None = None, is_bot: bool = False):
        self.id = id
        self.name = name or f"id{id}"
        self.username = username
        self.is_bot = is_bot

    @classmethod
    def from_user(cls, u):
        return cls(u.id, u.full_name, u.username, bool(u.is_bot))

    @property
    def full_name(self) -> str: return self.name
    def mention_html(self) -> str: return f'<a href="tg://user?id={self.id}">{html.escape(self.name)}</a>'

def vip_mention(chat_id: int, p: Person) -> str:
    stats = db.get_user_stats(chat_id, p.id)
    return ("⭐ " if stats.get("vip") else "") + p.mention_html()

def cmd_arg(text, names) -> str | None:
    t = (text or "").strip()
    if not t: return None
    parts = t.split(None, 1)
    word = parts[0].lower()
    if word.startswith("/"): word = word[1:]
    word = word.split("@")[0]
    if word in names: return parts[1].strip() if len(parts) > 1 else ""
    return None

async def resolve_target(m, text: str):
    tokens = (text or "").split()
    reply = m.reply_to_message.from_user if m.reply_to_message and m.reply_to_message.from_user else None
    idx = None
    if tokens and tokens[0].startswith("@") and len(tokens[0]) > 1: idx = 0
    elif reply is None:
        for i, tok in enumerate(tokens):
            if tok.startswith("@") and len(tok) > 1:
                idx = i
                break

    if idx is not None:
        name = tokens[idx][1:].strip(",.!?;:")
        row = db.find_user(name)
        if row: return Person(row[0], row[1], row[2]), " ".join(tokens[:idx] + tokens[idx + 1:]), None
        if reply is None: return None, text, name

    if tokens and tokens[0].isdigit() and len(tokens[0]) >= 7 and reply is None:
        uid = int(tokens[0])
        row = db.get_user(uid)
        return Person(uid, row[1] if row else None, row[2] if row else None), " ".join(tokens[1:]), None

    if reply is not None: return Person.from_user(reply), text, None
    return None, text, None
