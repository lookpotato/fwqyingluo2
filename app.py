from fastapi import FastAPI, Request
from pydantic import BaseModel
from datetime import datetime

app = FastAPI()


class DeviceMessage(BaseModel):
    device_id: str
    message: str


@app.get("/")
def health_check():
    return {
        "ok": True,
        "service": "esp32-server",
        "time": datetime.now().isoformat()
    }


@app.post("/api/device/message")
def receive_message(data: DeviceMessage):
    print("收到 ESP32 消息：", data)

    return {
        "ok": True,
        "reply": f"服务器已收到：{data.message}",
        "device_id": data.device_id,
        "time": datetime.now().isoformat()
    }
