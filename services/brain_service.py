from openai import OpenAI, OpenAIError

from schemas.api import EmotionResult
from services.memory_service import ConversationTurn
from services.personality_service import load_personality_text
from services.settings import get_settings


def generate_reply(
    device_id: str,
    user_text: str,
    emotion: EmotionResult,
    recent_turns: list[ConversationTurn],
) -> tuple[str, str]:
    settings = get_settings()
    robot_mood = _pick_robot_mood(emotion)

    if settings.deepseek_api_key:
        try:
            return _generate_deepseek_reply(
                device_id=device_id,
                user_text=user_text,
                emotion=emotion,
                recent_turns=recent_turns,
                robot_mood=robot_mood,
            ), robot_mood
        except OpenAIError:
            return _fallback_reply(user_text, emotion, recent_turns), robot_mood

    return _fallback_reply(user_text, emotion, recent_turns), robot_mood


def _generate_deepseek_reply(
    device_id: str,
    user_text: str,
    emotion: EmotionResult,
    recent_turns: list[ConversationTurn],
    robot_mood: str,
) -> str:
    settings = get_settings()
    personality = load_personality_text()
    client = OpenAI(
        api_key=settings.deepseek_api_key,
        base_url=settings.deepseek_base_url,
        timeout=settings.deepseek_timeout_seconds,
    )

    extra_body = None
    if settings.deepseek_thinking_enabled:
        extra_body = {"thinking": {"type": "enabled"}}

    response = client.chat.completions.create(
        model=settings.deepseek_model,
        messages=_build_messages(
            device_id=device_id,
            personality=personality,
            emotion=emotion,
            recent_turns=recent_turns,
            user_text=user_text,
            robot_mood=robot_mood,
        ),
        stream=False,
        reasoning_effort=settings.deepseek_reasoning_effort,
        extra_body=extra_body,
    )

    reply = response.choices[0].message.content
    if not reply:
        return _fallback_reply(user_text, emotion, recent_turns)

    return reply.strip()


def _build_messages(
    device_id: str,
    personality: str,
    emotion: EmotionResult,
    recent_turns: list[ConversationTurn],
    user_text: str,
    robot_mood: str,
) -> list[dict[str, str]]:
    messages = [
        {
            "role": "system",
            "content": (
                f"{personality}\n\n"
                "你正在通过 ESP32-S3 语音机器人和用户对话。\n"
                "请使用自然中文回答，适合直接 TTS 播放。\n"
                "回答保持 1 到 3 句话，不要输出 Markdown。\n"
                f"当前设备 ID: {device_id}\n"
                f"识别到的用户情绪: {emotion.label}, 强度: {emotion.intensity}, "
                f"意图: {emotion.intent}, 需要安慰: {emotion.need_comfort}\n"
                f"机器人当前语气状态: {robot_mood}"
            ),
        }
    ]

    for turn in recent_turns:
        messages.append({"role": "user", "content": turn.user_text})
        messages.append({"role": "assistant", "content": turn.reply_text})

    messages.append({"role": "user", "content": user_text})
    return messages


def _pick_robot_mood(emotion: EmotionResult) -> str:
    if emotion.need_comfort:
        return "gentle"
    if emotion.label == "happy":
        return "bright"
    if emotion.intent == "question":
        return "curious"
    return "warm"


def _fallback_reply(
    user_text: str,
    emotion: EmotionResult,
    recent_turns: list[ConversationTurn],
) -> str:
    personality = load_personality_text()

    if emotion.need_comfort:
        return "我听出来你有点难受。我先陪你待一会儿，我们可以从一件很小的事开始慢慢来。"

    if emotion.label == "happy":
        return "听起来你现在心情不错，我也跟着亮起来了。要不要把这件开心的事讲给我听？"

    if emotion.intent == "question":
        return "我在这里，像一个刚醒来的桌面小伙伴。你问我什么，我会尽量用简单的话陪你想明白。"

    if recent_turns:
        return "我记得我们刚刚已经聊起来了。你继续说，我会跟着你的节奏慢慢回应。"

    if "萤落" in personality:
        return "你好，我是萤落。现在我的第一件事，就是认真认识你的声音。"
    else:
        return "你好，我已经收到你的话了。等接上大模型后，我会用自己的性格认真回答你。"
