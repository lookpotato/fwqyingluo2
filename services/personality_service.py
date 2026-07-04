from pathlib import Path

from services.settings import get_settings


PERSONALITY_DIR = Path("data/personalities")
DEFAULT_PERSONALITY = (
    "你是影落，一个住在 ESP32-S3 机器人身体里的中文语音伙伴。\n"
    "你的表达温柔、机灵、有一点点俏皮，但不卖萌过度。\n"
    "回答要简短、自然、适合语音播放。"
)


def load_personality_text(personality_id: str | None = None) -> str:
    settings = get_settings()
    selected_id = personality_id or settings.personality_id
    personality_path = PERSONALITY_DIR / f"{selected_id}.yaml"

    if not personality_path.exists():
        return DEFAULT_PERSONALITY

    text = personality_path.read_text(encoding="utf-8").strip()
    return text or DEFAULT_PERSONALITY
