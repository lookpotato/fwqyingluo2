from dataclasses import dataclass, field
from datetime import datetime
import json
import re
import sqlite3
import threading

from services.settings import get_settings


@dataclass
class ConversationTurn:
    device_id: str
    user_text: str
    reply_text: str
    emotion_label: str
    created_at: str


@dataclass
class UserProfile:
    device_id: str
    preferred_name: str | None = None
    preferences: list[str] = field(default_factory=list)
    dislikes: list[str] = field(default_factory=list)
    facts: list[str] = field(default_factory=list)
    updated_at: str | None = None

    def to_prompt_text(self) -> str:
        parts: list[str] = []
        if self.preferred_name:
            parts.append(f"用户希望被称呼为：{self.preferred_name}")
        if self.preferences:
            parts.append("用户喜欢或偏好的事物：" + "；".join(self.preferences[:8]))
        if self.dislikes:
            parts.append("用户不喜欢或需要避开的事物：" + "；".join(self.dislikes[:8]))
        if self.facts:
            parts.append("关于用户的长期信息：" + "；".join(self.facts[:8]))
        return "\n".join(parts) if parts else "暂时还没有可靠的长期用户画像。"


_DB_LOCK = threading.Lock()
_SCHEMA_READY = False
_MAX_PROFILE_ITEMS = 30


def get_recent_turns(device_id: str, limit: int = 6) -> list[ConversationTurn]:
    _ensure_schema()
    clean_device_id = device_id.strip()
    safe_limit = max(1, min(limit, 20))

    with _DB_LOCK, _connect() as conn:
        rows = conn.execute(
            """
            SELECT device_id, user_text, reply_text, emotion_label, created_at
            FROM conversation_turns
            WHERE device_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (clean_device_id, safe_limit),
        ).fetchall()

    rows.reverse()
    return [ConversationTurn(*row) for row in rows]


def get_user_profile(device_id: str) -> UserProfile:
    _ensure_schema()
    clean_device_id = device_id.strip()

    with _DB_LOCK, _connect() as conn:
        row = conn.execute(
            """
            SELECT device_id, preferred_name, preferences_json, dislikes_json, facts_json, updated_at
            FROM user_profiles
            WHERE device_id = ?
            """,
            (clean_device_id,),
        ).fetchone()

    if row is None:
        return UserProfile(device_id=clean_device_id)

    return UserProfile(
        device_id=row[0],
        preferred_name=row[1],
        preferences=_load_json_list(row[2]),
        dislikes=_load_json_list(row[3]),
        facts=_load_json_list(row[4]),
        updated_at=row[5],
    )


def save_conversation_turn(
    device_id: str,
    user_text: str,
    reply_text: str,
    emotion_label: str,
) -> None:
    _ensure_schema()
    clean_device_id = device_id.strip()
    clean_user_text = user_text.strip()
    clean_reply_text = reply_text.strip()
    created_at = datetime.now().isoformat()

    with _DB_LOCK, _connect() as conn:
        conn.execute(
            """
            INSERT INTO conversation_turns
                (device_id, user_text, reply_text, emotion_label, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                clean_device_id,
                clean_user_text,
                clean_reply_text,
                emotion_label,
                created_at,
            ),
        )
        _upsert_profile_from_text(conn, clean_device_id, clean_user_text, created_at)
        conn.execute(
            """
            DELETE FROM conversation_turns
            WHERE id IN (
                SELECT id
                FROM conversation_turns
                WHERE device_id = ?
                ORDER BY id DESC
                LIMIT -1 OFFSET 200
            )
            """,
            (clean_device_id,),
        )
        conn.commit()


def _upsert_profile_from_text(
    conn: sqlite3.Connection,
    device_id: str,
    user_text: str,
    updated_at: str,
) -> None:
    learned = _extract_profile_updates(user_text)
    if not learned:
        return

    current = _get_user_profile_locked(conn, device_id)
    preferred_name = learned.get("preferred_name") or current.preferred_name
    preferences = _merge_items(current.preferences, learned.get("preferences", []))
    dislikes = _merge_items(current.dislikes, learned.get("dislikes", []))
    facts = _merge_items(current.facts, learned.get("facts", []))

    conn.execute(
        """
        INSERT INTO user_profiles
            (device_id, preferred_name, preferences_json, dislikes_json, facts_json, updated_at)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(device_id) DO UPDATE SET
            preferred_name = excluded.preferred_name,
            preferences_json = excluded.preferences_json,
            dislikes_json = excluded.dislikes_json,
            facts_json = excluded.facts_json,
            updated_at = excluded.updated_at
        """,
        (
            device_id,
            preferred_name,
            json.dumps(preferences, ensure_ascii=False),
            json.dumps(dislikes, ensure_ascii=False),
            json.dumps(facts, ensure_ascii=False),
            updated_at,
        ),
    )


def _get_user_profile_locked(conn: sqlite3.Connection, device_id: str) -> UserProfile:
    row = conn.execute(
        """
        SELECT device_id, preferred_name, preferences_json, dislikes_json, facts_json, updated_at
        FROM user_profiles
        WHERE device_id = ?
        """,
        (device_id,),
    ).fetchone()
    if row is None:
        return UserProfile(device_id=device_id)

    return UserProfile(
        device_id=row[0],
        preferred_name=row[1],
        preferences=_load_json_list(row[2]),
        dislikes=_load_json_list(row[3]),
        facts=_load_json_list(row[4]),
        updated_at=row[5],
    )


def _extract_profile_updates(user_text: str) -> dict[str, object]:
    text = " ".join(user_text.strip().split())
    if _looks_like_question(text):
        return {}

    updates: dict[str, object] = {}

    name = _first_match(
        text,
        (
            r"(?:我叫|我的名字叫|我的名字是|叫我|以后叫我)([\u4e00-\u9fa5A-Za-z0-9_-]{1,12})",
        ),
    )
    if name:
        updates["preferred_name"] = name
        updates.setdefault("facts", []).append(f"用户名字或称呼是{name}")

    likes = _extract_items(text, (r"我(?:很|超|特别)?(?:喜欢|爱)([^，。！？,.!?]{1,30})",))
    dislikes = _extract_items(
        text,
        (
            r"我(?:不喜欢|讨厌|不爱)([^，。！？,.!?]{1,30})",
            r"(?:不喜欢|讨厌|不爱)([^，。！？,.!?]{1,30})",
        ),
    )
    facts = _extract_items(
        text,
        (
            r"我是([^，。！？,.!?]{1,30})",
            r"我在([^，。！？,.!?]{1,30})(?:工作|上学|学习|生活)",
            r"我家(?:在|住在)([^，。！？,.!?]{1,30})",
        ),
    )

    if likes:
        updates["preferences"] = [f"喜欢{item}" for item in likes]
    if dislikes:
        updates["dislikes"] = [f"不喜欢{item}" for item in dislikes]
    if facts:
        updates.setdefault("facts", []).extend(facts)

    return updates


def _looks_like_question(text: str) -> bool:
    return "?" in text or "？" in text or any(word in text for word in ("什么", "为什么", "怎么", "吗", "呢", "能不能"))


def _first_match(text: str, patterns: tuple[str, ...]) -> str | None:
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return _clean_memory_item(match.group(1))
    return None


def _extract_items(text: str, patterns: tuple[str, ...]) -> list[str]:
    items: list[str] = []
    for pattern in patterns:
        for match in re.finditer(pattern, text):
            item = _clean_memory_item(match.group(1))
            if item:
                items.append(item)
    return items


def _clean_memory_item(item: str) -> str:
    item = re.sub(r"^(叫|是|吃|玩|看|听|去)", "", item.strip())
    item = re.sub(r"(这件事|这个|那个|的时候)$", "", item)
    return item[:40].strip()


def _merge_items(existing: list[str], learned: object) -> list[str]:
    merged = list(existing)
    for item in learned if isinstance(learned, list) else []:
        clean_item = str(item).strip()
        if clean_item and clean_item not in merged:
            merged.append(clean_item)
    return merged[-_MAX_PROFILE_ITEMS:]


def _load_json_list(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    return [str(item) for item in data if str(item).strip()]


def _connect() -> sqlite3.Connection:
    settings = get_settings()
    return sqlite3.connect(settings.memory_db_path)


def _ensure_schema() -> None:
    global _SCHEMA_READY
    if _SCHEMA_READY:
        return

    with _DB_LOCK, _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS conversation_turns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                device_id TEXT NOT NULL,
                user_text TEXT NOT NULL,
                reply_text TEXT NOT NULL,
                emotion_label TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_conversation_turns_device_id_id
            ON conversation_turns (device_id, id)
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS user_profiles (
                device_id TEXT PRIMARY KEY,
                preferred_name TEXT,
                preferences_json TEXT NOT NULL DEFAULT '[]',
                dislikes_json TEXT NOT NULL DEFAULT '[]',
                facts_json TEXT NOT NULL DEFAULT '[]',
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.commit()
        _SCHEMA_READY = True
