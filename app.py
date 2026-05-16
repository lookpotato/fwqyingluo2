from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from schemas.api import (
    DeviceMessage,
    TextChatResponse,
    TextToSpeechRequest,
    TextToSpeechResponse,
    VoiceChatResponse,
)
from services.brain_service import generate_reply
from services.emotion_service import analyze_emotion
from services.memory_service import get_recent_turns, save_conversation_turn
from services.settings import get_settings
from services.stt_service import transcribe_audio
from services.tts_service import synthesize_speech

app = FastAPI(title="ESP32-S3 Voice Robot Server")


@app.get("/")
def health_check():
    settings = get_settings()
    return {
        "ok": True,
        "service": settings.service_name,
        "time": datetime.now().isoformat(),
    }


@app.post("/api/device/message", response_model=TextChatResponse)
def receive_message(data: DeviceMessage):
    emotion = analyze_emotion(data.message)
    recent_turns = get_recent_turns(data.device_id)
    reply_text, robot_mood = generate_reply(
        device_id=data.device_id,
        user_text=data.message,
        emotion=emotion,
        recent_turns=recent_turns,
    )

    save_conversation_turn(
        device_id=data.device_id,
        user_text=data.message,
        reply_text=reply_text,
        emotion_label=emotion.label,
    )

    return TextChatResponse(
        ok=True,
        device_id=data.device_id,
        user_text=data.message,
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


@app.post("/api/voice/chat", response_model=VoiceChatResponse)
async def voice_chat(
    device_id: str = Form(...),
    audio: UploadFile = File(...),
    format: str = Form("wav"),
    sample_rate: int = Form(16000),
):
    _ = format, sample_rate
    transcript = await transcribe_audio(audio)
    user_text = transcript["text"]

    emotion = analyze_emotion(user_text)
    recent_turns = get_recent_turns(device_id)
    reply_text, robot_mood = generate_reply(
        device_id=device_id,
        user_text=user_text,
        emotion=emotion,
        recent_turns=recent_turns,
    )
    audio_url, _audio_path = await synthesize_speech(reply_text)

    save_conversation_turn(
        device_id=device_id,
        user_text=user_text,
        reply_text=reply_text,
        emotion_label=emotion.label,
    )

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
    audio_url, _audio_path = await synthesize_speech(data.text)
    return TextToSpeechResponse(
        ok=True,
        text=data.text,
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


def _guess_audio_media_type(path: Path) -> str:
    if path.suffix.lower() == ".mp3":
        return "audio/mpeg"
    if path.suffix.lower() == ".wav":
        return "audio/wav"
    return "application/octet-stream"
