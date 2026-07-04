from functools import lru_cache
import logging
import re

from openai import OpenAI, OpenAIError

from schemas.api import EmotionResult
from services.memory_service import ConversationTurn, UserProfile
from services.personality_service import load_personality_text
from services.settings import get_settings


logger = logging.getLogger(__name__)
MAX_HISTORY_TURNS = 6
MAX_USER_TEXT_CHARS = 800
MAX_HISTORY_TEXT_CHARS = 500
MAX_REPLY_CHARS = 220
MAX_REPLY_SENTENCES = 3


def generate_reply(
    device_id: str,
    user_text: str,
    emotion: EmotionResult,
    recent_turns: list[ConversationTurn],
    user_profile: UserProfile | None = None,
) -> tuple[str, str]:
    clean_user_text = _clean_text(user_text, MAX_USER_TEXT_CHARS)
    robot_mood = _pick_robot_mood(emotion)

    if _get_client() is not None:
        try:
            return (
                _generate_model_reply(
                    device_id=device_id,
                    user_text=clean_user_text,
                    emotion=emotion,
                    recent_turns=recent_turns,
                    user_profile=user_profile,
                    robot_mood=robot_mood,
                ),
                robot_mood,
            )
        except Exception:
            logger.exception("Model reply failed; using local fallback")

    return _fallback_reply(clean_user_text, emotion, recent_turns, user_profile), robot_mood


def _generate_model_reply(
    device_id: str,
    user_text: str,
    emotion: EmotionResult,
    recent_turns: list[ConversationTurn],
    user_profile: UserProfile | None,
    robot_mood: str,
) -> str:
    settings = get_settings()
    client = _get_client()
    if client is None:
        return _fallback_reply(user_text, emotion, recent_turns, user_profile)

    kwargs = {
        "model": settings.deepseek_model,
        "messages": _build_messages(
            device_id=device_id,
            personality=load_personality_text(),
            emotion=emotion,
            recent_turns=recent_turns,
            user_profile=user_profile,
            user_text=user_text,
            robot_mood=robot_mood,
        ),
        "stream": False,
    }

    if settings.deepseek_reasoning_effort:
        kwargs["reasoning_effort"] = settings.deepseek_reasoning_effort
    if settings.deepseek_thinking_enabled:
        kwargs["extra_body"] = {"thinking": {"type": "enabled"}}

    try:
        response = client.chat.completions.create(**kwargs)
    except (TypeError, OpenAIError):
        kwargs.pop("reasoning_effort", None)
        kwargs.pop("extra_body", None)
        response = client.chat.completions.create(**kwargs)

    reply = response.choices[0].message.content
    if not reply:
        return _fallback_reply(user_text, emotion, recent_turns, user_profile)

    return _normalize_reply(reply)


def _build_messages(
    device_id: str,
    personality: str,
    emotion: EmotionResult,
    recent_turns: list[ConversationTurn],
    user_profile: UserProfile | None,
    user_text: str,
    robot_mood: str,
) -> list[dict[str, str]]:
    profile_text = user_profile.to_prompt_text() if user_profile else "暂时还没有可靠的长期用户画像。"
    messages = [
        {
            "role": "system",
            "content": (
                f"{personality}\n\n"
                "你正在通过 ESP32-S3 语音机器人和用户对话。\n"
                "你的目标是成为一个稳定、可信、会记得上下文的中文语音伙伴。\n"
                "长期用户画像如下，只有在自然相关时使用，不要生硬复述：\n"
                f"{profile_text}\n\n"
                "回复要求：\n"
                "1. 使用自然中文，适合直接 TTS 播放。\n"
                "2. 默认 1 到 3 句话，先回应用户真正关心的点。\n"
                "3. 不输出 Markdown、项目符号、表格、代码、括号舞台说明或表情符号。\n"
                "4. 不编造你做不到的真实世界动作；可以用机器人视角表达在线、正在听、需要用户再说一遍。\n"
                "5. 如果用户有明显痛苦，先共情和稳定，再给很小的一步建议。\n"
                "6. 如果用户表达自伤风险，鼓励立刻联系身边可信任的人或当地紧急服务。\n"
                f"当前设备 ID: {device_id}\n"
                f"识别到的用户情绪: {emotion.label}, 强度: {emotion.intensity}, "
                f"意图: {emotion.intent}, 需要安慰: {emotion.need_comfort}, "
                f"安全风险: {emotion.safety_risk}\n"
                f"机器人当前语气状态: {robot_mood}"
            ),
        }
    ]

    for turn in recent_turns[-MAX_HISTORY_TURNS:]:
        user = _clean_text(turn.user_text, MAX_HISTORY_TEXT_CHARS)
        assistant = _clean_text(turn.reply_text, MAX_HISTORY_TEXT_CHARS)
        if user and assistant:
            messages.append({"role": "user", "content": user})
            messages.append({"role": "assistant", "content": assistant})

    messages.append({"role": "user", "content": user_text})
    return messages


def _pick_robot_mood(emotion: EmotionResult) -> str:
    if emotion.safety_risk != "none":
        return "steady"
    if emotion.need_comfort:
        return "gentle"
    if emotion.label == "happy":
        return "bright"
    if emotion.label == "angry":
        return "calm"
    if emotion.label in {"anxious", "tired"}:
        return "soft"
    if emotion.intent == "question":
        return "curious"
    return "warm"


def _fallback_reply(
    user_text: str,
    emotion: EmotionResult,
    recent_turns: list[ConversationTurn],
    user_profile: UserProfile | None,
) -> str:
    name = user_profile.preferred_name if user_profile and user_profile.preferred_name else ""
    introduced_name = _extract_introduced_name(user_text)
    if introduced_name:
        name = introduced_name
    prefix = f"{name}，" if name and not user_text.startswith(name) else ""

    if emotion.safety_risk == "self_harm":
        return _normalize_reply(
            f"{prefix}我听到你现在很危险，也很辛苦。请先不要一个人扛着，马上联系身边可信任的人，或者拨打当地紧急电话求助。"
        )

    if user_profile and user_profile.preferences and any(word in user_text for word in ("喜欢什么", "偏好", "爱好", "喜欢啥")):
        return _normalize_reply(f"{prefix}我记得你提过{user_profile.preferences[-1]}。你也可以继续告诉我新的偏好，我会慢慢记住。")

    if recent_turns and any(word in user_text for word in ("记得", "刚才", "之前", "上次")):
        last_turn = recent_turns[-1]
        remembered = _clean_text(last_turn.user_text, 80)
        return _normalize_reply(f"{prefix}我记得，你刚才说的是“{remembered}”。如果你愿意，我们可以接着这个话题继续聊。")

    if introduced_name:
        return _normalize_reply(f"{prefix}我记住了，以后就这样称呼你。我是影落，会慢慢熟悉你的说话习惯和偏好。")

    if emotion.need_comfort:
        return _normalize_reply(
            f"{prefix}我听出来你现在不太好受。我先陪你稳一下，我们可以从一件很小的事开始，比如先慢慢吸一口气。"
        )

    if emotion.label == "happy":
        return _normalize_reply(f"{prefix}听起来你现在心情不错，我也替你亮起来了。要不要把这件开心的事讲给我听？")

    if any(word in user_text for word in ("你是谁", "你叫什么", "你的名字")):
        return _normalize_reply(f"{prefix}我是影落，一个住在 ESP32-S3 机器人身体里的中文语音伙伴。我会尽量用短一点、自然一点的话陪你聊天。")

    if emotion.intent == "question":
        return _normalize_reply(f"{prefix}我在听，你可以把问题再说具体一点。我会尽量用简单的话，陪你一步一步想明白。")

    if recent_turns:
        return _normalize_reply(f"{prefix}我记得我们刚刚已经聊起来了。你继续说，我会跟着你的节奏慢慢回应。")

    return _normalize_reply(f"{prefix}你好，我是影落。我已经听到你了，现在最重要的事就是认真认识你的声音。")


@lru_cache
def _get_client() -> OpenAI | None:
    settings = get_settings()
    if not settings.deepseek_api_key:
        return None
    return OpenAI(
        api_key=settings.deepseek_api_key,
        base_url=settings.deepseek_base_url,
        timeout=settings.deepseek_timeout_seconds,
    )


def _clean_text(text: str, max_chars: int) -> str:
    return " ".join(text.strip().split())[:max_chars]


def _extract_introduced_name(text: str) -> str | None:
    match = re.search(r"(?:我叫|我的名字叫|我的名字是|叫我|以后叫我)([\u4e00-\u9fa5A-Za-z0-9_-]{1,12})", text)
    if not match:
        return None
    return match.group(1).strip()


def _normalize_reply(reply: str) -> str:
    cleaned = _clean_text(reply, 800)
    cleaned = re.sub(r"```.*?```", "", cleaned, flags=re.S)
    cleaned = re.sub(r"^[#>*\-\d.、\s]+", "", cleaned)
    cleaned = re.sub(r"[\r\n]+", "，", cleaned)
    cleaned = re.sub(r"[*_`#>\[\]{}]", "", cleaned)
    cleaned = re.sub(r"[😀-🙏🌀-🗿🚀-🛿☀-⛿✀-➿]+", "", cleaned)
    cleaned = re.sub(r"（[^（）]{0,30}）|\([^()]{0,30}\)", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ，。；;")
    cleaned = _limit_sentences(cleaned, MAX_REPLY_SENTENCES)
    if len(cleaned) > MAX_REPLY_CHARS:
        cleaned = cleaned[:MAX_REPLY_CHARS].rstrip("，、；; ")
    return cleaned or "我听到了。你可以再多说一点，我会继续认真听。"


def _limit_sentences(text: str, max_sentences: int) -> str:
    parts = re.findall(r"[^。！？!?]+[。！？!?]?", text)
    if not parts:
        return text
    limited = "".join(parts[:max_sentences]).strip()
    if limited and limited[-1] not in "。！？!?":
        limited += "。"
    return limited
