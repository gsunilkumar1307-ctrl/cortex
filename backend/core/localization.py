"""
localization.py — Multilingual Localization System for Cortex
Provides native, warm, and natural localized responses across:
- English (en)
- Kannada (kn)
- Hindi (hi)
- Tamil (ta)
- Telugu (te)
"""
from __future__ import annotations

import re
from typing import Any

# ── Localized Message Templates ──────────────────────────────────────────────
_TEMPLATES: dict[str, dict[str, str]] = {
    "app_opened": {
        "en": "Opened {app_name}.",
        "kn": "{app_name} ತೆರೆಯಲಾಗಿದೆ.",
        "hi": "{app_name} खोल दिया गया है।",
        "ta": "{app_name} திறக்கப்பட்டது.",
        "te": "{app_name} తెరవబడింది.",
    },
    "app_closed": {
        "en": "Closed {app_name}.",
        "kn": "{app_name} ಮುಚ್ಚಲಾಗಿದೆ.",
        "hi": "{app_name} बंद कर दिया गया है।",
        "ta": "{app_name} மூடப்பட்டது.",
        "te": "{app_name} మూసివేయబడింది.",
    },
    "app_focused": {
        "en": "Switched to {app_name}.",
        "kn": "{app_name} ಗೆ ಬದಲಾಯಿಸಲಾಗಿದೆ.",
        "hi": "{app_name} पर स्विच किया गया।",
        "ta": "{app_name} க்கு மாற்றப்பட்டது.",
        "te": "{app_name} కి మార్చబడింది.",
    },
    "screenshot_taken": {
        "en": "Screenshot captured.",
        "kn": "ಸ್ಕ್ರೀನ್‌ಶಾಟ್ ತೆಗೆದುಕೊಳ್ಳಲಾಗಿದೆ.",
        "hi": "स्क्रीनशॉट ले लिया गया है।",
        "ta": "ஸ்கிரீன்ஷாட் எடுக்கப்பட்டது.",
        "te": "స్క్రీన్ షాట్ తీయబడింది.",
    },
    "calc_result": {
        "en": "{expression} = {result}",
        "kn": "ಲೆಕ್ಕ: {expression} = {result}",
        "hi": "परिणाम: {expression} = {result}",
        "ta": "முடிவு: {expression} = {result}",
        "te": "ఫలితం: {expression} = {result}",
    },
    "need_recipient": {
        "en": "Who would you like to email? Please specify the recipient's name or email address.",
        "kn": "ನೀವು ಯಾರಿಗೆ ಇಮೇಲ್ ಕಳುಹಿಸಲು ಬಯಸುತ್ತೀರಿ? ದಯವಿಟ್ಟು ಅವರ ಹೆಸರು ಅಥವಾ ಇಮೇಲ್ ವಿಳಾಸವನ್ನು ತಿಳಿಸಿ.",
        "hi": "आप किसे ईमेल भेजना चाहते हैं? कृपया नाम या ईमेल पता बताएं।",
        "ta": "நீங்கள் யாருக்கு மின்னஞ்சல் அனுப்ப விரும்புகிறீர்கள்? தயவுசெய்து பெயர் அல்லது மின்னஞ்சல் முகவரியைக் குறிப்பிடவும்.",
        "te": "మీరు ఎవరికి ఇమెయిల్ పంపాలనుకుంటున్నారు? దయచేసి పేరు లేదా ఇమెయిల్ చిరునామాను పేర్కొనండి.",
    },
    "need_body": {
        "en": "What would you like me to send to {recipient}?",
        "kn": "{recipient} ಅವರಿಗೆ ಯಾವ ಸಂದೇಶವನ್ನು ಕಳುಹಿಸಬೇಕು?",
        "hi": "आप {recipient} को क्या संदेश भेजना चाहते हैं?",
        "ta": "{recipient} அவர்களுக்கு என்ன செய்தி அனுப்ப வேண்டும்?",
        "te": "{recipient} కి మీరు ఏ సందೇಶాన్ని పంపాలనుకుంటున్నారు?",
    },
    "need_note_body": {
        "en": "What would you like to write in the note '{title}'?",
        "kn": "'{title}' ನೋಟ್‌ನಲ್ಲಿ ನೀವು ಏನನ್ನು ಬರೆಯಲು ಬಯಸುತ್ತೀರಿ?",
        "hi": "'{title}' नोट में आप क्या लिखना चाहते हैं?",
        "ta": "'{title}' குறிப்பில் நீங்கள் என்ன எழுத விரும்புகிறீர்கள்?",
        "te": "'{title}' నోట్‌లో మీరు ఏమి వ్రాయాలనుకుంటున్నారు?",
    },
    "need_message_body": {
        "en": "What message would you like to send to {recipient}?",
        "kn": "{recipient} ಅವರಿಗೆ ಯಾವ ಸಂದೇಶವನ್ನು ಕಳುಹಿಸಲು ಬಯಸುತ್ತೀರಿ?",
        "hi": "आप {recipient} को क्या संदेश भेजना चाहते हैं?",
        "ta": "{recipient} அவர்களுக்கு என்ன செய்தி அனுப்ப விரும்புகிறீர்கள்?",
        "te": "{recipient} కి మీరు ఏ సందೇಶాన్ని పంపాలనుకుంటున్నారు?",
    },
    "draft_prepared_approval": {
        "en": (
            "Draft created:\n"
            "To: {recipient}\n"
            "Subject: {subject}\n"
            "Body: {body}\n\n"
            "I need your approval before I send this email. Should I send it?"
        ),
        "kn": (
            "ಇಮೇಲ್ ಡ್ರಾಫ್ಟ್ ಸಿದ್ಧವಾಗಿದೆ:\n"
            "ಸ್ವೀಕೃತದಾರರು: {recipient}\n"
            "ವಿಷಯ: {subject}\n"
            "ವಿಷಯಾಂಶ: {body}\n\n"
            "ಈ ಇಮೇಲ್ ಕಳುಹಿಸಲು ನಿಮ್ಮ ಅನುಮೋದನೆ ಬೇಕು. ಕಳುಹಿಸುವುದೇ?"
        ),
        "hi": (
            "ईमेल ड्राफ्ट तैयार है:\n"
            "प्राप्तकर्ता: {recipient}\n"
            "विषय: {subject}\n"
            "सामग्री: {body}\n\n"
            "यह ईमेल भेजने से पहले मुझे आपकी अनुमति चाहिए। क्या मैं इसे भेज दूँ?"
        ),
        "ta": (
            "மின்னஞ்சல் வரைவு தயாராக உள்ளது:\n"
            "பெறுநர்: {recipient}\n"
            "பொருள்: {subject}\n"
            "உள்ளடக்கம்: {body}\n\n"
            "இந்த மின்னஞ்சலை அனுப்ப உங்கள் அனுமதி தேவை. அனுப்பவா?"
        ),
        "te": (
            "ఇమెయిల్ డ్రాఫ్ట్ సిద్ధంగా ఉంది:\n"
            "గ్రహీత: {recipient}\n"
            "విషయం: {subject}\n"
            "సారాంశం: {body}\n\n"
            "ఈ ఇమెయిల్ పంపే ముందు మీ అనుమతి అవసరం. పంపమంటారా?"
        ),
    },
    "approval_prompt": {
        "en": "I can prepare this, but I need your approval before I {action}.",
        "kn": "ನಾನು ಇದನ್ನು ಸಿದ್ಧಪಡಿಸಬಲ್ಲೆ, ಆದರೆ {action} ಮಾಡುವ ಮುನ್ನ ನಿಮ್ಮ ಅನುಮೋದನೆ ಅಗತ್ಯವಿದೆ. ಮುಂದುವರಿಯುವುದೇ?",
        "hi": "मैं इसे तैयार कर सकता हूँ, लेकिन {action} करने से पहले आपकी अनुमति चाहिए।",
        "ta": "நான் இதைத் தயாரிக்க முடியும், ஆனால் {action} செய்வதற்கு முன் உங்கள் அனுமதி தேவை.",
        "te": "నేను దీన్ని సిద్ధం చేయగలను, కానీ {action} చేయడానికి ముందు మీ అనుమతి అవసరం.",
    },
    "email_sent": {
        "en": "Email sent to {recipient}.",
        "kn": "{recipient} ಅವರಿಗೆ ಇಮೇಲ್ ಕಳುಹಿಸಲಾಗಿದೆ.",
        "hi": "{recipient} को ईमेल भेज दिया गया है।",
        "ta": "{recipient} அவர்களுக்கு மின்னஞ்சல் அனுப்பப்பட்டது.",
        "te": "{recipient} కి ఇమెయిల్ పంపబడింది.",
    },
    "action_cancelled": {
        "en": "Cancelled.",
        "kn": "ರದ್ದುಗೊಳಿಸಲಾಗಿದೆ.",
        "hi": "रद्द कर दिया गया।",
        "ta": "ரத்து செய்யப்பட்டது.",
        "te": "రద్దు చేయబడింది.",
    },
    "action_done": {
        "en": "Done.",
        "kn": "ಪೂರ್ಣಗೊಂಡಿದೆ.",
        "hi": "हो गया।",
        "ta": "முடிந்தது.",
        "te": "పూర్తయింది.",
    },
    "action_blocked": {
        "en": "This action cannot be performed safely at this time.",
        "kn": "ಸುರಕ್ಷತಾ ಕಾರಣಗಳಿಂದ ಈ ಕ್ರಿಯೆಯನ್ನು ನಿರ್ವಹಿಸಲು ಸಾಧ್ಯವಿಲ್ಲ.",
        "hi": "सुरक्षा कारणों से यह क्रिया पूरी नहीं की जा सकती।",
        "ta": "பாதுகாப்புக் காரணங்களால் இந்த செயலைச் செய்ய முடியாது.",
        "te": "భద్రతా కారణాల వల్ల ఈ చర్యను నిర్వహించలేము.",
    },
    "no_confident_answer": {
        "en": "I don't have a confident answer for '{query}'. Try rephrasing or ask me to search the web for it.",
        "kn": "'{query}' ಗೆ ಸಂಬಂಧಿಸಿದಂತೆ ನಿಖರವಾದ ಉತ್ತರ ಸಿಗಲಿಲ್ಲ. ದಯವಿಟ್ಟು ಬೇರೆ ರೀತಿಯಲ್ಲಿ ಕೇಳಿ ಅಥವಾ ವೆಬ್‌ನಲ್ಲಿ ಹುಡುಕಲು ತಿಳಿಸಿ.",
        "hi": "'{query}' के लिए कोई सटीक उत्तर नहीं मिला। कृपया प्रश्न दोबारा पूछें या वेब पर खोजने को कहें।",
        "ta": "'{query}' க்கு சரியான பதில் கிடைக்கவில்லை. தயவுசெய்து வேறு விதமாக கேட்கவும் அல்லது இணையத்தில் தேடச் சொல்லவும்.",
        "te": "'{query}' కోసం ఖచ్చితమైన సమాధానం లభించలేదు. దయచేసి వేరే విధంగా అడగండి లేదా వెబ్‌లో శోధించమని అడగండి.",
    },
    "inbox_clear": {
        "en": "Your inbox is clear — no recent emails found.",
        "kn": "ನಿಮ್ಮ ಇನ್‌ಬಾಕ್ಸ್ ಖಾಲಿಯಾಗಿದೆ — ಯಾವುದೇ ಹೊಸ ಇಮೇಲ್ ಇಲ್ಲ.",
        "hi": "आपका इनबॉक्स खाली है — कोई नया ईमेल नहीं मिला।",
        "ta": "உங்கள் இன்பாக்ஸ் காலியாக உள்ளது — புதிய மின்னஞ்சல்கள் எதுவும் இல்லை.",
        "te": "మీ ఇన్‌బాక్స్ ఖాళీగా ఉంది — కొత్త ఇమెయిల్‌లు ఏవీ లేవు.",
    },
    "recent_emails": {
        "en": "You have {count} recent emails:\n{emails}",
        "kn": "ನಿಮ್ಮ ಬಳಿ {count} ಇತ್ತೀಚಿನ ಇಮೇಲ್‌ಗಳಿವೆ:\n{emails}",
        "hi": "आपके {count} हालिया ईमेल हैं:\n{emails}",
        "ta": "உங்களிடம் {count} சமீபத்திய மின்னஞ்சல்கள் உள்ளன:\n{emails}",
        "te": "మీకు {count} ఇటీవలి ఇమెయిల్‌లు ఉన్నాయి:\n{emails}",
    },
    "note_written": {
        "en": "Note '{title}' saved.",
        "kn": "'{title}' ನೋಟ್ ಉಳಿಸಲಾಗಿದೆ.",
        "hi": "नोट '{title}' सहेज लिया गया।",
        "ta": "'{title}' குறிப்பு சேமிக்கப்பட்டது.",
        "te": "'{title}' నోట్ సేవ్ చేయబడింది.",
    },
    "message_sent": {
        "en": "Message sent to {recipient}.",
        "kn": "{recipient} ಅವರಿಗೆ ಸಂದೇಶ ಕಳುಹಿಸಲಾಗಿದೆ.",
        "hi": "{recipient} को संदेश भेज दिया गया।",
        "ta": "{recipient} அவர்களுக்கு செய்தி அனுப்பப்பட்டது.",
        "te": "{recipient} కి సందేశం పంపబడింది.",
    },
}

# ── App Name Translations (Indic ↔ English) ───────────────────────────────────
APP_NAME_MAP: dict[str, str] = {
    # Kannada
    "ಕ್ಯಾಲ್ಕುಲೇಟರ್": "Calculator",
    "ಕ್ಯಾಲ್ಕ್ಯುಲೇಟರ್": "Calculator",
    "ಸಫಾರಿ": "Safari",
    "ಕ್ರೋಮ್": "Google Chrome",
    "ಗೂಗಲ್ ಕ್ರೋಮ್": "Google Chrome",
    "ಟರ್ಮಿನಲ್": "Terminal",
    "ನೋಟ್ಸ್": "Notes",
    "ಕ್ಯಾಲೆಂಡರ್": "Calendar",
    "ಮೇಲ್": "Mail",
    "ಇಮೇಲ್": "Mail",
    "ಫೈಂಡರ್": "Finder",
    "ಮ್ಯಾಪ್ಸ್": "Maps",
    "ಸೆಟ್ಟಿಂಗ್ಸ್": "System Settings",

    # Hindi
    "कैलकुलेटर": "Calculator",
    "सफारी": "Safari",
    "क्रोम": "Google Chrome",
    "गूगल क्रोम": "Google Chrome",
    "टर्मिनल": "Terminal",
    "नोट्स": "Notes",
    "कैलेंडर": "Calendar",
    "मेल": "Mail",
    "ईमेल": "Mail",
    "फाइंडर": "Finder",
    "नक्शे": "Maps",
    "सेटिंग्स": "System Settings",

    # Tamil
    "கால்குலேட்டர்": "Calculator",
    "சஃபாரி": "Safari",
    "குரோம்": "Google Chrome",
    "கூகிள் குரோம்": "Google Chrome",
    "டெர்மினல்": "Terminal",
    "நோட்ஸ்": "Notes",
    "கேலெண்டர்": "Calendar",
    "மெயில்": "Mail",
    "மின்னஞ்சல்": "Mail",

    # Telugu
    "క్యాలిక్యులేటర్": "Calculator",
    "సఫారి": "Safari",
    "క్రోమ్": "Google Chrome",
    "గూగుల్ క్రోమ్": "Google Chrome",
    "టెర్మినల్": "Terminal",
    "నోట్స్": "Notes",
    "క్యాలెండర్": "Calendar",
    "మెయిల్": "Mail",
    "ఇమెయిల్": "Mail",
}


def normalize_app_name(raw_name: str) -> str:
    """Normalizes multilingual app names to standard system app names."""
    trimmed = raw_name.strip().strip("'\"")
    # Exact lookup
    if trimmed in APP_NAME_MAP:
        return APP_NAME_MAP[trimmed]
    lower = trimmed.lower()
    for indic_name, eng_name in APP_NAME_MAP.items():
        if indic_name in trimmed:
            return eng_name
    return trimmed


def localize(key: str, lang: str = "en", **kwargs: Any) -> str:
    """Retrieves and formats a localized template string for the target language."""
    code = lang if lang in ("en", "kn", "hi", "ta", "te") else "en"
    key_dict = _TEMPLATES.get(key, {})
    template = key_dict.get(code) or key_dict.get("en", "")
    if not template:
        return kwargs.get("fallback", "")
    try:
        return template.format(**kwargs)
    except Exception:
        return template


# ── Curated Multilingual Knowledge & Greeting Responses ────────────────────────

def get_cortex_identity(lang_code: str) -> str:
    """Returns warm, localized self-identity for Cortex."""
    if lang_code == "kn":
        return "ನಮಸ್ಕಾರ! ನಾನು ಕಾರ್ಟೆಕ್ಸ್ — ನಿಮ್ಮ AI ಡೆಸ್ಕ್‌ಟಾಪ್ ಸಹಾಯಕ. ಅಪ್ಲಿಕೇಶನ್ ತೆರೆಯುವುದು, ಇಮೇಲ್, ವೆಬ್ ಹುಡುಕಾಟ, ಅಥವಾ ಯಾವುದೇ ಪ್ರಶ್ನೆಗೆ ಉತ್ತರಿಸಲು ನಾನು ಸಿದ್ಧನಿದ್ದೇನೆ."
    elif lang_code == "hi":
        return "नमस्ते! मैं Cortex हूँ — आपका AI डेस्कटॉप असिस्टेंट। ऐप्स खोलना, ईमेल, वेब सर्च, या कोई भी सवाल — सब में मदद करता हूँ।"
    elif lang_code == "ta":
        return "வணக்கம்! நான் Cortex — உங்கள் AI டெஸ்க்டாப் உதவியாளர். ஆப்கள் திறப்பது, மெயில், வலை தேடல் அல்லது எந்த கேள்விக்கும் பதில் சொல்வேன்."
    elif lang_code == "te":
        return "నమస్కారం! నేను Cortex — మీ AI డెస్క్‌టాప్ అసిస్టెంట్. యాప్స్ తెరవడం, ఇమెయిల్, వెబ్ సెర్చ్ లేదా ఏ ప్రశ్నకైనా జవాబు చెప్పగలను."
    return "Hello! I'm Cortex — your AI desktop assistant. I can open apps, search the web, answer questions, manage email, and control your computer."


def get_cortex_status(lang_code: str) -> str:
    """Returns warm, localized status ('How are you?') response."""
    if lang_code == "kn":
        return "ನಾನು ತುಂಬಾ ಚೆನ್ನಾಗಿದ್ದೇನೆ, ಧನ್ಯವಾದಗಳು! ನಿಮಗೆ ಹೇಗೆ ಸಹಾಯ ಮಾಡಲಿ?"
    elif lang_code == "hi":
        return "मैं बहुत अच्छा हूँ, धन्यवाद! मैं आपकी क्या मदद कर सकता हूँ?"
    elif lang_code == "ta":
        return "நான் நலமாக இருக்கிறேன், நன்றி! உங்களுக்கு எப்படி உதவ வேண்டும்?"
    elif lang_code == "te":
        return "నేను బాగున్నాను, ధನ್ಯవాదాలు! నేను మీకు ఎలా సహాయపడగలను?"
    return "I'm doing great, thank you! How can I help you today?"


def get_offline_knowledge(query: str, lang_code: str) -> str | None:
    """
    Offline factual knowledge fallback for frequent general knowledge questions
    in Indic languages and English.
    """
    q = query.lower().strip()

    # Capital of India
    if any(p in q for p in ("capital of india", "ಭಾರತದ ರಾಜಧಾನಿ", "भारत की राजधानी", "இந்தியாவின் தலைநகரம்", "భారతదేశ రాజధాని")):
        if lang_code == "kn":
            return "ಭಾರತದ ರಾಜಧಾನಿ ನವದೆಹಲಿ."
        elif lang_code == "hi":
            return "भारत की राजधानी नई दिल्ली है।"
        elif lang_code == "ta":
            return "இந்தியாவின் தலைநகரம் புது தில்லி ஆகும்."
        elif lang_code == "te":
            return "భారతదేశ రాజధాని న్యూఢిల్లీ."
        return "The capital of India is New Delhi."

    # Capital of Karnataka
    if any(p in q for p in ("capital of karnataka", "ಕರ್ನಾಟಕದ ರಾಜಧಾನಿ", "कर्नाटक की राजधानी", "கர்நாடகாவின் தலைநகரம்", "కర్ణాటక రాజధాని")):
        if lang_code == "kn":
            return "ಕರ್ನಾಟಕದ ರಾಜಧಾನಿ ಬೆಂಗಳೂರು."
        elif lang_code == "hi":
            return "कर्नाटक की राजधानी बेंगलुरु है।"
        elif lang_code == "ta":
            return "கர்நாடகாவின் தலைநகரம் பெங்களூரு ஆகும்."
        elif lang_code == "te":
            return "కర్ణాటక రాజధాని బెంగళూరు."
        return "The capital of Karnataka is Bengaluru."

    # Capital of Tamil Nadu
    if any(p in q for p in ("capital of tamil nadu", "capital of tamilnadu", "ತಮಿಳುನಾಡಿನ ರಾಜಧಾನಿ", "तमिलनाडु की राजधानी", "தமிழ்நாட்டின் தலைநகரம்", "తమిళనాడు రాజధాని")):
        if lang_code == "kn":
            return "ತಮಿಳುನಾಡಿನ ರಾಜಧಾನಿ ಚೆನ್ನೈ."
        elif lang_code == "hi":
            return "तमिलनाडु की राजधानी चेन्नई है।"
        elif lang_code == "ta":
            return "தமிழ்நாட்டின் தலைநகரம் சென்னை ஆகும்."
        elif lang_code == "te":
            return "తమిళనాడు రాజధాని చెన్నై."
        return "The capital of Tamil Nadu is Chennai."

    # Capital of Telangana / AP
    if any(p in q for p in ("capital of telangana", "ತೆಲಂಗಾಣದ ರಾಜಧಾನಿ", "तेलंगाना की राजधानी", "తెలంగాణ రాజధాని")):
        if lang_code == "kn":
            return "ತೆಲಂಗಾಣದ ರಾಜಧಾನಿ ಹೈದರಾಬಾದ್."
        elif lang_code == "hi":
            return "तेलंगाना की राजधानी हैदराबाद है।"
        elif lang_code == "te":
            return "తెలంగాణ రాజధాని హైదరాబాద్."
        return "The capital of Telangana is Hyderabad."

    # Sun rises in east
    if any(p in q for p in ("sun rise", "sun rises", "ಸೂರ್ಯ ಯಾವ ದಿಕ್ಕಿನಲ್ಲಿ", "ಸೂರ್ಯ ಹುಟ್ಟುವುದು", "सूर्य किस दिशा", "சூரியன் எந்த திசை", "సూర్యుడు ఏ దిక్కున")):
        if lang_code == "kn":
            return "ಸೂರ್ಯ ಪೂರ್ವ ದಿಕ್ಕಿನಲ್ಲಿ ಹುಟ್ಟುತ್ತಾನೆ."
        elif lang_code == "hi":
            return "सूर्य पूर्व दिशा में उगता है।"
        elif lang_code == "ta":
            return "சூரியன் கிழக்கு திசையில் உதிக்கிறது."
        elif lang_code == "te":
            return "సూర్యుడు తూర్పున ఉదయిస్తాడు."
        return "The Sun rises in the East."

    # What is AI
    if any(p in q for p in ("what is ai", "what is artificial intelligence", "ಕೃತಕ ಬುದ್ಧಿಮತ್ತೆ", "आर्टिफिशियल इंटेलिजेंस", "செயற்கை நுண்ணறிவு", "కృత్రిమ మేధస్సు")):
        if lang_code == "kn":
            return "ಕೃತಕ ಬುದ್ಧಿಮತ್ತೆ (AI) ಎಂದರೆ ಮಾನವ ಬುದ್ಧಿಮತ್ತೆಯಂತೆ ಯೋಚಿಸುವ, ಕಲಿಯುವ ಮತ್ತು ಕಾರ್ಯಗಳನ್ನು ನಿರ್ವಹಿಸುವಂತೆ ವಿನ್ಯಾಸಗೊಳಿಸಲಾದ ಗಣಕ ತಂತ್ರಜ್ಞಾನವಾಗಿದೆ."
        elif lang_code == "hi":
            return "आर्टिफिशियल इंटेलिजेंस (AI) कंप्यूटर विज्ञान की एक तकनीक है जो मशीनों को इंसानों की तरह सोचने, समझने और सीखने में सक्षम बनाती है।"
        elif lang_code == "ta":
            return "செயற்கை நுண்ணறிவு (AI) என்பது மனிதர்களைப் போல சிந்திக்கும், கற்கும் மற்றும் பணிகளைச் செய்யும் கணினித் தொழில்நுட்பமாகும்."
        elif lang_code == "te":
            return "కృత్రిమ మేధస్సు (AI) అనేది మానవుల వలె ఆలోచించడానికి, నేర్చుకోవడానికి కంప్యూటర్లు రూపొందించిన సాంకేతికత."
        return "Artificial Intelligence (AI) is the simulation of human intelligence by machines, enabling them to learn, reason, and solve problems."

    return None
