from schemas.api import EmotionResult


def analyze_emotion(user_text: str) -> EmotionResult:
    text = user_text.strip()

    if any(word in text for word in ["难过", "伤心", "不开心", "想哭"]):
        return EmotionResult(
            label="sad",
            intensity=0.7,
            intent="chat",
            need_comfort=True,
            safety_risk="none",
        )

    if any(word in text for word in ["开心", "高兴", "太好了", "喜欢"]):
        return EmotionResult(
            label="happy",
            intensity=0.65,
            intent="chat",
            need_comfort=False,
            safety_risk="none",
        )

    if "?" in text or "？" in text or any(word in text for word in ["为什么", "怎么", "是谁"]):
        return EmotionResult(
            label="curious",
            intensity=0.45,
            intent="question",
            need_comfort=False,
            safety_risk="none",
        )

    return EmotionResult(
        label="neutral",
        intensity=0.3,
        intent="chat",
        need_comfort=False,
        safety_risk="none",
    )

