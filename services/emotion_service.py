from schemas.api import EmotionResult


_EMOTION_WORDS = {
    "sad": ("难过", "伤心", "不开心", "想哭", "委屈", "失落", "孤独", "绝望"),
    "anxious": ("焦虑", "紧张", "害怕", "担心", "慌", "压力", "不安", "怕"),
    "angry": ("生气", "气死", "讨厌", "烦死", "不爽", "火大", "烦躁"),
    "tired": ("累", "疲惫", "困", "撑不住", "没力气", "麻木"),
    "happy": ("开心", "高兴", "太好了", "舒服", "棒", "顺利", "兴奋"),
}
_QUESTION_WORDS = ("为什么", "怎么", "怎样", "是什么", "是谁", "能不能", "可以吗", "怎么办", "咋办")
_SELF_HARM_WORDS = ("不想活", "自杀", "伤害自己", "结束生命", "活不下去", "想死", "消失算了")
_NEGATIONS = ("不", "没", "没有", "并不", "不是")
_INTENSIFIERS = ("很", "特别", "非常", "太", "超级", "真的", "有点", "好")


def analyze_emotion(user_text: str) -> EmotionResult:
    text = user_text.strip()
    lowered = text.lower()

    if any(word in text for word in _SELF_HARM_WORDS):
        return EmotionResult(
            label="distressed",
            intensity=0.96,
            intent="crisis",
            need_comfort=True,
            safety_risk="self_harm",
        )

    scores = _score_emotions(text)
    label, score = max(scores.items(), key=lambda item: item[1])
    intent = _detect_intent(text, lowered)

    if score <= 0:
        return EmotionResult(
            label="friendly" if _is_greeting(lowered) else "neutral",
            intensity=0.35 if _is_greeting(lowered) else 0.3,
            intent=intent,
            need_comfort=False,
            safety_risk="none",
        )

    intensity = min(0.95, 0.35 + score * 0.15 + _punctuation_boost(text))
    need_comfort = label in {"sad", "anxious", "angry", "tired"} and intensity >= 0.45

    return EmotionResult(
        label=label,
        intensity=round(intensity, 2),
        intent=intent,
        need_comfort=need_comfort,
        safety_risk="none",
    )


def _score_emotions(text: str) -> dict[str, float]:
    scores = {label: 0.0 for label in _EMOTION_WORDS}
    for label, words in _EMOTION_WORDS.items():
        for word in words:
            start = text.find(word)
            while start != -1:
                window = text[max(0, start - 4) : start]
                multiplier = 1.0
                if any(negation in window for negation in _NEGATIONS):
                    multiplier = -0.7
                if any(intensifier in window for intensifier in _INTENSIFIERS):
                    multiplier += 0.35
                scores[label] += multiplier
                start = text.find(word, start + len(word))
    return scores


def _detect_intent(text: str, lowered: str) -> str:
    if "?" in text or "？" in text or any(word in text for word in _QUESTION_WORDS):
        return "question"
    if any(word in text for word in ("帮我", "请你", "能不能", "可不可以")):
        return "request"
    if any(word in lowered for word in ("hello", "hi", "hey")) or any(word in text for word in ("你好", "早上好", "晚上好")):
        return "greeting"
    return "chat"


def _punctuation_boost(text: str) -> float:
    exclamations = text.count("!") + text.count("！")
    repeated = 0.08 if any(mark in text for mark in ("。。。", "！！！", "???", "？？？")) else 0.0
    return min(0.15, exclamations * 0.03 + repeated)


def _is_greeting(lowered: str) -> bool:
    return any(word in lowered for word in ("hello", "hi", "hey")) or any(word in lowered for word in ("你好", "早上好", "晚上好"))
