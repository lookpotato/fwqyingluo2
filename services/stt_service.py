import asyncio
import io
import json
import wave
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

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


def create_pcm_recognizer(sample_rate: int = 16000) -> Any:
    if _stt_provider() == "sherpa":
        return _create_sherpa_pcm_recognizer(sample_rate)

    recognizer = KaldiRecognizer(_get_model(), sample_rate)
    recognizer.SetWords(True)
    return recognizer


def accept_pcm_chunk(recognizer: Any, chunk: bytes) -> dict[str, str | bool]:
    if isinstance(recognizer, SherpaPcmRecognizer):
        return recognizer.accept_chunk(chunk)

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


def final_pcm_result(recognizer: Any) -> str:
    if isinstance(recognizer, SherpaPcmRecognizer):
        return recognizer.final_result()

    result = json.loads(recognizer.FinalResult())
    return result.get("text", "").strip()


def _recognize_wav(audio_bytes: bytes) -> tuple[str, int]:
    with wave.open(io.BytesIO(audio_bytes), "rb") as wav_file:
        channels = wav_file.getnchannels()
        sample_width = wav_file.getsampwidth()
        sample_rate = wav_file.getframerate()

        if channels != 1:
            raise HTTPException(status_code=400, detail="WAV must be mono audio")
        if sample_width != 2:
            raise HTTPException(status_code=400, detail="WAV must be 16-bit PCM audio")

        if _stt_provider() == "sherpa":
            recognizer = _create_sherpa_pcm_recognizer(sample_rate)
        else:
            recognizer = KaldiRecognizer(_get_model(), sample_rate)
            recognizer.SetWords(True)

        while True:
            chunk = wav_file.readframes(4000)
            if not chunk:
                break
            if isinstance(recognizer, SherpaPcmRecognizer):
                recognizer.accept_chunk(chunk)
            else:
                recognizer.AcceptWaveform(chunk)

    return final_pcm_result(recognizer), sample_rate


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


@dataclass
class SherpaPcmRecognizer:
    recognizer: Any
    stream: Any
    sample_rate: int
    last_text: str = ""

    def accept_chunk(self, chunk: bytes) -> dict[str, str | bool]:
        samples = _pcm_s16le_to_float32(chunk)
        if samples.size == 0:
            return {"accepted": False, "partial": self.last_text}

        self.stream.accept_waveform(self.sample_rate, samples)
        while self.recognizer.is_ready(self.stream):
            self.recognizer.decode_stream(self.stream)

        text = self.recognizer.get_result(self.stream).strip()
        if text:
            self.last_text = text

        accepted = False
        if hasattr(self.recognizer, "is_endpoint") and self.recognizer.is_endpoint(self.stream):
            accepted = True
            if hasattr(self.recognizer, "reset"):
                self.recognizer.reset(self.stream)

        return {
            "accepted": accepted,
            "text" if accepted else "partial": self.last_text,
        }

    def final_result(self) -> str:
        import numpy as np

        tail_padding = np.zeros(int(0.66 * self.sample_rate), dtype=np.float32)
        self.stream.accept_waveform(self.sample_rate, tail_padding)
        self.stream.input_finished()

        while self.recognizer.is_ready(self.stream):
            self.recognizer.decode_stream(self.stream)

        text = self.recognizer.get_result(self.stream).strip()
        return text or self.last_text


def _stt_provider() -> str:
    return get_settings().stt_provider.lower().strip()


def _create_sherpa_pcm_recognizer(sample_rate: int) -> SherpaPcmRecognizer:
    recognizer = _get_sherpa_recognizer()
    return SherpaPcmRecognizer(
        recognizer=recognizer,
        stream=recognizer.create_stream(),
        sample_rate=sample_rate,
    )


@lru_cache
def _get_sherpa_recognizer() -> Any:
    try:
        import sherpa_onnx
    except ImportError as exc:
        raise FileNotFoundError(
            "sherpa-onnx is not installed. Run: pip install sherpa-onnx==1.13.3"
        ) from exc

    settings = get_settings()
    model_dir = settings.sherpa_model_dir
    tokens = model_dir / "tokens.txt"
    model = _find_sherpa_ctc_model(model_dir)

    if not tokens.exists():
        raise FileNotFoundError(f"sherpa tokens.txt not found: {tokens}")
    if model is None:
        raise FileNotFoundError(
            f"sherpa CTC model not found in {model_dir}. "
            "Download and extract sherpa-onnx-streaming-zipformer-ctc-zh-int8-2025-06-30."
        )

    return sherpa_onnx.OnlineRecognizer.from_zipformer2_ctc(
        tokens=str(tokens),
        model=str(model),
        num_threads=settings.sherpa_num_threads,
        provider=settings.sherpa_provider,
        sample_rate=16000,
        feature_dim=80,
        decoding_method="greedy_search",
    )


def _find_sherpa_ctc_model(model_dir: Path) -> Path | None:
    preferred_names = (
        "ctc.int8.onnx",
        "ctc.onnx",
        "model.int8.onnx",
        "model.onnx",
    )
    for name in preferred_names:
        candidate = model_dir / name
        if candidate.exists():
            return candidate

    onnx_files = sorted(model_dir.glob("*.onnx"))
    for candidate in onnx_files:
        if "ctc" in candidate.name.lower():
            return candidate
    return onnx_files[0] if onnx_files else None


def _pcm_s16le_to_float32(chunk: bytes) -> Any:
    import numpy as np

    usable_length = len(chunk) - (len(chunk) % 2)
    if usable_length <= 0:
        return np.array([], dtype=np.float32)
    samples = np.frombuffer(chunk[:usable_length], dtype=np.int16)
    return samples.astype(np.float32) / 32768.0
