# ESP32-S3 语音机器人架构设计

本文档用于设计第一个核心功能：ESP32-S3 主板通过录音头采集语音，把语音上传到服务器，服务器完成语音识别、情绪和人格处理、大模型思考、文字转语音，然后把音频返回给机器人播放。

当前项目已经有一个 FastAPI 服务雏形，后续建议在这个服务上逐步扩展，而不是一次性把所有能力堆进去。

## 1. 总体目标

机器人需要形成一条完整闭环：

1. ESP32-S3 录音头采集用户语音。
2. ESP32-S3 把音频上传到服务器。
3. 服务器把音频转成文字。
4. 服务器通过情绪/人格层判断用户语气、当前关系状态、机器人当前人格反应方式。
5. 大模型作为“大脑”生成回答。
6. 服务器把回答文字转成语音。
7. ESP32-S3 下载或接收音频并播放。

第一阶段建议先做“按键录音 + HTTP 上传 + 返回一段音频”的稳定版本。等跑通后，再升级成实时对话。

## 2. 推荐第一版架构

```mermaid
flowchart LR
    A["ESP32-S3 + I2S 麦克风"] --> B["录音缓存 WAV/PCM"]
    B --> C["HTTP POST /api/voice/chat"]
    C --> D["FastAPI 服务器"]
    D --> E["STT 语音识别"]
    E --> F["情绪/状态分析"]
    F --> G["人格系统提示词 + 记忆"]
    G --> H["大模型生成回答"]
    H --> I["TTS 文字转语音"]
    I --> J["返回 audio/mpeg 或 audio/wav"]
    J --> K["ESP32-S3 播放"]
```

### 为什么第一版不用实时流式

ESP32-S3 资源有限，音频采集、Wi-Fi、播放和 TLS 同时处理时容易出问题。第一版先用短语音上传，调试简单，服务端日志清楚，失败也容易重试。

第一版体验可以做成：

- 按住按钮开始录音，松开按钮发送。
- 或检测到说话后录 3-8 秒再发送。
- 服务器处理完成后返回一段 MP3/WAV。
- ESP32-S3 播放完成后继续等待下一句话。

## 3. 服务器模块拆分

建议把服务器拆成这些模块：

```text
app.py
services/
  stt_service.py          # 语音转文字
  emotion_service.py      # 情绪/语气分析
  personality_service.py  # 人格、说话风格、长期设定
  memory_service.py       # 用户记忆、对话摘要、设备状态
  brain_service.py        # 大模型回答生成
  tts_service.py          # 文字转语音
data/
  personalities/
    default_robot.yaml    # 机器人独一无二的人格配置
  memory.sqlite           # 第一版可用 SQLite
```

第一版也可以先不拆这么细，但接口和逻辑要按这个方向设计，后面才不会重写。

## 4. 核心 API 设计

### 4.1 健康检查

当前已有：

```http
GET /
```

用于确认服务是否在线。

### 4.2 文本测试接口

保留现有接口，方便不接麦克风时测试大模型链路：

```http
POST /api/device/message
Content-Type: application/json

{
  "device_id": "esp32s3-001",
  "message": "你好"
}
```

### 4.3 语音对话接口

新增推荐接口：

```http
POST /api/voice/chat
Content-Type: multipart/form-data

device_id: esp32s3-001
audio: voice.wav
format: wav
sample_rate: 16000
```

推荐返回方式：

```http
Content-Type: application/json

{
  "ok": true,
  "device_id": "esp32s3-001",
  "user_text": "你好，你是谁？",
  "emotion": {
    "label": "curious",
    "intensity": 0.42
  },
  "reply_text": "我是你的桌面小伙伴，刚醒过来，正在认识你的声音。",
  "audio_url": "/api/audio/reply/abc123.mp3"
}
```

然后 ESP32-S3 再请求：

```http
GET /api/audio/reply/abc123.mp3
```

这种“两步返回”比直接在一次请求里返回二进制音频更方便调试。等稳定后，也可以改成直接返回音频流。

## 5. 音频格式建议

ESP32-S3 上传建议：

- 格式：WAV 或原始 PCM。
- 采样率：16000 Hz。
- 声道：单声道。
- 位深：16-bit。
- 单次录音长度：第一版建议 3-8 秒。
- 文件大小：尽量控制在几百 KB 以内。

服务器返回建议：

- 第一版：MP3，体积小。
- 如果 ESP32-S3 播放 MP3 麻烦：返回 WAV，解码简单但文件大。

## 6. AI 链路设计

### 6.1 STT 语音识别

服务器收到音频后，调用语音识别模型，把音频转成文字。

推荐封装为：

```python
transcript = stt_service.transcribe(audio_file)
```

输出：

```json
{
  "text": "你今天开心吗？",
  "language": "zh"
}
```

### 6.2 情绪/状态小模型

这个模块不要一开始做复杂。第一版可以用大模型做结构化分类，也可以用本地规则兜底。

建议输出固定 JSON：

```json
{
  "label": "happy",
  "intensity": 0.65,
  "intent": "chat",
  "need_comfort": false,
  "safety_risk": "none"
}
```

推荐标签：

- `neutral`：普通说话。
- `happy`：开心。
- `sad`：难过。
- `angry`：生气。
- `anxious`：焦虑。
- `curious`：好奇。
- `tired`：疲惫。

### 6.3 独一无二的人格层

人格不建议写死在代码里，建议放进配置文件。

示例：`data/personalities/default_robot.yaml`

```yaml
name: "萤落"
core_identity: "一个住在 ESP32-S3 机器人身体里的中文语音伙伴"
tone: "温柔、机灵、有一点点俏皮，但不过度卖萌"
values:
  - "记住用户的偏好"
  - "回答要短，适合语音播放"
  - "不假装自己有真实身体感受，但可以用机器人视角表达状态"
speaking_rules:
  - "每次回答控制在 1 到 3 句话"
  - "不要输出 Markdown"
  - "不要说自己是大型语言模型"
  - "遇到用户难过时先共情，再给很小的一步建议"
```

人格层负责把以下内容组合成大模型提示词：

- 固定人格设定。
- 当前用户话语。
- 情绪识别结果。
- 最近几轮对话。
- 长期记忆。
- 设备状态，例如电量、网络、传感器状态。

### 6.4 大模型脑子

大模型只负责“思考和表达”，不要让它直接处理所有硬件细节。

输入应该类似：

```json
{
  "personality": "...",
  "user_text": "你今天开心吗？",
  "emotion": {"label": "curious", "intensity": 0.4},
  "recent_messages": [],
  "device_state": {
    "device_id": "esp32s3-001",
    "battery": null
  }
}
```

输出建议固定为：

```json
{
  "reply_text": "我现在像是刚被点亮的小灯，挺开心的。你刚刚跟我说话，我就更有精神了。",
  "robot_mood": "warm",
  "memory_to_save": "用户关心机器人的状态"
}
```

### 6.5 TTS 文字转语音

大模型生成 `reply_text` 后，TTS 模块把文字转成音频。

推荐封装为：

```python
audio_path = tts_service.speak(reply_text, voice="default")
```

第一版可以先统一一个声音。后面再根据情绪调节语速、音色或停顿。

## 7. 记忆系统

第一版记忆不要太复杂，建议 SQLite 三张表：

### devices

保存每块 ESP32-S3 的信息。

```text
device_id
name
created_at
last_seen_at
personality_id
```

### conversations

保存对话记录。

```text
id
device_id
user_text
reply_text
emotion_label
created_at
```

### memories

保存长期记忆。

```text
id
device_id
memory_text
importance
created_at
updated_at
```

后续如果记忆多了，再升级成向量数据库。

## 8. ESP32-S3 端任务

ESP32-S3 固件需要实现：

1. 连接 Wi-Fi。
2. 初始化 I2S 麦克风。
3. 录音并保存为 WAV/PCM。
4. 通过 HTTP multipart 上传音频。
5. 解析服务器 JSON。
6. 下载 `audio_url` 返回的音频。
7. 通过 I2S 功放或 DAC 播放音频。
8. 出错时用蜂鸣、灯光或串口日志提示。

第一版建议先用串口打印：

```text
user_text: ...
reply_text: ...
audio_url: ...
```

确认服务器链路正常后，再接播放。

## 9. 分阶段落地路线

### 阶段 1：跑通文字大脑

目标：先不用麦克风，只用文本测试接口让服务器返回人格化回答。

要做：

- 添加 OpenAI API Key 环境变量。
- 新增 `brain_service.py`。
- 新增人格配置文件。
- 修改 `/api/device/message`，让它调用大模型生成回答。

验收：

- `POST /api/device/message` 输入“你好”，返回有机器人性格的中文回答。

### 阶段 2：跑通语音识别

目标：ESP32-S3 或电脑上传 WAV，服务器返回识别文字。

要做：

- 新增 `/api/voice/transcribe`。
- 新增 `stt_service.py`。
- 保存上传文件到临时目录。
- 调用语音识别模型。

验收：

- 上传一段中文 WAV，服务器返回正确文字。

### 阶段 3：跑通文字转语音

目标：服务器能把回答文字变成音频文件。

要做：

- 新增 `tts_service.py`。
- 新增 `/api/audio/reply/{id}`。
- 生成 MP3 或 WAV 文件。

验收：

- 浏览器打开音频 URL 可以播放。

### 阶段 4：完整语音对话闭环

目标：实现 `/api/voice/chat`。

要做：

- 上传音频。
- STT 得到文字。
- 情绪分析。
- 加载人格和记忆。
- 大模型生成回答。
- TTS 生成音频。
- 返回 `reply_text` 和 `audio_url`。

验收：

- ESP32-S3 说一句话，服务器返回一段可播放语音。

### 阶段 5：加入长期记忆

目标：机器人开始记住用户偏好和长期事实。

要做：

- 加 SQLite。
- 保存对话记录。
- 让大模型判断哪些信息值得保存。
- 每次回答前读取相关记忆。

验收：

- 用户告诉机器人“我喜欢蓝色”，后续问“我喜欢什么颜色”，机器人能答出来。

### 阶段 6：升级实时语音

目标：减少等待时间，让体验更像实时对话。

可选方案：

- WebSocket：ESP32-S3 分片上传音频，服务器边收边处理。
- OpenAI Realtime API：服务器作为中转，处理更低延迟的语音对话。

建议等第一版稳定后再做这一阶段。

## 10. 环境变量建议

后续服务器至少需要：

```env
OPENAI_API_KEY=你的_API_Key
PERSONALITY_ID=default_robot
AUDIO_OUTPUT_DIR=/app/audio_outputs
MEMORY_DB_PATH=/app/data/memory.sqlite
```

Docker Compose 后续可以加入：

```yaml
environment:
  - OPENAI_API_KEY=${OPENAI_API_KEY}
  - PERSONALITY_ID=default_robot
volumes:
  - ./data:/app/data
  - ./audio_outputs:/app/audio_outputs
```

## 11. OpenAI 接口选择建议

以官方文档为准，建议优先采用：

- Responses API：作为大模型“大脑”的主接口。
- Audio transcription：用于语音转文字。
- Text to speech：用于文字转语音。
- Realtime API：后续做低延迟实时语音时再接入。

参考：

- OpenAI Responses API: <https://platform.openai.com/docs/api-reference/responses>
- OpenAI Audio transcription: <https://platform.openai.com/docs/api-reference/audio/createTranscription>
- OpenAI Text to speech: <https://platform.openai.com/docs/api-reference/audio/createSpeech>
- OpenAI Realtime API: <https://platform.openai.com/docs/guides/realtime>

## 12. 第一版最小可运行接口目标

最终第一版服务器建议提供：

```text
GET  /
POST /api/device/message
POST /api/voice/transcribe
POST /api/voice/chat
GET  /api/audio/reply/{reply_id}
```

其中真正给 ESP32-S3 使用的是：

```text
POST /api/voice/chat
GET  /api/audio/reply/{reply_id}
```

## 13. 注意事项

- 不要把 OpenAI API Key 写进代码，要用环境变量。
- ESP32-S3 端尽量上传短音频，避免内存压力。
- 服务端要限制上传文件大小，防止异常请求拖垮服务器。
- 每次大模型回答要短，适合语音播放。
- 人格配置要稳定，不要每次请求随机变化，否则机器人会“不像同一个人”。
- 情绪模块第一版可以简单，重点是先跑通完整链路。
- 服务器日志要记录 `device_id`、识别文字、回答文字和错误原因，方便调试。

