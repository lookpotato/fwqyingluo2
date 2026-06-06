# WebSocket Voice Protocol

Endpoint:

```text
ws://<server-host>:8000/ws/voice
```

Optional query parameters:

```text
ws://<server-host>:8000/ws/voice?device_id=esp32s3-001&sample_rate=16000
```

Audio format:

```text
PCM signed 16-bit little-endian, mono, 16000 Hz
```

Utterance end marker:

```text
__END_OF_UTTERANCE__
```

Client messages:

```json
{"type":"start","device_id":"esp32s3-001","sample_rate":16000}
```

Then send raw PCM audio as binary WebSocket frames.

End one utterance by sending this text frame:

```text
__END_OF_UTTERANCE__
```

Equivalent JSON end message:

```json
{"type":"end"}
```

Optional reset:

```json
{"type":"reset"}
```

Optional heartbeat:

```json
{"type":"ping"}
```

Server messages:

```json
{"type":"ready","device_id":"esp32s3-001","sample_rate":16000,"audio_format":"pcm_s16le_mono","end_marker":"__END_OF_UTTERANCE__"}
```

```json
{"type":"partial_text","text":"...","total_bytes":12345}
```

```json
{"type":"final_text","device_id":"esp32s3-001","text":"...","total_bytes":12345}
```

```json
{"type":"reply","ok":true,"device_id":"esp32s3-001","user_text":"...","reply_text":"...","robot_mood":"warm","audio_url":"/api/audio/reply/<file>.mp3"}
```

```json
{"type":"no_speech","message":"No recognizable speech received","total_bytes":12345}
```

```json
{"type":"error","message":"..."}
```
