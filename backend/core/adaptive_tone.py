from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Optional


class ToneMode(str, Enum):
    NEUTRAL = "neutral"
    CONCISE_DIRECT = "concise_direct"
    EMPATHETIC = "empathetic"
    URGENT = "urgent"
    WARM_PROFESSIONAL = "warm_professional"


@dataclass
class AdaptiveToneContext:
    mode: ToneMode = ToneMode.WARM_PROFESSIONAL
    detected_signal: Optional[str] = None
    confidence: float = 0.5
    instruction: str = ""
    enabled: bool = True


# Explicit conversational signals (never guessing medical or psychological conditions)
_TONE_PATTERNS = [
    # Urgent / In a rush
    (
        ToneMode.URGENT,
        r"\b(?:urgent|asap|emergency|hurry|in a rush|fast|quick answer|immediately|right now|no time)\b",
        "User is in a hurry or needs urgent assistance. Be exceptionally direct, crisp, and prioritize immediate actionable steps.",
        0.9,
    ),
    # Concise / Direct preference
    (
        ToneMode.CONCISE_DIRECT,
        r"\b(?:be concise|keep it short|briefly|in one sentence|tldr|bullet points only|just the answer|don't give a speech)\b",
        "User requested brevity. Provide only the essential answer with minimal preamble.",
        0.95,
    ),
    # Stressed / Frustrated / Needs extra patience and clarity
    (
        ToneMode.EMPATHETIC,
        r"\b(?:stressed|frustrated|overwhelmed|stuck|exhausted|tired|having a hard time|confused|not working at all)\b",
        "User expressed frustration or difficulty. Respond with extra clarity, calm reassurance, and clear step-by-step guidance without patronizing.",
        0.85,
    ),
    # Appreciative / Cheerful
    (
        ToneMode.WARM_PROFESSIONAL,
        r"\b(?:great|awesome|thank you so much|thanks cortex|wonderful|excited|happy|good morning|hello friend)\b",
        "User is engaging warmly. Maintain a warm, thoughtful, and courteous tone.",
        0.8,
    ),
]


def detect_adaptive_tone(user_text: str, enabled: bool = True) -> AdaptiveToneContext:
    """
    Detects situational communication cues to adapt Cortex's tone.
    Adheres to strict ethical boundaries:
    - Never psychoanalyzes or makes medical/psychological diagnoses.
    - Treats signals as situational communication preferences.
    - Does not override user consent, permission gates, or safety boundaries.
    """
    if not enabled or not user_text:
        return AdaptiveToneContext(
            mode=ToneMode.NEUTRAL,
            detected_signal=None,
            confidence=1.0,
            instruction="Maintain a balanced, objective, and helpful tone.",
            enabled=False,
        )

    text_lower = user_text.lower()
    for mode, pattern, instruction, conf in _TONE_PATTERNS:
        match = re.search(pattern, text_lower, flags=re.IGNORECASE)
        if match:
            return AdaptiveToneContext(
                mode=mode,
                detected_signal=match.group(0),
                confidence=conf,
                instruction=instruction,
                enabled=True,
            )

    # Default to warm professional assistant tone
    return AdaptiveToneContext(
        mode=ToneMode.WARM_PROFESSIONAL,
        detected_signal=None,
        confidence=0.7,
        instruction="Maintain a warm, articulate, and professional tone.",
        enabled=True,
    )


def apply_tone_to_prompt(base_prompt: str, tone_ctx: AdaptiveToneContext) -> str:
    """Appends adaptive communication instructions to the prompt if enabled."""
    if not tone_ctx.enabled or not tone_ctx.instruction:
        return base_prompt
    return f"{base_prompt}\n\n[Communication Guidance: {tone_ctx.instruction}]"
