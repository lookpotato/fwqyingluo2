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


async def transcribe_pcm(
    audio_bytes: bytes,
    sample_rate: int = 16000,
) -> dict[str, str]:
    if not audio_bytes:
        raise HTTPException(status_code=400, detail="PCM audio is empty")

    try:
        text = await asyncio.to_thread(_recognize_pcm, audio_bytes, sample_rate)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    return {
        "text": text,
        "language": "zh",
        "sample_rate": str(sample_rate),
    }


def create_pcm_recognizer(sample_rate: int = 16000) -> KaldiRecognizer:
    recognizer = KaldiRecognizer(_get_model(), sample_rate)
    recognizer.SetWords(True)
    return recognizer


def accept_pcm_chunk(recognizer: KaldiRecognizer, chunk: bytes) -> dict[str, str | bool]:
    accepted = recognizer.AcceptWaveform(chunk)
    if accepted:
        result = json.loads(recognizer.Result())
        return {
            "accepted": True,
            "text": result.get("text", "").strip(),
        }

    partial = json.loads(recognizer.PartialResult())
    return {
        "accepted": False,
        "partial": partial.get("partial", "").strip(),
    }


def final_pcm_result(recognizer: KaldiRecognizer) -> str:
    result = json.loads(recognizer.FinalResult())
    return result.get("text", "").strip()


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


def _recognize_pcm(audio_bytes: bytes, sample_rate: int) -> str:
    recognizer = create_pcm_recognizer(sample_rate)
    for start in range(0, len(audio_bytes), 4000):
        recognizer.AcceptWaveform(audio_bytes[start : start + 4000])
    return final_pcm_result(recognizer)


@lru_cache
def _get_model() -> Model:
    model_dir = get_settings().vosk_model_dir
    if not model_dir.exists():
        raise FileNotFoundError(
            f"Vosk model not found: {model_dir}. "
            "Download vosk-model-small-cn-0.22 and set VOSK_MODEL_DIR to that folder."
        )
    return Model(str(model_dir))
