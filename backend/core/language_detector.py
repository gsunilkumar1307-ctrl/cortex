"""
language_detector.py — Phase 6: Multilingual Language Detection for Cortex

Priority chain:
  1. Unicode-block heuristic  (fast, offline — catches native-script input)
  2. Romanized keyword match  (offline — catches transliterated Indian text)
  3. Gemini LLM detect call   (online, only when heuristics are ambiguous)
  4. Fallback → English       (always safe)

Supports: English (en), Kannada (kn), Hindi (hi), Tamil (ta), Telugu (te)
"""
from __future__ import annotations

import re
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass  # avoid circular import; LanguageCode imported at call-site

# ── Unicode ranges for Indic scripts ────────────────────────────────────────
_KANNADA_RANGE  = re.compile(r"[\u0C80-\u0CFF]")   # ಕನ್ನಡ
_HINDI_RANGE    = re.compile(r"[\u0900-\u097F]")   # देवनागरी (Hindi/Marathi/Sanskrit)
_TAMIL_RANGE    = re.compile(r"[\u0B80-\u0BFF]")   # தமிழ்
_TELUGU_RANGE   = re.compile(r"[\u0C00-\u0C7F]")   # తెలుగు

# ── Romanized (transliterated) keyword sets ──────────────────────────────────
# Common words/phrases a person uses when speaking that specific language in Latin script
_ROMAN_KN = {
    # greetings & friend terms
    "namaskara", "namaskaram", "hegidira", "hegiddira", "hegidiya", "chennagidira",
    "samachara", "snehitare", "geleyane", "guru", "macha", "kannada",
    # verbs / fillers
    "maadu", "maadi", "madhu", "madko", "madkond", "heli", "helri", "helappa",
    "beda", "bidu", "bidappa", "illa", "ide", "ide-ya", "iro", "irli", "iri",
    "anta", "andre", "andre-ya", "enu", "yenu", "en", "yaak", "yaake",
    "naan", "naanu", "nimage", "ninge", "nimge", "avru", "avaru", "avana",
    "hogi", "hodre", "banni", "band", "banda", "barli", "baar", "baara",
    "sari", "sari-ya", "thumba", "thumba-na", "chennag", "channag", "channagi",
    "ondu", "eradu", "mooru", "naalk", "aidu", "aaru", "nodi", "nodi-pa",
    "oota", "aaytha", "aaytu", "kelsa", "dayavittu", "dhanyavadagalu", "bega",
    # everyday phrases
    "yeshtu", "eshtu", "henge", "hengirutte", "hengide", "hengaagutte",
    "gottilla", "gottide", "bittogala", "bitogala", "bitogale", "nodappa",
    "nim mail", "nan mail", "mail check", "inbox nod", "mail odhu",
}

_ROMAN_HI = {
    # greetings & friend terms
    "namaste", "namaskar", "pranam", "kaisa", "kaise", "kaisi", "haal", "chal",
    "dost", "yaar", "bhai", "bhaiya", "shukriya", "dhanyawad", "badhiya",
    # pronouns / verbs / fillers
    "karo", "karna", "karta", "karti", "kar", "mujhe", "mujhse", "mera",
    "mere", "meri", "hum", "hume", "humara", "aap", "aapka", "aapki",
    "nahi", "nhi", "nahin", "hai", "hain", "tha", "thi", "hoga",
    "yeh", "ye", "woh", "wo", "isko", "usko", "iska", "uska",
    "kya", "kab", "kahan", "kyun", "kyunki", "aur", "lekin", "magar",
    "thoda", "bahut", "bhi", "sirf", "ab", "phir", "bata", "batao",
    "dikha", "dikhao", "kholo", "band", "bhejo", "bhej", "likh", "likho",
    "seedha", "suno", "sun", "bol", "bolo", "dekh", "dekho", "ruk", "ruko",
    "jaldi", "dhire", "accha", "theek", "bilkul", "zaroor", "samajh",
    "samajho", "mail padh", "mail bhejo", "inbox dekho", "kripya", "alvida",
}

_ROMAN_TA = {
    # greetings & friend terms
    "vanakkam", "eppadi", "irukinga", "irukeenga", "epdi", "nandri", "nanba",
    "thozha", "thalaiva", "machan", "vishayam",
    # pronouns / verbs
    "pannunga", "pannnu", "pannu", "paarungal", "paarunga", "paaru",
    "solunga", "sollu", "sollunga", "solren", "solven", "pesuren", "pesuven",
    "iruku", "irukku", "illa", "illai", "enna", "yenna",
    "evlo", "naan", "naanga", "neenga", "avan", "aval", "avanga",
    "vandhaachu", "pogaren", "vaarunga", "vaanga", "vaaru",
    "romba", "konjam", "nalla", "kettalama", "seri", "mudiyuma",
    "mail paaru", "inbox paaru", "mail anuppu", "mail anupu",
}

_ROMAN_TE = {
    # greetings & friend terms
    "namaskaram", "ela", "elaa", "unnaru", "bagunnara", "dhanyavadalu",
    "mitrama", "mithrama", "bhayya", "sangathi", "ippudu",
    # pronouns / verbs / fillers
    "cheyyi", "cheyandu", "cheyagalavu", "cheseyyi", "cheyyandi",
    "cheppandi", "cheppu", "cheppu-ga", "chusta", "chustanu",
    "ledu", "undi", "unte", "avutundi", "avutadha", "avadhu",
    "nenu", "meeru", "meeru-ku", "vaadu", "vaadiki", "vaatiki",
    "emiti", "emiti-ra", "evaru", "enduku",
    "chala", "konchem", "manchidi", "manchiga", "okay-ga",
    "mail cheyyi", "mail padandi", "inbox chudandi", "inbox chuu",
}

# Map sets → language codes (as string; we resolve at call-site)
_ROMAN_SETS: list[tuple[set[str], str]] = [
    (_ROMAN_KN, "kn"),
    (_ROMAN_HI, "hi"),
    (_ROMAN_TA, "ta"),
    (_ROMAN_TE, "te"),
]


def _count_unicode(text: str) -> dict[str, int]:
    return {
        "kn": len(_KANNADA_RANGE.findall(text)),
        "hi": len(_HINDI_RANGE.findall(text)),
        "ta": len(_TAMIL_RANGE.findall(text)),
        "te": len(_TELUGU_RANGE.findall(text)),
    }


def _roman_detect(text: str) -> str | None:
    """Returns language code string if a Romanized keyword matches, else None."""
    words = set(re.sub(r"[^\w\s]", " ", text.lower()).split())
    best_lang = None
    best_count = 0
    for kw_set, lang in _ROMAN_SETS:
        hits = len(words & kw_set)
        if hits > best_count:
            best_count = hits
            best_lang = lang
    # Require at least 1 confident keyword
    return best_lang if best_count >= 1 else None


def detect_language_fast(text: str) -> str:
    """
    Offline heuristic language detection.
    Returns a language code string: 'en' | 'kn' | 'hi' | 'ta' | 'te'.
    """
    if not text or not text.strip():
        return "en"

    # Step 1 — Unicode block counts (native script)
    counts = _count_unicode(text)
    max_count = max(counts.values())
    if max_count >= 2:   # at least 2 chars in a script → confident detection
        lang = max(counts, key=counts.__getitem__)
        return lang

    # Step 2 — Romanized keyword match
    roman = _roman_detect(text)
    if roman:
        return roman

    # Step 3 — Single Indic character (less confident, use it anyway)
    if max_count == 1:
        lang = max(counts, key=counts.__getitem__)
        return lang

    return "en"


def detect_language(text: str, gemini_model=None) -> str:
    """
    Full language detection: fast heuristic first, Gemini fallback if ambiguous.

    Args:
        text: The user's raw input string.
        gemini_model: Optional pre-configured genai.GenerativeModel instance.
                      If None, skips the Gemini step.

    Returns:
        Language code string: 'en' | 'kn' | 'hi' | 'ta' | 'te'
    """
    fast_result = detect_language_fast(text)

    # If the fast heuristic is confident (non-English), trust it
    if fast_result != "en":
        return fast_result

    # For short pure-English-looking input, try Gemini if available
    if gemini_model is not None and len(text.strip()) > 3:
        try:
            prompt = (
                "Detect the language of the following user message.\n"
                "Reply with ONLY ONE of these codes: en, kn, hi, ta, te\n"
                "- en = English\n"
                "- kn = Kannada (native script OR Romanized like 'mail check maadu')\n"
                "- hi = Hindi (native script OR Romanized like 'mail bhejo')\n"
                "- ta = Tamil (native script OR Romanized like 'mail anuppu')\n"
                "- te = Telugu (native script OR Romanized like 'mail cheyyi')\n\n"
                f"Message: {text}\n\nLanguage code:"
            )
            response = gemini_model.generate_content(prompt)
            code = response.text.strip().lower().split()[0]
            if code in {"en", "kn", "hi", "ta", "te"}:
                return code
        except Exception as exc:
            print(f"[language_detector] Gemini detection failed: {exc}", file=sys.stderr)

    return fast_result


# ── Language → instruction string injected into Cortex system prompt ─────────
_LANG_INSTRUCTION: dict[str, str] = {
    "en": "",  # English is default; friendly persona is defined in base prompt
    "kn": (
        "The user is speaking Kannada (or Kanglish). "
        "MANDATORY: You MUST respond warmly, fluently, and naturally in Kannada, just like a close, smart friend or Alexa/ChatGPT. "
        "Use natural, idiomatic, spoken Kannada (e.g., 'ಖಂಡಿತ ಸ್ನೇಹಿತರೇ', 'ನಾನು ತುಂಬಾ ಚೆನ್ನಾಗಿದ್ದೇನೆ', 'ಹೇಳಿ, ನಿಮಗಾಗಿ ಏನು ಮಾಡಲಿ?'). "
        "All conversational responses and the 'answer' field MUST be in natural Kannada script. "
        "Mix common English technical terms (email, app, browser, search) naturally where appropriate. "
        "Never sound robotic, stiff, or bureaucratic. Be warm, attentive, and helpful."
    ),
    "hi": (
        "The user is speaking Hindi (or Hinglish). "
        "MANDATORY: You MUST respond warmly, fluently, and naturally in Hindi, just like a close friend or Alexa/ChatGPT. "
        "Use warm, conversational, everyday Hindi (e.g., 'अरे बिल्कुल दोस्त!', 'मैं एकदम बढ़िया हूँ, आप बताइए!'). "
        "All conversational responses and the 'answer' field MUST be in Devanagari Hindi script. "
        "Mix common English terms naturally as spoken in modern conversation. "
        "Never sound like a rigid machine. Be engaging, friendly, and helpful."
    ),
    "ta": (
        "The user is speaking Tamil (or Tanglish). "
        "MANDATORY: You MUST respond warmly, fluently, and naturally in Tamil, like a friendly, intelligent companion. "
        "Use natural spoken Tamil phrasing (e.g., 'நிச்சயமா நண்பா!', 'நான் ரொம்ப நல்லா இருக்கேன், சொல்லுங்க!'). "
        "All conversational responses and the 'answer' field MUST be in Tamil script. "
        "Mix English technical terms naturally. Be warm, supportive, and conversational."
    ),
    "te": (
        "The user is speaking Telugu (or Tenglish). "
        "MANDATORY: You MUST respond warmly, fluently, and naturally in Telugu, like a friendly, smart companion. "
        "Use natural spoken Telugu phrasing (e.g., 'తప్పకుండా మిత్రమా!', 'నేను చాలా బాగున్నాను, చెప్పండి!'). "
        "All conversational responses and the 'answer' field MUST be in Telugu script. "
        "Mix English technical terms naturally. Be warm, conversational, and energetic."
    ),
}


def language_instruction(lang_code: str) -> str:
    """Returns the system-prompt instruction snippet for a language code."""
    return _LANG_INSTRUCTION.get(lang_code, "")

