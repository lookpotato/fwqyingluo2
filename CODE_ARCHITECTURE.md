# 代码架构说明

本文档说明当前服务端代码结构、各模块职责、接口边界，以及后续开发时应该优先修改的位置。

## 1. 当前项目结构

```text
fwqyingluo2/
  app.py
  requirements.txt
  Dockerfile
  docker-compose.yml
  CODE_ARCHITECTURE.md
  ESP32_S3_VOICE_ROBOT_ARCHITECTURE.md
  WEBSOCKET_VOICE_PROTOCOL.md
  schemas/
    __init__.py
    api.py
  services/
    __init__.py
    settings.py
    personality_service.py
    emotion_service.py
    memory_service.py
    brain_service.py
    stt_service.py
    tts_service.py
    realtime_session.py
  data/
    personalities/
      default_robot.yaml
  models/
    vosk-model-small-cn-0.22/
  audio_outputs/
    .gitkeep
```

## 2. 服务入口

主入口文件是：

```text
app.py
```

本地启动命令：

```bash
uvicorn app:app --host 0.0.0.0 --port 8000
```

Dockerfile 当前也通过同一个入口启动：

```dockerfile
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
```

`app.py` 只负责创建 FastAPI 应用、声明 HTTP/WebSocket 接口、串联 `services/` 中的业务能力。语音识别、大模型回复、语音合成、人格配置和记忆逻辑都应继续放在 `services/` 目录中。

## 3. 当前接口

```text
GET       /
POST      /api/device/message
POST      /api/voice/transcribe
POST      /api/voice/chat
POST      /api/voice/tts
GET       /api/audio/reply/{reply_id}
WebSocket /ws/voice
```

### 3.1 健康检查

```text
GET /
```

返回服务状态、服务名和当前时间。

### 3.2 文本对话

```text
POST /api/device/message
```

用途：不经过麦克风和音频链路，直接测试“情绪分析 -> 记忆读取 -> 大脑回复 -> 保存对话”的文本链路。

请求体由 `schemas.api.DeviceMessage` 定义：

```json
{
  "device_id": "esp32s3-001",
  "message": "你好"
}
```

返回体由 `schemas.api.TextChatResponse` 定义。

### 3.3 音频转文字

```text
POST /api/voice/transcribe
Content-Type: multipart/form-data
```

用途：上传 WAV 音频，调用本地 Vosk 模型识别中文文本。

当前限制：

- 只支持 PCM WAV。
- 必须是单声道。
- 必须是 16-bit PCM。
- 模型目录默认是 `models/vosk-model-small-cn-0.22`，可通过 `VOSK_MODEL_DIR` 覆盖。

### 3.4 完整语音对话

```text
POST /api/voice/chat
Content-Type: multipart/form-data
```

表单字段：

```text
device_id: esp32s3-001
audio: voice.wav
format: wav
sample_rate: 16000
```

处理流程：

```text
上传音频 -> STT -> 情绪分析 -> 读取近期对话 -> 大脑生成回复 -> TTS -> 保存对话 -> 返回 JSON
```

返回中包含 `reply_text` 和 `audio_url`。如果 TTS 失败，接口仍会返回文本回复，`audio_url` 为 `null`。

### 3.5 文本转语音

```text
POST /api/voice/tts
```

用途：单独测试 TTS 链路。请求体由 `TextToSpeechRequest` 定义，返回体由 `TextToSpeechResponse` 定义。

### 3.6 获取回复音频

```text
GET /api/audio/reply/{reply_id}
```

用途：下载或播放 `audio_outputs/` 目录中的已生成音频文件。当前会根据扩展名返回 `audio/mpeg`、`audio/wav` 或 `application/octet-stream`。

### 3.7 实时语音 WebSocket

```text
WebSocket /ws/voice
```

用途：接收 ESP32-S3 或测试客户端发送的 PCM 二进制音频帧，边接收边输出局部识别文本，收到结束标记后生成最终回复。

协议细节见：

```text
WEBSOCKET_VOICE_PROTOCOL.md
```

当前音频格式：

```text
PCM signed 16-bit little-endian, mono, 16000 Hz
```

默认结束标记：

```text
__END_OF_UTTERANCE__
```

## 4. schemas 目录

目录：

```text
schemas/
```

职责：定义接口请求和响应的数据格式。

当前主要模型：

- `DeviceMessage`：文本对话请求。
- `EmotionResult`：情绪分析结果。
- `TextChatResponse`：文本对话响应。
- `VoiceChatResponse`：语音对话响应，比文本响应多 `audio_url`。
- `TextToSpeechRequest`：TTS 请求。
- `TextToSpeechResponse`：TTS 响应。

以后如果接口字段要变化，优先修改 `schemas/api.py`，再同步修改 `app.py` 中对应接口。

## 5. services 目录

目录：

```text
services/
```

职责：承载业务逻辑和外部能力封装。

### 5.1 settings.py

统一读取环境变量，并确保运行目录存在。

当前配置项：

```text
PERSONALITY_ID
AUDIO_OUTPUT_DIR
MEMORY_DB_PATH
DEEPSEEK_API_KEY
DEEPSEEK_BASE_URL
DEEPSEEK_MODEL
DEEPSEEK_REASONING_EFFORT
DEEPSEEK_THINKING_ENABLED
DEEPSEEK_TIMEOUT_SECONDS
TTS_PROVIDER
TTS_LANGUAGE
TTS_VOICE
TTS_RATE
TTS_CONNECT_TIMEOUT_SECONDS
TTS_READ_TIMEOUT_SECONDS
VOSK_MODEL_DIR
```

新增配置时优先放在这里，不要在各个业务文件中分散调用 `os.getenv()`。

### 5.2 personality_service.py

读取机器人固定人格配置。

默认读取：

```text
data/personalities/default_robot.yaml
```

如果后续支持多个机器人人格，应继续扩展此模块和 `data/personalities/` 目录。

### 5.3 emotion_service.py

对用户文本进行简单情绪和意图分析。

当前是规则版，用于跑通链路。后续可以替换为小模型或大模型结构化输出，但对外最好继续返回 `EmotionResult`，避免影响其他模块。

### 5.4 memory_service.py

保存和读取近期对话。

当前实现是内存列表：

- `get_recent_turns(device_id, limit=6)`
- `save_conversation_turn(...)`

服务重启后记忆会丢失。`MEMORY_DB_PATH` 已经预留，后续升级 SQLite 时主要修改这个文件。

### 5.5 brain_service.py

机器人“大脑”，负责生成回复文本和机器人语气状态。

当前行为：

- 如果配置了 `DEEPSEEK_API_KEY`，使用 OpenAI SDK 以 `DEEPSEEK_BASE_URL` 调用 DeepSeek 兼容接口。
- 如果未配置 Key，或大模型调用失败，则返回本地兜底回复。
- 回复生成会组合人格配置、设备 ID、情绪结果和近期对话。

后续如果要接入其他模型，优先改这个文件，并保持 `generate_reply(...) -> tuple[str, str]` 这个边界稳定。

### 5.6 stt_service.py

语音转文字。

当前使用 Vosk 本地模型：

- `transcribe_audio(audio)`：处理上传的 PCM WAV。
- `transcribe_pcm(audio_bytes, sample_rate)`：处理原始 PCM。
- `create_pcm_recognizer(sample_rate)`：为 WebSocket 流式识别创建识别器。
- `accept_pcm_chunk(recognizer, chunk)`：接收音频分片并返回局部结果。
- `final_pcm_result(recognizer)`：返回最终识别结果。

后续如果要改成云端 STT 或更大的本地模型，主要改这里。

### 5.7 tts_service.py

文字转语音。

当前支持：

- `edge_tts`，默认 provider。
- `gTTS`，通过 `TTS_PROVIDER=gtts` 启用。

生成文件统一保存到：

```text
audio_outputs/
```

返回 URL 格式：

```text
/api/audio/reply/{filename}.mp3
```

## 6. 数据和模型目录

### 6.1 data/

运行数据目录。当前包含：

```text
data/personalities/default_robot.yaml
```

后续 SQLite 记忆数据库建议放在：

```text
data/memory.sqlite
```

### 6.2 models/

本地模型目录。当前 Vosk 中文小模型放在：

```text
models/vosk-model-small-cn-0.22/
```

如果部署到 Docker，需要确保 `models/` 已挂载到容器内 `/app/models`。

### 6.3 audio_outputs/

服务端生成的回复音频目录。Docker Compose 已将其挂载出来，方便重启后继续访问已生成文件。

## 7. Docker 与依赖

### 7.1 requirements.txt

当前主要依赖：

```text
fastapi
uvicorn[standard]
pydantic
python-multipart
python-dotenv
openai
edge-tts
gTTS
vosk
```

新增 Python 包时先更新 `requirements.txt`，再确认 Docker 镜像能构建。

### 7.2 Dockerfile

使用 `python:3.11-slim`，安装依赖后复制项目代码，暴露 8000 端口并启动 FastAPI。

### 7.3 docker-compose.yml

当前服务名：

```text
fwqyingluo2
```

已挂载：

```text
./data:/app/data
./audio_outputs:/app/audio_outputs
./models:/app/models
```

已注入 DeepSeek、TTS、Vosk 等环境变量。

## 8. 主要请求链路

### 8.1 文本链路

```text
POST /api/device/message
  -> analyze_emotion()
  -> get_recent_turns()
  -> generate_reply()
  -> save_conversation_turn()
  -> TextChatResponse
```

### 8.2 HTTP 语音链路

```text
POST /api/voice/chat
  -> transcribe_audio()
  -> analyze_emotion()
  -> get_recent_turns()
  -> generate_reply()
  -> synthesize_speech()
  -> save_conversation_turn()
  -> VoiceChatResponse
```

### 8.3 WebSocket 实时链路

```text
WebSocket /ws/voice
  -> create_pcm_recognizer()
  -> accept_pcm_chunk() 多次
  -> final_pcm_result()
  -> analyze_emotion()
  -> get_recent_turns()
  -> generate_reply()
  -> synthesize_speech()
  -> save_conversation_turn()
  -> reply 消息
```

## 9. 后续开发改哪里

### 修改接口字段

```text
schemas/api.py
app.py
```

### 修改机器人性格

```text
data/personalities/default_robot.yaml
services/personality_service.py
```

### 调整大模型供应商或提示词

```text
services/brain_service.py
services/settings.py
docker-compose.yml
```

### 调整语音识别

```text
services/stt_service.py
services/settings.py
models/
```

### 调整语音合成

```text
services/tts_service.py
services/settings.py
docker-compose.yml
```

### 做长期记忆

```text
services/memory_service.py
services/settings.py
data/memory.sqlite
docker-compose.yml
```

### 调整 WebSocket 协议

```text
app.py
WEBSOCKET_VOICE_PROTOCOL.md
services/stt_service.py
```

## 10. 当前状态

当前已经完成：

- FastAPI 服务骨架。
- 文本对话链路。
- HTTP WAV 上传识别链路。
- HTTP 完整语音对话链路。
- 单独 TTS 测试接口。
- WebSocket PCM 分片识别与回复链路。
- Vosk 本地中文 STT。
- Edge TTS/gTTS 语音合成。
- DeepSeek 兼容大模型调用和本地兜底回复。
- 人格配置文件和近期内存记忆。
- Docker Compose 的数据、音频、模型目录挂载。

当前仍需注意：

- 记忆仍是进程内临时记忆，重启会丢失。
- WebSocket 已有基础协议，但还需要结合 ESP32-S3 固件做端到端压测。
- STT 目前只严格支持单声道 16-bit PCM WAV 或原始 PCM。
- 代码中部分历史中文字符串可能存在编码问题，建议后续统一清理为 UTF-8。

## 11. 建议下一步

优先做两件事：

1. 把 `memory_service.py` 升级为 SQLite，使用 `MEMORY_DB_PATH` 持久化保存对话。
2. 用真实 ESP32-S3 客户端压测 `/ws/voice`，确认分片大小、结束标记、延迟和断线重连策略。
