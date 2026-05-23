from functools import lru_cache
from pathlib import Path
from pydantic import BaseModel
from dotenv import load_dotenv
import os


load_dotenv()


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


class Settings(BaseModel):
    service_name: str = "esp32-voice-robot"
    personality_id: str = os.getenv("PERSONALITY_ID", "default_robot")
    audio_output_dir: Path = Path(os.getenv("AUDIO_OUTPUT_DIR", "audio_outputs"))
    memory_db_path: Path = Path(os.getenv("MEMORY_DB_PATH", "data/memory.sqlite"))
    deepseek_api_key: str | None = os.getenv("DEEPSEEK_API_KEY")
    deepseek_base_url: str = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    deepseek_model: str = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-pro")
    deepseek_reasoning_effort: str = os.getenv("DEEPSEEK_REASONING_EFFORT", "high")
    deepseek_thinking_enabled: bool = _env_bool("DEEPSEEK_THINKING_ENABLED", True)
    deepseek_timeout_seconds: float = float(os.getenv("DEEPSEEK_TIMEOUT_SECONDS", "30"))
    tts_provider: str = os.getenv("TTS_PROVIDER", "edge")
    tts_language: str = os.getenv("TTS_LANGUAGE", "zh-CN")
    tts_voice: str = os.getenv("TTS_VOICE", "zh-CN-XiaoxiaoNeural")
    tts_rate: str = os.getenv("TTS_RATE", "+0%")
    tts_connect_timeout_seconds: float = float(os.getenv("TTS_CONNECT_TIMEOUT_SECONDS", "5"))
    tts_read_timeout_seconds: float = float(os.getenv("TTS_READ_TIMEOUT_SECONDS", "15"))
    vosk_model_dir: Path = Path(os.getenv("VOSK_MODEL_DIR", "models/vosk-model-small-cn-0.22"))


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.audio_output_dir.mkdir(parents=True, exist_ok=True)
    settings.memory_db_path.parent.mkdir(parents=True, exist_ok=True)
    return settings
