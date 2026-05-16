from pydantic import BaseModel, Field


class DeviceMessage(BaseModel):
    device_id: str = Field(..., examples=["esp32s3-001"])
    message: str = Field(..., examples=["你好"])


class EmotionResult(BaseModel):
    label: str
    intensity: float
    intent: str
    need_comfort: bool
    safety_risk: str


class TextChatResponse(BaseModel):
    ok: bool
    device_id: str
    user_text: str
    emotion: EmotionResult
    reply_text: str
    robot_mood: str
    time: str


class VoiceChatResponse(TextChatResponse):
    audio_url: str | None = None

