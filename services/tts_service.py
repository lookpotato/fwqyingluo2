from pathlib import Path
from uuid import uuid4

import asyncio
import edge_tts
from gtts import gTTS

from services.settings import get_settings


async def synthesize_speech(reply_text: str) -> tuple[str, Path]:
    settings = get_settings()
    filename = f"{uuid4().hex}.mp3"
    audio_path = settings.audio_output_dir / filename

    if settings.tts_provider.lower() == "gtts":
        await asyncio.to_thread(_save_gtts, reply_text, audio_path, settings.tts_language)
        return f"/api/audio/reply/{filename}", audio_path

    communicate = edge_tts.Communicate(
        text=reply_text,
        voice=settings.tts_voice,
        rate=settings.tts_rate,
    )
    await communicate.save(str(audio_path))

    return f"/api/audio/reply/{filename}", audio_path


def _save_gtts(reply_text: str, audio_path: Path, language: str) -> None:
    gTTS(text=reply_text, lang=language).save(str(audio_path))
