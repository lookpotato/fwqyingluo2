from pathlib import Path
from uuid import uuid4

from services.settings import get_settings


def synthesize_speech(reply_text: str) -> tuple[str, Path | None]:
    # 后续这里接入 OpenAI Text to speech。
    # 当前不生成真实音频，先保留统一返回结构。
    get_settings()
    _ = reply_text
    return f"/api/audio/reply/{uuid4().hex}.mp3", None

