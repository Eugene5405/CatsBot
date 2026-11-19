"""Работа с PostgreSQL (Neon): чаты, настройки, варны, экономика, репутация, РП и тикеты."""
import json
import os
import time
import psycopg

DATABASE_URL = os.getenv("DATABASE_URL", "")
TTL = 30 * 86400  # 30 дней на сгорание предупреждения

def _conn():
    return psycopg.connect(DATABASE_URL, autocommit=True)

def init_db() -> None:
    if not DATABASE_URL: return
    with _conn() as conn, conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS chats (
                chat_id BIGINT PRIMARY KEY, title TEXT NOT NULL DEFAULT 'Чат',
                profanity BOOLEAN NOT NULL DEFAULT TRUE, antispam BOOLEAN NOT NULL DEFAULT TRUE,
                antilink BOOLEAN NOT NULL DEFAULT TRUE, subcheck BOOLEAN NOT NULL DEFAULT TRUE,
                welcome BOOLEAN NOT NULL DEFAULT TRUE, updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
            CREATE TABLE IF NOT EXISTS settings (chat_id BIGINT NOT NULL, key TEXT NOT NULL, value TEXT, PRIMARY KEY (chat_id, key));
            CREATE TABLE IF NOT EXISTS warns (id SERIAL PRIMARY KEY, chat_id BIGINT NOT NULL, user_id BIGINT NOT NULL, reason TEXT, admin_id BIGINT, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW());
            CREATE TABLE IF NOT EXISTS warn_bans (chat_id BIGINT NOT NULL, user_id BIGINT NOT NULL, bans INT NOT NULL DEFAULT 0, PRIMARY KEY (chat_id, user_id));
            CREATE TABLE IF NOT EXISTS user_stats (chat_id BIGINT NOT NULL, user_id BIGINT NOT NULL, balance BIGINT NOT NULL DEFAULT 0, reputation INT NOT NULL DEFAULT 0, vip_until TIMESTAMPTZ, prefix TEXT, partner_id BIGINT, inventory JSONB NOT NULL DEFAULT '{}'::jsonb, PRIMARY KEY (chat_id, user_id));
            CREATE TABLE IF NOT EXISTS custom_rp (chat_id BIGINT NOT NULL, trigger TEXT NOT NULL, template TEXT NOT NULL, PRIMARY KEY (chat_id, trigger));
            CREATE TABLE IF NOT EXISTS cooldowns (key TEXT PRIMARY KEY, ts BIGINT NOT NULL);
            CREATE TABLE IF NOT EXISTS tickets (id SERIAL PRIMARY KEY, kind TEXT, chat_id BIGINT, user_id BIGINT, text TEXT, status TEXT DEFAULT 'open');
            CREATE TABLE IF NOT EXISTS pending (user_id BIGINT PRIMARY KEY, kind TEXT, chat_id BIGINT);
            CREATE TABLE IF NOT EXISTS users (user_id BIGINT PRIMARY KEY, username TEXT, name TEXT);
        """)

# --- Юзеры ---
def touch_user(user_id: int, username: str | None, name: str):
    if not DATABASE_URL: return
    with _conn() as conn, conn.cursor() as cur:
        cur.execute("INSERT INTO users (user_id, username, name) VALUES (%s, %s, %s) ON CONFLICT (user_id) DO UPDATE SET username = EXCLUDED.username, name = EXCLUDED.name", (user_id, (username or "").lower() or None, name))

def find_user(username: str):
    if not DATABASE_URL: return None
    with _conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT user_id, name, username FROM users WHERE username=%s", (username.lower(),))
        return cur.fetchone()

def get_user(user_id: int):
    if not DATABASE_URL: return None
    with _conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT user_id, name, username FROM users WHERE user_id=%s", (user_id,))
        return cur.fetchone()

# --- Чаты и настройки ---
def register_chat(chat_id: int, title: str | None) -> None:
    if not DATABASE_URL: return
    with _conn() as conn, conn.cursor() as cur:
        cur.execute("INSERT INTO chats (chat_id, title, updated_at) VALUES (%s, %s, NOW()) ON CONFLICT (chat_id) DO UPDATE SET title = EXCLUDED.title, updated_at = NOW();", (chat_id, (title or "Чат").strip()))

def delete_chat(chat_id: int) -> None:
    if not DATABASE_URL: return
    with _conn() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM chats WHERE chat_id = %s;", (chat_id,))

def get_chats() -> list[dict]:
    if not DATABASE_URL: return []
    with _conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT chat_id, title FROM chats ORDER BY updated_at DESC;")
        return [{"chat_id": str(r[0]), "title": r[1]} for r in cur.fetchall()]

def get_chat_settings(chat_id: int) -> dict:
    default = {"profanity": True, "antispam": True, "antilink": True, "subcheck": True, "welcome": True}
    if not DATABASE_URL: return default
    with _conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT profanity, antispam, antilink, subcheck, welcome FROM chats WHERE chat_id = %s;", (chat_id,))
        row = cur.fetchone()
        if not row: return default
        return {"profanity": bool(row[0]), "antispam": bool(row[1]), "antilink": bool(row[2]), "subcheck": bool(row[3]), "welcome": bool(row[4])}

def update_chat_settings(chat_id: int, data: dict) -> None:
    if not DATABASE_URL: return
    with _conn() as conn, conn.cursor() as cur:
        cur.execute("""
            INSERT INTO chats (chat_id, profanity, antispam, antilink, subcheck, welcome, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, NOW())
            ON CONFLICT (chat_id) DO UPDATE SET profanity = EXCLUDED.profanity, antispam = EXCLUDED.antispam, antilink = EXCLUDED.antilink, subcheck = EXCLUDED.subcheck, welcome = EXCLUDED.welcome, updated_at = NOW();
        """, (chat_id, bool(data.get("profanity", True)), bool(data.get("antispam", True)), bool(data.get("antilink", True)), bool(data.get("subcheck", True)), bool(data.get("welcome", True))))

def filter_on(chat_id: int, kind: str) -> bool:
    settings = get_chat_settings(chat_id)
    return settings.get(kind, get_setting(chat_id, "f_" + kind) != "0")

def set_setting(chat_id: int, key: str, value: str | None) -> None:
    if not DATABASE_URL: return
    if key.startswith("f_"):
        kind = key[2:]
        cur_settings = get_chat_settings(chat_id)
        if kind in cur_settings:
            cur_settings[kind] = value != "0"
            update_chat_settings(chat_id, cur_settings)
            return
    with _conn() as conn, conn.cursor() as cur:
        if value is None: cur.execute("DELETE FROM settings WHERE chat_id = %s AND key = %s;", (chat_id, key))
        else: cur.execute("INSERT INTO settings (chat_id, key, value) VALUES (%s, %s, %s) ON CONFLICT (chat_id, key) DO UPDATE SET value = EXCLUDED.value;", (chat_id, key, value))

def get_setting(chat_id: int, key: str) -> str | None:
    if not DATABASE_URL: return None
    with _conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT value FROM settings WHERE chat_id = %s AND key = %s;", (chat_id, key))
        row = cur.fetchone()
        return row[0] if row else None

# --- Варны ---
def active_warns(chat_id: int, user_id: int) -> int:
    if not DATABASE_URL: return 0
    with _conn() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM warns WHERE created_at < NOW() - INTERVAL '30 days';")
        cur.execute("SELECT COUNT(*) FROM warns WHERE chat_id=%s AND user_id=%s", (chat_id, user_id))
        return cur.fetchone()[0]

def list_warns(chat_id: int, user_id: int) -> list[tuple]:
    if not DATABASE_URL: return []
    with _conn() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM warns WHERE created_at < NOW() - INTERVAL '30 days';")
        cur.execute("SELECT id, extract(epoch from created_at)::int, reason FROM warns WHERE chat_id=%s AND user_id=%s ORDER BY created_at, id", (chat_id, user_id))
        return cur.fetchall()

def remove_warn_by_number(chat_id: int, user_id: int, number: int) -> bool:
    rows = list_warns(chat_id, user_id)
    if not 1 <= number <= len(rows): return False
    with _conn() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM warns WHERE id=%s", (rows[number - 1][0],))
    return True

def add_warn(chat_id: int, user_id: int, reason: str = "", moderator_id: int = 0) -> tuple[int, int]:
    if not DATABASE_URL: return 0, 0
    with _conn() as conn, conn.cursor() as cur:
        cur.execute("INSERT INTO warns (chat_id, user_id, reason, admin_id) VALUES (%s, %s, %s, %s)", (chat_id, user_id, reason, moderator_id))
        cur.execute("DELETE FROM warns WHERE created_at < NOW() - INTERVAL '30 days' AND chat_id=%s AND user_id=%s", (chat_id, user_id))
        cur.execute("SELECT COUNT(*) FROM warns WHERE chat_id=%s AND user_id=%s", (chat_id, user_id))
        count = cur.fetchone()[0]
        cur.execute("SELECT bans FROM warn_bans WHERE chat_id=%s AND user_id=%s", (chat_id, user_id))
        row = cur.fetchone()
        bans = row[0] if row else 0
        if count >= 3:
            bans += 1
            cur.execute("DELETE FROM warns WHERE chat_id=%s AND user_id=%s", (chat_id, user_id))
            cur.execute("INSERT INTO warn_bans VALUES (%s, %s, %s) ON CONFLICT (chat_id, user_id) DO UPDATE SET bans = EXCLUDED.bans", (chat_id, user_id, bans))
            return 0, bans
        return count, bans

def remove_last_warn(chat_id: int, user_id: int) -> int:
    if not DATABASE_URL: return 0
    with _conn() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM warns WHERE id = (SELECT id FROM warns WHERE chat_id=%s AND user_id=%s ORDER BY created_at DESC, id DESC LIMIT 1)", (chat_id, user_id))
    return active_warns(chat_id, user_id)

# --- Экономика ---
def get_user_stats(chat_id: int, user_id: int) -> dict:
    if not DATABASE_URL: return {"balance": 0, "reputation": 0, "vip": False, "inventory": {}, "prefix": "", "partner_id": 0}
    with _conn() as conn, conn.cursor() as cur:
        cur.execute("INSERT INTO user_stats (chat_id, user_id) VALUES (%s, %s) ON CONFLICT DO NOTHING", (chat_id, user_id))
        cur.execute("SELECT balance, reputation, vip_until, inventory, prefix, partner_id FROM user_stats WHERE chat_id=%s AND user_id=%s", (chat_id, user_id))
        row = cur.fetchone()
        if not row: return {"balance": 0, "reputation": 0, "vip": False, "inventory": {}, "prefix": "", "partner_id": 0}
        vip_active = row[2] is not None and row[2].timestamp() > time.time()
        return {"balance": row[0], "reputation": row[1], "vip": vip_active, "inventory": row[3] if isinstance(row[3], dict) else {}, "prefix": row[4] or "", "partner_id": row[5] or 0}

def add_balance(chat_id: int, user_id: int, amount: int) -> int:
    if not DATABASE_URL: return 0
    get_user_stats(chat_id, user_id)
    with _conn() as conn, conn.cursor() as cur:
        cur.execute("UPDATE user_stats SET balance = balance + %s WHERE chat_id=%s AND user_id=%s RETURNING balance", (amount, chat_id, user_id))
        return max(0, cur.fetchone()[0])

def set_balance(chat_id: int, user_id: int, amount: int) -> int:
    if not DATABASE_URL: return amount
    get_user_stats(chat_id, user_id)
    with _conn() as conn, conn.cursor() as cur:
        cur.execute("UPDATE user_stats SET balance = %s WHERE chat_id=%s AND user_id=%s RETURNING balance", (amount, chat_id, user_id))
        return cur.fetchone()[0]

def add_reputation(chat_id: int, user_id: int, amount: int) -> int:
    if not DATABASE_URL: return 0
    get_user_stats(chat_id, user_id)
    with _conn() as conn, conn.cursor() as cur:
        cur.execute("UPDATE user_stats SET reputation = reputation + %s WHERE chat_id=%s AND user_id=%s RETURNING reputation", (amount, chat_id, user_id))
        return max(0, cur.fetchone()[0])

def set_reputation(chat_id: int, user_id: int, amount: int) -> int:
    if not DATABASE_URL: return amount
    get_user_stats(chat_id, user_id)
    with _conn() as conn, conn.cursor() as cur:
        cur.execute("UPDATE user_stats SET reputation = %s WHERE chat_id=%s AND user_id=%s RETURNING reputation", (amount, chat_id, user_id))
        return cur.fetchone()[0]

def activate_vip(chat_id: int, user_id: int, days: int = 30):
    if not DATABASE_URL: return
    get_user_stats(chat_id, user_id)
    with _conn() as conn, conn.cursor() as cur:
        cur.execute("UPDATE user_stats SET vip_until = NOW() + INTERVAL '%s days' WHERE chat_id=%s AND user_id=%s", (days, chat_id, user_id))

def set_partner(chat_id: int, user_id: int, partner_id: int):
    if not DATABASE_URL: return
    get_user_stats(chat_id, user_id)
    with _conn() as conn, conn.cursor() as cur:
        cur.execute("UPDATE user_stats SET partner_id = %s WHERE chat_id=%s AND user_id=%s", (partner_id, chat_id, user_id))

# --- Инвентарь ---
def add_item(chat_id: int, user_id: int, item: str, qty: int = 1):
    if not DATABASE_URL: return
    get_user_stats(chat_id, user_id)
    with _conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT inventory FROM user_stats WHERE chat_id=%s AND user_id=%s", (chat_id, user_id))
        inv = cur.fetchone()[0] or {}
        inv[item] = inv.get(item, 0) + qty
        cur.execute("UPDATE user_stats SET inventory = %s WHERE chat_id=%s AND user_id=%s", (json.dumps(inv), chat_id, user_id))

def consume_item(chat_id: int, user_id: int, item: str) -> bool:
    if not DATABASE_URL: return False
    with _conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT inventory FROM user_stats WHERE chat_id=%s AND user_id=%s FOR UPDATE", (chat_id, user_id))
        row = cur.fetchone()
        if not row or not row[0]: return False
        inv = row[0]
        if inv.get(item, 0) <= 0: return False
        inv[item] -= 1
        cur.execute("UPDATE user_stats SET inventory = %s WHERE chat_id=%s AND user_id=%s", (json.dumps(inv), chat_id, user_id))
        return True
use_item = consume_item

# --- Кулдауны и прочее ---
def cooldown_left(key: str, seconds: int) -> int:
    if not DATABASE_URL: return 0
    with _conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT ts FROM cooldowns WHERE key = %s;", (key,))
        row = cur.fetchone()
        return max(0, int(row[0] + seconds - time.time())) if row else 0

def set_cooldown(key: str):
    if not DATABASE_URL: return
    with _conn() as conn, conn.cursor() as cur:
        cur.execute("INSERT INTO cooldowns (key, ts) VALUES (%s, %s) ON CONFLICT (key) DO UPDATE SET ts = EXCLUDED.ts;", (key, int(time.time())))

def check_and_set(key: str, seconds: int) -> int:
    left = cooldown_left(key, seconds)
    if not left: set_cooldown(key)
    return left

def add_custom_rp(chat_id: int, trigger: str, template: str):
    if not DATABASE_URL: return
    with _conn() as conn, conn.cursor() as cur:
        cur.execute("INSERT INTO custom_rp (chat_id, trigger, template) VALUES (%s, %s, %s) ON CONFLICT (chat_id, trigger) DO UPDATE SET template = EXCLUDED.template;", (chat_id, trigger, template))

def get_custom_rps(chat_id: int) -> dict:
    if not DATABASE_URL: return {}
    with _conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT trigger, template FROM custom_rp WHERE chat_id = %s;", (chat_id,))
        return dict(cur.fetchall())

def delete_custom_rp(chat_id: int, trigger: str) -> bool:
    if not DATABASE_URL: return False
    with _conn() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM custom_rp WHERE chat_id = %s AND trigger = %s;", (chat_id, trigger))
        return cur.rowcount > 0

def add_ticket(kind: str, chat_id: int, user_id: int, text: str) -> int:
    if not DATABASE_URL: return 0
    with _conn() as conn, conn.cursor() as cur:
        cur.execute("INSERT INTO tickets (kind, chat_id, user_id, text) VALUES (%s, %s, %s, %s) RETURNING id;", (kind, chat_id, user_id, text))
        return cur.fetchone()[0]

def close_ticket(ticket_id: int):
    if not DATABASE_URL: return
    with _conn() as conn, conn.cursor() as cur:
        cur.execute("UPDATE tickets SET status = 'closed' WHERE id = %s;", (ticket_id,))

def open_tickets() -> list[tuple]:
    if not DATABASE_URL: return []
    with _conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT id, kind, chat_id, user_id, text FROM tickets WHERE status = 'open' ORDER BY id;")
        return cur.fetchall()

def set_pending(user_id: int, kind: str, chat_id: int):
    if not DATABASE_URL: return
    with _conn() as conn, conn.cursor() as cur:
        cur.execute("INSERT INTO pending (user_id, kind, chat_id) VALUES (%s, %s, %s) ON CONFLICT (user_id) DO UPDATE SET kind = EXCLUDED.kind, chat_id = EXCLUDED.chat_id;", (user_id, kind, chat_id))

def pop_pending(user_id: int):
    if not DATABASE_URL: return None
    with _conn() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM pending WHERE user_id = %s RETURNING kind, chat_id;", (user_id,))
        return cur.fetchone()
