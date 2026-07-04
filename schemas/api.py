from pydantic import BaseModel, Field


class DeviceMessage(BaseModel):
    device_id: str = Field(..., examples=["esp32s3-001"], min_length=1)
    message: str = Field(..., examples=["你好"], min_length=1)


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


class TextToSpeechRequest(BaseModel):
    text: str = Field(..., examples=["你好，我是影落，很高兴认识你。"], min_length=1)


class TextToSpeechResponse(BaseModel):
    ok: bool
    text: str
    audio_url: str
    time: str
