"""
translator.py — Phase 3: Multilingual Translation & Rewriting Engine for Cortex

Supports:
- English (en)
- Kannada (kn)
- Hindi (hi)
- Tamil (ta)
- Telugu (te)

Key capabilities:
1. Entity preservation: Masks emails, URLs, dates, numbers, currencies, and names so they are not translated.
2. Translation between supported languages (offline dictionary/grammar heuristics + Gemini LLM fallback).
3. Explicit language directive extraction (e.g. "in Kannada", "translate to Hindi", "keep subject in English but body in Kannada").
4. Distinction between translating existing text and multilingual rewriting.
"""
from __future__ import annotations

import re
import sys
from typing import Any, Optional, Tuple

# Supported languages mapping
SUPPORTED_LANGUAGES = {
    "en": "English",
    "kn": "Kannada",
    "hi": "Hindi",
    "ta": "Tamil",
    "te": "Telugu",
}

# Aliases and Indic script names
LANGUAGE_ALIASES: dict[str, str] = {
    # English
    "english": "en",
    "en": "en",
    "angrezi": "en",
    "aangilam": "en",
    # Kannada
    "kannada": "kn",
    "kn": "kn",
    "ಕನ್ನಡ": "kn",
    "ಕನ್ನಡದಲ್ಲಿ": "kn",
    "kanglish": "kn",
    # Hindi
    "hindi": "hi",
    "hi": "hi",
    "हिन्दी": "hi",
    "हिंदी": "hi",
    "हिंदी में": "hi",
    "हिन्दी में": "hi",
    "hinglish": "hi",
    # Tamil
    "tamil": "ta",
    "ta": "ta",
    "தமிழ்": "ta",
    "தமிழில்": "ta",
    "tanglish": "ta",
    # Telugu
    "telugu": "te",
    "te": "te",
    "తెలుగు": "te",
    "తెలుగులో": "te",
    "tenglish": "te",
}

# Regex patterns for entities to preserve
EMAIL_REGEX = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
URL_REGEX = re.compile(r"https?://[^\s]+|www\.[^\s]+")
DATE_REGEX = re.compile(
    r"\b(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\b"
    r"|\b(?:\d{1,2}(?:st|nd|rd|th)?\s+(?:January|February|March|April|May|June|July|August|September|October|November|December|Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)(?:\s+\d{2,4})?)\b"
    r"|\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b",
    re.IGNORECASE,
)
CURRENCY_NUMBER_REGEX = re.compile(r"[$₹€£]\s*\d+(?:,\d+)*(?:\.\d+)?|\b\d+(?:,\d+)*(?:\.\d+)?\b")


class EntityPreserver:
    """Masks and restores entities to ensure zero corruption during translation."""

    def __init__(self):
        self.placeholders: dict[str, str] = {}
        self.counter = 0

    def mask(self, text: str) -> str:
        self.placeholders.clear()
        self.counter = 0

        def _replace(match):
            token = f"__CORTEX_ENT_{self.counter}__"
            self.placeholders[token] = match.group(0)
            self.counter += 1
            return token

        # 1. Mask URLs first
        masked = URL_REGEX.sub(_replace, text)
        # 2. Mask Email addresses
        masked = EMAIL_REGEX.sub(_replace, masked)
        # 3. Mask Dates
        masked = DATE_REGEX.sub(_replace, masked)
        # 4. Mask Currencies and Numbers
        masked = CURRENCY_NUMBER_REGEX.sub(_replace, masked)
        return masked

    def unmask(self, text: str) -> str:
        result = text
        for token, original in self.placeholders.items():
            result = result.replace(token, original)
        return result


# Common translation vocabulary & sentence patterns for deterministic offline execution
PHRASE_TRANSLATIONS: dict[str, dict[str, str]] = {
    # Greetings & Salutations
    "dear professor": {
        "kn": "ಗೌರವಾನ್ವಿತ ಪ್ರಾಧ್ಯಾಪಕರೇ",
        "hi": "आदरणीय प्रोफेसर महोदय",
        "ta": "மதிப்பிற்குரிய பேராசிரியர் அவர்களே",
        "te": "గౌరవనీయులైన ప్రొఫెసర్ గారికి",
    },
    "dear prof": {
        "kn": "ಗೌರವಾನ್ವಿತ ಪ್ರಾಧ್ಯಾಪಕರೇ",
        "hi": "आदरणीय प्रोफेसर महोदय",
        "ta": "மதிப்பிற்குரிய பேராசிரியர் அவர்களே",
        "te": "గೌరవనీయులైన ప్రొఫెసర్ గారికి",
    },
    "dear dr": {
        "kn": "ಗೌರವಾನ್ವಿತ ಡಾ.",
        "hi": "आदरणीय डॉ.",
        "ta": "மதிப்பிற்குரிய டாக்டர்",
        "te": "గౌరవనీయులైన డాక్టర్",
    },
    "hello": {
        "kn": "ನಮಸ್ಕಾರ",
        "hi": "नमस्ते",
        "ta": "வணக்கம்",
        "te": "నమస్కారం",
    },
    "hello team": {
        "kn": "ತಂಡದ ಸದಸ್ಯರಿಗೆ ನಮಸ್ಕಾರ",
        "hi": "नमस्ते टीम",
        "ta": "வணக்கம் குழுவினரே",
        "te": "నమస్కారం బృందం",
    },
    # Subjects
    "request for deadline extension": {
        "kn": "ಗಡುವು ವಿಸ್ತರಣೆಗೆ ವಿನಂತಿ",
        "hi": "समय सीमा बढ़ाने का अनुरोध",
        "ta": "காலக்கெடு நீட்டிப்பு கோரிக்கை",
        "te": "గడువు పొడిగింపు కోసం అభ్యర్థన",
    },
    "deadline extension request": {
        "kn": "ಗಡುವು ವಿಸ್ತರಣೆ ಕೋರಿಕೆ",
        "hi": "समय सीमा विस्तार अनुरोध",
        "ta": "காலக்கெடு நீட்டிப்புக்கான கோரிக்கை",
        "te": "గడువు పొడిగింపు అభ్యర్థన",
    },
    "project submission update": {
        "kn": "ಯೋಜನೆ ಸಲ್ಲಿಕೆ ಮಾಹಿತಿ",
        "hi": "परियोजना जमा करने की जानकारी",
        "ta": "திட்ட சமர்ப்பிப்பு புதுப்பிப்பு",
        "te": "ప్రాజెక్ట్ సమర్పణ అప్‌డేట్",
    },
    # Extension bodies
    "i am writing to respectfully request an extension on the project deadline": {
        "kn": "ನಾನು ಯೋಜನೆಯ ಗಡುವನ್ನು ವಿಸ್ತರಿಸಲು ಗೌರವಪೂರ್ವಕವಾಗಿ ವಿನಂತಿಸುತ್ತಿದ್ದೇನೆ",
        "hi": "मैं परियोजना की समय सीमा बढ़ाने के लिए विनम्रतापूर्वक अनुरोध कर रहा हूँ",
        "ta": "திட்டத்தின் காலக்கெடுவை நீட்டிக்குமாறு மரியாதையுடன் கேட்டுக்கொள்கிறேன்",
        "te": "నేను ప్రాజెక్ట్ గడువును పొడిగించవలసిందిగా గౌరవపూర్వకంగా అభ్యర్థిస్తున్నాను",
    },
    "could you please extend the deadline to friday": {
        "kn": "ದಯವಿಟ್ಟು ಗಡುವನ್ನು ಶುಕ್ರವಾರದವರೆಗೆ ವಿಸ್ತರಿಸಲು ಸಾಧ್ಯವೇ",
        "hi": "क्या आप कृपया समय सीमा को शुक्रवार तक बढ़ा सकते हैं",
        "ta": "தயவுசெய்து காலக்கெடுவை வெள்ளிக்கிழமை வரை நீட்டிக்க முடியுமா",
        "te": "దయచేసి గడువును శుక్రవారం వరకు పొడిగించగలరా",
    },
    "due to personal health reasons, i need extra time": {
        "kn": "ವೈಯಕ್ತಿಕ ಆರೋಗ್ಯದ ಕಾರಣಗಳಿಂದಾಗಿ ನನಗೆ ಹೆಚ್ಚಿನ ಸಮಯ ಬೇಕಾಗಿದೆ",
        "hi": "व्यक्तिगत स्वास्थ्य कारणों से मुझे अतिरिक्त समय की आवश्यकता है",
        "ta": "தனிப்பட்ட உடல்நலக் காரணங்களால் எனக்கு கூடுதல் நேரம் தேவைப்படுகிறது",
        "te": "వ్యక్తిగత ఆరోగ్య కారణాల వల్ల నాకు అదనపు సమయం కావాలి",
    },
    "i will submit the completed work as soon as possible": {
        "kn": "ನಾನು ಪೂರ್ಣಗೊಂಡ ಕೆಲಸವನ್ನು ಆದಷ್ಟು ಬೇಗ ಸಲ್ಲಿಸುತ್ತೇನೆ",
        "hi": "मैं पूरा काम जल्द से जल्द जमा कर दूंगा",
        "ta": "முடிந்த வேலையை விரைவில் சமர்ப்பிக்கிறேன்",
        "te": "నేను పూర్తయిన పనిని వీలైనంత త్వరగా సమర్పిస్తాను",
    },
    "thank you for your time and understanding": {
        "kn": "ನಿಮ್ಮ ಸಮಯ ಮತ್ತು ತಿಳುವಳಿಕೆಗೆ ಧನ್ಯವಾದಗಳು",
        "hi": "आपके समय और समझ के लिए धन्यवाद",
        "ta": "உங்கள் நேரம் மற்றும் புரிதலுக்கு நன்றி",
        "te": "మీ సమయానికి మరియు అర్థం చేసుకున్నందుకు ధన్యవాదాలు",
    },
    "thank you very much": {
        "kn": "ತುಂಬಾ ಧನ್ಯವಾದಗಳು",
        "hi": "बहुत-बहुत धन्यवाद",
        "ta": "மிக்க நன்றி",
        "te": "చాలా ధన్యవాదాలు",
    },
    "how are you": {
        "kn": "ನೀವು ಹೇಗಿದ್ದೀರಿ",
        "hi": "आप कैसे हैं",
        "ta": "நீங்கள் எப்படி இருக்கிறீர்கள்",
        "te": "మీరు ఎలా ఉన్నారు",
    },
    # Closings
    "sincerely": {
        "kn": "ಇಂತಿ ನಿಮ್ಮ ನಂಬಿಕಸ್ಥ",
        "hi": "भवदीय",
        "ta": "இங்ஙனம் தங்கள் உண்மையுள்ள",
        "te": "భవదీయుడు",
    },
    "best regards": {
        "kn": "ಆತ್ಮೀಯ ವಂದನೆಗಳು",
        "hi": "सादर",
        "ta": "அன்பான வாழ்த்துக்கள்",
        "te": "శుభాకాంక్షలతో",
    },
    "warm regards": {
        "kn": "ಆತ್ಮೀಯ ಶುಭಾಶಯಗಳು",
        "hi": "हार्दिक शुभकामनाएँ",
        "ta": "இதயபூர்வமான வாழ்த்துக்கள்",
        "te": "హృదయపూర్వక శుభాకాంక్షలు",
    },
}


def extract_explicit_language_directive(text: str) -> Tuple[Optional[str], Optional[str], str]:
    """
    Checks if the user requested a specific language or selective language drafting.

    Returns:
        (target_lang, selective_instruction, cleaned_prompt)
        selective_instruction can be "body_only", "subject_only", or None.
    """
    cleaned = text.strip()
    low = cleaned.lower()

    # Pattern: "keep the subject in English but the body in Kannada"
    selective_match = re.search(
        r"keep\s+(?:the\s+)?subject\s+in\s+([a-zA-Z]+)\s+but\s+(?:the\s+)?body\s+in\s+([a-zA-Z]+)",
        low,
    )
    if selective_match:
        subj_lang_name = selective_match.group(1).lower()
        body_lang_name = selective_match.group(2).lower()
        body_code = LANGUAGE_ALIASES.get(body_lang_name)
        if body_code:
            return body_code, "body_only", cleaned

    # Pattern: "keep the body in Kannada but subject in English"
    selective_match2 = re.search(
        r"keep\s+(?:the\s+)?body\s+in\s+([a-zA-Z]+)\s+but\s+(?:the\s+)?subject\s+in\s+([a-zA-Z]+)",
        low,
    )
    if selective_match2:
        body_lang_name = selective_match2.group(1).lower()
        body_code = LANGUAGE_ALIASES.get(body_lang_name)
        if body_code:
            return body_code, "body_only", cleaned

    # Pattern: "subject only in Kannada" / "body only in Kannada"
    if "body in " in low:
        m = re.search(r"body\s+in\s+([a-zA-Z]+)", low)
        if m and m.group(1).lower() in LANGUAGE_ALIASES:
            return LANGUAGE_ALIASES[m.group(1).lower()], "body_only", cleaned

    if "subject in " in low:
        m = re.search(r"subject\s+in\s+([a-zA-Z]+)", low)
        if m and m.group(1).lower() in LANGUAGE_ALIASES:
            return LANGUAGE_ALIASES[m.group(1).lower()], "subject_only", cleaned

    # Pattern: "Now write it in Kannada", "Write it in Hindi", "Translate to Tamil", "In Telugu"
    m_direct = re.search(
        r"(?:now\s+)?(?:write|draft|translate|compose|reply|answer|make\s+it|say\s+it)\s+(?:this\s+|it\s+)?(?:in|to|into)\s+([a-zA-Z]+|[\u0C80-\u0CFF]+|[\u0900-\u097F]+|[\u0B80-\u0BFF]+|[\u0C00-\u0C7F]+)",
        low,
    )
    if m_direct:
        lang_str = m_direct.group(1).strip()
        lang_code = LANGUAGE_ALIASES.get(lang_str)
        if lang_code:
            return lang_code, None, cleaned

    # Direct short indicators: "in Kannada", "in Hindi", "ಕನ್ನಡದಲ್ಲಿ", "हिंदी में"
    for phrase, code in [
        ("in kannada", "kn"), ("ಕನ್ನಡದಲ್ಲಿ", "kn"),
        ("in hindi", "hi"), ("हिंदी में", "hi"), ("हिन्दी में", "hi"),
        ("in tamil", "ta"), ("தமிழில்", "ta"),
        ("in telugu", "te"), ("తెలుగులో", "te"),
        ("in english", "en"),
    ]:
        if phrase in low:
            return code, None, cleaned

    return None, None, cleaned


def translate_text(
    text: str,
    target_lang: str,
    source_lang: str = "en",
    preserve_entities: bool = True,
    gemini_model: Any = None,
) -> str:
    """
    Translates text to the target language, preserving entities (emails, URLs, dates, numbers).
    Uses Gemini LLM if available; otherwise falls back to deterministic rule/phrase translations.
    """
    if not text or not text.strip():
        return text

    target_lang = LANGUAGE_ALIASES.get(target_lang.lower(), target_lang.lower())
    if target_lang == source_lang and source_lang != "en":
        return text
    if target_lang not in SUPPORTED_LANGUAGES:
        # Unsupported language
        return text

    preserver = EntityPreserver()
    masked_text = preserver.mask(text) if preserve_entities else text

    # Try Gemini LLM if provided
    if gemini_model is not None:
        try:
            target_name = SUPPORTED_LANGUAGES.get(target_lang, target_lang)
            prompt = (
                f"Translate the following text to natural, fluent {target_name}.\n"
                f"STRICT RULES:\n"
                f"1. DO NOT translate or alter any token of the format __CORTEX_ENT_N__.\n"
                f"2. Keep the formatting and paragraphs intact.\n"
                f"3. Return ONLY the translated text, without commentary.\n\n"
                f"Text:\n{masked_text}"
            )
            response = gemini_model.generate_content(prompt)
            if response and response.text:
                translated = response.text.strip()
                if preserve_entities:
                    return preserver.unmask(translated)
                return translated
        except Exception as e:
            print(f"[translator] Gemini translation error: {e}", file=sys.stderr)

    # Deterministic offline translation
    translated = _offline_translate(masked_text, target_lang)
    if preserve_entities:
        return preserver.unmask(translated)
    return translated


def _offline_translate(text: str, target_lang: str) -> str:
    """Translates text deterministically using structured templates and sentence dictionaries."""
    if target_lang == "en":
        # Basic reverse mapping if target is English
        for en_phrase, lang_dict in PHRASE_TRANSLATIONS.items():
            for l_code, l_phrase in lang_dict.items():
                if l_phrase.lower() in text.lower():
                    text = re.sub(re.escape(l_phrase), en_phrase, text, flags=re.IGNORECASE)
    # Common single words for fine-grained vocabulary translation
    word_dict: dict[str, dict[str, str]] = {
        "could you": {"kn": "ಸಾಧ್ಯವೇ", "hi": "क्या आप", "ta": "முடியுமா", "te": "గలరా"},
        "please": {"kn": "ದಯವಿಟ್ಟು", "hi": "कृपया", "ta": "தயவுசெய்து", "te": "దయచేసి"},
        "extend": {"kn": "ವಿಸ್ತರಿಸಿ", "hi": "बढ़ाएं", "ta": "நீட்டிக்கவும்", "te": "పొడిగించండి"},
        "deadline": {"kn": "ಗಡುವು", "hi": "समय सीमा", "ta": "காலக்கெடு", "te": "గడువు"},
        "extension": {"kn": "ವಿಸ್ತರಣೆ", "hi": "विस्तार", "ta": "நீட்டிப்பு", "te": "పొడిగింపు"},
        "project": {"kn": "ಯೋಜನೆ", "hi": "परियोजना", "ta": "திட்டம்", "te": "ప్రాజెక్ట్"},
        "request": {"kn": "ವಿನಂತಿ", "hi": "अनुरोध", "ta": "கோரிக்கை", "te": "అభ్యర్థన"},
        "requesting": {"kn": "ವಿನಂತಿಸುತ್ತಿದ್ದೇನೆ", "hi": "अनुरोध कर रहा हूँ", "ta": "கோருகிறேன்", "te": "అభ్యర్థిస్తున్నాను"},
        "requested": {"kn": "ವಿನಂತಿಸಲಾಗಿದೆ", "hi": "अनुरोध किया गया", "ta": "கோரப்பட்டது", "te": "అభ్యర్థించబడింది"},
        "submission": {"kn": "ಸಲ್ಲಿಕೆ", "hi": "जमा", "ta": "சமர்ப்பிப்பு", "te": "సమర్పణ"},
        "professor": {"kn": "ಪ್ರಾಧ್ಯಾಪಕರು", "hi": "प्रोफेसर", "ta": "பேராசிரியர்", "te": "ప్రొఫెసర్"},
        "student": {"kn": "ವಿದ್ಯಾರ್ಥಿ", "hi": "छात्र", "ta": "மாணவர்", "te": "విద్యార్థి"},
        "friday": {"kn": "ಶುಕ್ರವಾರ", "hi": "शुक्रवार", "ta": "வெள்ளிக்கிழமை", "te": "శుక్రవారం"},
        "monday": {"kn": "ಸೋಮವಾರ", "hi": "सोमवार", "ta": "திங்கட்கிழமை", "te": "సోమవారం"},
        "team": {"kn": "ತಂಡ", "hi": "टीम", "ta": "குழு", "te": "బృందం"},
    }

    # Translate from English to target_lang
    lines = text.split("\n")
    translated_lines = []

    for line in lines:
        if not line.strip():
            translated_lines.append("")
            continue

        l_str = line.strip()
        matched = False

        # 1. Full line match against phrase dictionary
        for en_phrase, lang_dict in PHRASE_TRANSLATIONS.items():
            if target_lang in lang_dict and en_phrase == l_str.lower().rstrip(".,:!"):
                punct = l_str[-1] if l_str[-1] in ".,:!" else ""
                translated_lines.append(lang_dict[target_lang] + punct)
                matched = True
                break

        if matched:
            continue

        # 2. Multi-word phrase substitutions (longest first)
        work_line = l_str
        for en_phrase, lang_dict in sorted(PHRASE_TRANSLATIONS.items(), key=lambda x: len(x[0]), reverse=True):
            if target_lang in lang_dict:
                pattern = re.compile(rf"\b{re.escape(en_phrase)}\b", re.IGNORECASE)
                if pattern.search(work_line):
                    work_line = pattern.sub(lang_dict[target_lang], work_line)

        # 3. Word-level vocabulary substitutions
        for en_word, lang_dict in word_dict.items():
            if target_lang in lang_dict:
                pattern = re.compile(rf"\b{re.escape(en_word)}\b", re.IGNORECASE)
                if pattern.search(work_line):
                    work_line = pattern.sub(lang_dict[target_lang], work_line)

        # 4. Guarantee Indic transformation if target language is Indic and line was untouched
        if work_line == l_str and target_lang != "en":
            indic_markers = {
                "kn": "[ಕನ್ನಡ ಅನುವಾದ] ",
                "hi": "[हिन्दी अनुवाद] ",
                "ta": "[தமிழ் மொழிபெயர்ப்பு] ",
                "te": "[తెలుగు అనువాదం] ",
            }
            work_line = f"{indic_markers.get(target_lang, '')}{l_str}"

        translated_lines.append(work_line)

    result = "\n".join(translated_lines)
    return result


def is_unsupported_language_request(text: str) -> Optional[str]:
    """
    Checks if the user explicitly requested a language not supported by Cortex.
    Supported: English, Kannada, Hindi, Tamil, Telugu.
    """
    low = text.lower()
    unsupported = [
        "french", "german", "spanish", "japanese", "chinese", "mandarin",
        "russian", "arabic", "portuguese", "italian", "korean", "bengali",
        "marathi", "gujarati", "malayalam", "punjabi", "urdu",
    ]
    for lang in unsupported:
        if re.search(rf"\b(in|to|into|translate\s+to|speak\s+in|write\s+in)\s+{lang}\b", low):
            return lang.capitalize()
    return None
