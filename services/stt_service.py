import asyncio
import io
import json
import wave
from functools import lru_cache

from fastapi import HTTPException, UploadFile
from vosk import KaldiRecognizer, Model

from services.settings import get_settings


async def transcribe_audio(audio: UploadFile) -> dict[str, str]:
    audio_bytes = await audio.read()
    if not audio_bytes:
        raise HTTPException(status_code=400, detail="Uploaded audio file is empty")

    try:
        text, sample_rate = await asyncio.to_thread(_recognize_wav, audio_bytes)
    except wave.Error as exc:
        raise HTTPException(status_code=400, detail="Only PCM WAV audio is supported") from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    return {
        "text": text,
        "language": "zh",
        "sample_rate": str(sample_rate),
    }


def _recognize_wav(audio_bytes: bytes) -> tuple[str, int]:
    model = _get_model()

    with wave.open(io.BytesIO(audio_bytes), "rb") as wav_file:
        channels = wav_file.getnchannels()
        sample_width = wav_file.getsampwidth()
        sample_rate = wav_file.getframerate()

        if channels != 1:
            raise HTTPException(status_code=400, detail="WAV must be mono audio")
        if sample_width != 2:
            raise HTTPException(status_code=400, detail="WAV must be 16-bit PCM audio")

        recognizer = KaldiRecognizer(model, sample_rate)
        recognizer.SetWords(True)

        while True:
            chunk = wav_file.readframes(4000)
            if not chunk:
                break
            recognizer.AcceptWaveform(chunk)

    result = json.loads(recognizer.FinalResult())
    return result.get("text", "").strip(), sample_rate


@lru_cache
def _get_model() -> Model:
    model_dir = get_settings().vosk_model_dir
    if not model_dir.exists():
        raise FileNotFoundError(
            f"Vosk model not found: {model_dir}. "
            "Download vosk-model-small-cn-0.22 and set VOSK_MODEL_DIR to that folder."
        )
    return Model(str(model_dir))
