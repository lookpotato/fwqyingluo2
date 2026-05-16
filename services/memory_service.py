from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class ConversationTurn:
    device_id: str
    user_text: str
    reply_text: str
    emotion_label: str
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())


_RECENT_TURNS: list[ConversationTurn] = []


def get_recent_turns(device_id: str, limit: int = 6) -> list[ConversationTurn]:
    turns = [turn for turn in _RECENT_TURNS if turn.device_id == device_id]
    return turns[-limit:]


def save_conversation_turn(
    device_id: str,
    user_text: str,
    reply_text: str,
    emotion_label: str,
) -> None:
    _RECENT_TURNS.append(
        ConversationTurn(
            device_id=device_id,
            user_text=user_text,
            reply_text=reply_text,
            emotion_label=emotion_label,
        )
    )

    if len(_RECENT_TURNS) > 200:
        del _RECENT_TURNS[:100]

