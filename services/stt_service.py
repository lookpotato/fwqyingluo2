from fastapi import UploadFile


async def transcribe_audio(audio: UploadFile) -> dict[str, str]:
    # 后续这里接入 OpenAI Audio transcription。
    # 当前先返回占位文字，确保接口结构和 ESP32-S3 上传链路可以先调通。
    filename = audio.filename or "unknown-audio"
    return {
        "text": f"已收到音频文件：{filename}。语音识别模块等待接入。",
        "language": "zh",
    }

