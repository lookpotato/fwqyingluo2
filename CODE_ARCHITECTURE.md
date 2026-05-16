# 代码架构说明

这份文档只解释当前项目的代码结构：主文件是谁、每个目录放什么、后续开发某个功能应该改哪里。

## 1. 项目当前结构

```text
fwqyingluo2/
  app.py
  Dockerfile
  docker-compose.yml
  ESP32_S3_VOICE_ROBOT_ARCHITECTURE.md
  CODE_ARCHITECTURE.md
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
  data/
    personalities/
      default_robot.yaml
  audio_outputs/
    .gitkeep
```

## 2. 主文件

主文件是：

```text
app.py
```

服务器启动命令仍然是：

```bash
uvicorn app:app --host 0.0.0.0 --port 8000
```

Dockerfile 里也是启动这个文件：

```dockerfile
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
```

以后你要找“接口在哪里”，先看 `app.py`。

## 3. app.py 负责什么

`app.py` 只负责三件事：

1. 创建 FastAPI 应用。
2. 定义 HTTP 接口。
3. 调用 `services/` 里面的功能模块。

它不应该放太多复杂业务逻辑。比如语音识别、大模型回答、人格加载、记忆保存，都不要直接写死在 `app.py` 里。

当前接口：

```text
GET  /
POST /api/device/message
POST /api/voice/transcribe
POST /api/voice/chat
GET  /api/audio/reply/{reply_id}
```

## 4. schemas 目录

目录：

```text
schemas/
```

作用：放接口请求和响应的数据格式。

当前文件：

```text
schemas/api.py
```

里面定义了：

- `DeviceMessage`：ESP32-S3 发来的文本消息。
- `EmotionResult`：情绪识别结果。
- `TextChatResponse`：文本聊天接口返回格式。
- `VoiceChatResponse`：语音聊天接口返回格式。

以后如果接口返回字段要变，优先改这里。

## 5. services 目录

目录：

```text
services/
```

作用：放所有业务逻辑。

### 5.1 settings.py

文件：

```text
services/settings.py
```

作用：统一读取配置和环境变量。

当前支持：

- `OPENAI_API_KEY`
- `PERSONALITY_ID`
- `AUDIO_OUTPUT_DIR`
- `MEMORY_DB_PATH`

以后不要在各个文件里到处写 `os.getenv()`，统一放到这里。

### 5.2 personality_service.py

文件：

```text
services/personality_service.py
```

作用：读取机器人独一无二的人格配置。

当前会读取：

```text
data/personalities/default_robot.yaml
```

以后如果要换人格、增加多个机器人性格，就改这个模块和 `data/personalities/` 目录。

### 5.3 emotion_service.py

文件：

```text
services/emotion_service.py
```

作用：判断用户语气和情绪。

当前是简单规则版，可以先跑通流程。以后可以换成小模型或大模型结构化输出。

输入：

```text
用户文字
```

输出：

```json
{
  "label": "happy",
  "intensity": 0.65,
  "intent": "chat",
  "need_comfort": false,
  "safety_risk": "none"
}
```

### 5.4 memory_service.py

文件：

```text
services/memory_service.py
```

作用：保存和读取最近对话。

当前是内存临时版，服务重启后会丢失。后续会升级成 SQLite。

以后做长期记忆时，主要改这个文件。

### 5.5 brain_service.py

文件：

```text
services/brain_service.py
```

作用：机器人的“大脑”。

当前是占位版，会根据情绪和人格配置返回简单中文回复。后续接 OpenAI Responses API 时，主要改这个文件。

它应该接收：

- `device_id`
- 用户文字
- 情绪结果
- 最近对话
- 人格配置
- 记忆

它应该输出：

- `reply_text`
- `robot_mood`

### 5.6 stt_service.py

文件：

```text
services/stt_service.py
```

作用：语音转文字。

STT 是 speech to text 的缩写。

当前是占位版，只返回“已收到音频文件”。后续接 OpenAI Audio transcription 时，主要改这个文件。

### 5.7 tts_service.py

文件：

```text
services/tts_service.py
```

作用：文字转语音。

TTS 是 text to speech 的缩写。

当前是占位版，还不会生成真实音频。后续接 OpenAI Text to speech 时，主要改这个文件。

生成的音频文件应该放到：

```text
audio_outputs/
```

## 6. data 目录

目录：

```text
data/
```

作用：放项目运行数据。

当前有：

```text
data/personalities/default_robot.yaml
```

这个文件是机器人的人格配置，不是代码。以后你想调整机器人性格，优先改这里，而不是改 Python 代码。

后续 SQLite 记忆数据库也会放在：

```text
data/memory.sqlite
```

## 7. audio_outputs 目录

目录：

```text
audio_outputs/
```

作用：保存服务器生成的回复语音。

例如后续可能生成：

```text
audio_outputs/abc123.mp3
audio_outputs/def456.wav
```

ESP32-S3 会通过这个接口下载音频：

```text
GET /api/audio/reply/{reply_id}
```

## 8. Dockerfile 负责什么

文件：

```text
Dockerfile
```

作用：定义服务器镜像如何构建。

后续如果新增 Python 依赖，例如：

- `openai`
- `python-multipart`
- `pyyaml`

就需要在 Dockerfile 里安装。

## 9. docker-compose.yml 负责什么

文件：

```text
docker-compose.yml
```

作用：定义服务器容器如何运行。

后续会在这里加入：

- 环境变量。
- `data/` 挂载。
- `audio_outputs/` 挂载。

这样服务器重启后，人格、记忆和音频文件不会丢。

## 10. 后续开发应该改哪里

### 想改接口

改：

```text
app.py
schemas/api.py
```

### 想改机器人性格

改：

```text
data/personalities/default_robot.yaml
```

### 想接入 OpenAI 大模型

改：

```text
services/brain_service.py
services/settings.py
Dockerfile
docker-compose.yml
```

### 想接入语音识别

改：

```text
services/stt_service.py
app.py
Dockerfile
```

### 想接入文字转语音

改：

```text
services/tts_service.py
app.py
Dockerfile
docker-compose.yml
```

### 想做长期记忆

改：

```text
services/memory_service.py
data/memory.sqlite
docker-compose.yml
```

## 11. 当前代码状态

当前已经完成的是“代码骨架”：

- 接口位置已经确定。
- 业务模块位置已经确定。
- 人格配置文件已经确定。
- 语音识别和语音合成先用占位实现。
- 文本聊天接口已经可以走完整流程。

下一步建议先做：

```text
阶段 1：把 services/brain_service.py 接入 OpenAI Responses API
```

这样不用先处理麦克风和音频播放，就能先确认机器人人格和大脑能正常工作。

