from datetime import datetime
import asyncio
import json
import logging
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse

from schemas.api import (
    DeviceMessage,
    EmotionResult,
    TextChatResponse,
    TextToSpeechRequest,
    TextToSpeechResponse,
    VoiceChatResponse,
)
from services.brain_service import generate_reply
from services.emotion_service import analyze_emotion
from services.memory_service import get_recent_turns, get_user_profile, save_conversation_turn
from services.settings import get_settings
from services.stt_service import (
    accept_pcm_chunk,
    create_pcm_recognizer,
    final_pcm_result,
    transcribe_audio,
)
from services.tts_service import synthesize_speech


app = FastAPI(title="ESP32-S3 Voice Robot Server")
logger = logging.getLogger(__name__)
VOICE_END_MARKER = "__END_OF_UTTERANCE__"


@app.get("/")
def health_check():
    settings = get_settings()
    return {
        "ok": True,
        "service": settings.service_name,
        "time": datetime.now().isoformat(),
    }


@app.post("/api/device/message", response_model=TextChatResponse)
async def receive_message(data: DeviceMessage):
    device_id = data.device_id.strip()
    user_text = data.message.strip()
    if not device_id or not user_text:
        raise HTTPException(status_code=400, detail="device_id and message cannot be empty")

    emotion, reply_text, robot_mood = await _complete_text_turn(device_id, user_text)

    return TextChatResponse(
        ok=True,
        device_id=device_id,
        user_text=user_text,
        emotion=emotion,
        reply_text=reply_text,
        robot_mood=robot_mood,
        time=datetime.now().isoformat(),
    )


@app.post("/api/voice/transcribe")
async def transcribe_voice(audio: UploadFile = File(...)):
    transcript = await transcribe_audio(audio)
    return {
        "ok": True,
        "filename": audio.filename,
        "transcript": transcript,
        "time": datetime.now().isoformat(),
    }


@app.websocket("/ws/voice")
async def voice_ws(
    ws: WebSocket,
    device_id: str = "esp32s3-001",
    sample_rate: int = 16000,
):
    await ws.accept()
    recognizer = create_pcm_recognizer(sample_rate)
    pcm_buffer = bytearray()
    last_partial = ""

    await ws.send_json(
        {
            "type": "ready",
            "device_id": device_id,
            "sample_rate": sample_rate,
            "audio_format": "pcm_s16le_mono",
            "end_marker": VOICE_END_MARKER,
            "time": datetime.now().isoformat(),
        }
    )

    try:
        while True:
            message = await ws.receive()

            if message.get("type") == "websocket.disconnect":
                break

            if "bytes" in message and message["bytes"] is not None:
                chunk = message["bytes"]
                if not chunk:
                    continue

                pcm_buffer.extend(chunk)
                result = accept_pcm_chunk(recognizer, chunk)
                partial = str(result.get("partial") or result.get("text") or "")
                if partial and partial != last_partial:
                    last_partial = partial
                    await ws.send_json(
                        {
                            "type": "partial_text",
                            "text": partial,
                            "total_bytes": len(pcm_buffer),
                            "time": datetime.now().isoformat(),
                        }
                    )
                continue

            if "text" in message and message["text"] is not None:
                control = _parse_ws_control_message(message["text"])
                control_type = control.get("type")

                if control_type == "start":
                    device_id = str(control.get("device_id") or device_id).strip()
                    sample_rate = int(control.get("sample_rate") or sample_rate)
                    recognizer = create_pcm_recognizer(sample_rate)
                    pcm_buffer.clear()
                    last_partial = ""
                    await ws.send_json(
                        {
                            "type": "started",
                            "device_id": device_id,
                            "sample_rate": sample_rate,
                            "audio_format": "pcm_s16le_mono",
                            "end_marker": VOICE_END_MARKER,
                            "time": datetime.now().isoformat(),
                        }
                    )
                    continue

                if control_type == "end":
                    final_text = final_pcm_result(recognizer)
                    if not final_text and last_partial:
                        final_text = last_partial

                    await _send_voice_reply(
                        ws=ws,
                        device_id=device_id,
                        user_text=final_text,
                        total_bytes=len(pcm_buffer),
                    )

                    recognizer = create_pcm_recognizer(sample_rate)
                    pcm_buffer.clear()
                    last_partial = ""
                    continue

                if control_type == "reset":
                    recognizer = create_pcm_recognizer(sample_rate)
                    pcm_buffer.clear()
                    last_partial = ""
                    await ws.send_json({"type": "reset", "time": datetime.now().isoformat()})
                    continue

                if control_type == "ping":
                    await ws.send_json({"type": "pong", "time": datetime.now().isoformat()})
                    continue

                await ws.send_json(
                    {
                        "type": "error",
                        "message": f"Unsupported control message: {message['text']}",
                        "time": datetime.now().isoformat(),
                    }
                )
    except WebSocketDisconnect:
        logger.info("Voice websocket disconnected: device_id=%s", device_id)
    except Exception as exc:
        logger.exception("Voice websocket failed")
        await _safe_ws_send_json(
            ws,
            {
                "type": "error",
                "message": str(exc),
                "time": datetime.now().isoformat(),
            },
        )


@app.post("/api/voice/chat", response_model=VoiceChatResponse)
async def voice_chat(
    device_id: str = Form(...),
    audio: UploadFile = File(...),
    format: str = Form("wav"),
    sample_rate: int = Form(16000),
):
    _ = format, sample_rate
    device_id = device_id.strip()
    if not device_id:
        raise HTTPException(status_code=400, detail="device_id cannot be empty")

    transcript = await transcribe_audio(audio)
    user_text = str(transcript["text"]).strip()
    if not user_text:
        raise HTTPException(status_code=400, detail="No recognizable speech received")

    emotion, reply_text, robot_mood = await _complete_text_turn(device_id, user_text)
    audio_url = await _try_synthesize_speech(reply_text)

    return VoiceChatResponse(
        ok=True,
        device_id=device_id,
        user_text=user_text,
        emotion=emotion,
        reply_text=reply_text,
        robot_mood=robot_mood,
        audio_url=audio_url,
        time=datetime.now().isoformat(),
    )


@app.post("/api/voice/tts", response_model=TextToSpeechResponse)
async def text_to_speech(data: TextToSpeechRequest):
    text = data.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="text cannot be empty")

    try:
        audio_url, _audio_path = await synthesize_speech(text)
    except Exception as exc:
        logger.exception("Text-to-speech failed")
        raise HTTPException(status_code=503, detail="Text-to-speech service unavailable") from exc
    return TextToSpeechResponse(
        ok=True,
        text=text,
        audio_url=audio_url,
        time=datetime.now().isoformat(),
    )


@app.get("/api/audio/reply/{reply_id}")
def get_reply_audio(reply_id: str):
    settings = get_settings()
    audio_path = settings.audio_output_dir / reply_id

    if not audio_path.exists() or not audio_path.is_file():
        raise HTTPException(status_code=404, detail="Audio file not found")

    media_type = _guess_audio_media_type(audio_path)
    return FileResponse(audio_path, media_type=media_type, filename=audio_path.name)


async def _complete_text_turn(
    device_id: str,
    user_text: str,
) -> tuple[EmotionResult, str, str]:
    emotion = analyze_emotion(user_text)
    user_profile = get_user_profile(device_id)
    recent_turns = get_recent_turns(device_id)
    reply_text, robot_mood = await asyncio.to_thread(
        generate_reply,
        device_id=device_id,
        user_text=user_text,
        emotion=emotion,
        recent_turns=recent_turns,
        user_profile=user_profile,
    )

    save_conversation_turn(
        device_id=device_id,
        user_text=user_text,
        reply_text=reply_text,
        emotion_label=emotion.label,
    )
    return emotion, reply_text, robot_mood


async def _try_synthesize_speech(text: str) -> str | None:
    try:
        audio_url, _audio_path = await synthesize_speech(text)
        return audio_url
    except Exception:
        logger.exception("Voice chat text-to-speech failed")
        return None


def _guess_audio_media_type(path: Path) -> str:
    if path.suffix.lower() == ".mp3":
        return "audio/mpeg"
    if path.suffix.lower() == ".wav":
        return "audio/wav"
    return "application/octet-stream"


def _parse_ws_control_message(text: str) -> dict[str, object]:
    stripped = text.strip()
    if stripped == VOICE_END_MARKER:
        return {"type": "end"}

    try:
        data = json.loads(stripped)
    except json.JSONDecodeError:
        return {"type": stripped}

    if not isinstance(data, dict):
        return {"type": "unknown"}

    return data


async def _send_voice_reply(
    ws: WebSocket,
    device_id: str,
    user_text: str,
    total_bytes: int,
) -> None:
    user_text = user_text.strip()
    await ws.send_json(
        {
            "type": "final_text",
            "device_id": device_id,
            "text": user_text,
            "total_bytes": total_bytes,
            "time": datetime.now().isoformat(),
        }
    )

    if not user_text:
        await ws.send_json(
            {
                "type": "no_speech",
                "message": "No recognizable speech received",
                "total_bytes": total_bytes,
                "time": datetime.now().isoformat(),
            }
        )
        return

    emotion, reply_text, robot_mood = await _complete_text_turn(device_id, user_text)
    audio_url = await _try_synthesize_speech(reply_text)

    await ws.send_json(
        {
            "type": "reply",
            "ok": True,
            "device_id": device_id,
            "user_text": user_text,
            "emotion": _schema_to_dict(emotion),
            "reply_text": reply_text,
            "robot_mood": robot_mood,
            "audio_url": audio_url,
            "time": datetime.now().isoformat(),
        }
    )


async def _safe_ws_send_json(ws: WebSocket, data: dict[str, object]) -> None:
    try:
        await ws.send_json(data)
    except RuntimeError:
        pass


def _schema_to_dict(schema: object) -> dict[str, object]:
    if hasattr(schema, "model_dump"):
        return schema.model_dump()
    if hasattr(schema, "dict"):
        return schema.dict()
    return {}
