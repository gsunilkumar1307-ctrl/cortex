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
    "clarify_ambiguous": {
        "en": "I'm not quite sure I understood. Could you please clarify what you would like to do? You can ask me to draft or send an email, translate text, open an app, or search information.",
        "kn": "ನಿಮ್ಮ ಉದ್ದೇಶ ಸ್ಪಷ್ಟವಾಗಿ ತಿಳಿಯಲಿಲ್ಲ. ದಯವಿಟ್ಟು ನೀವು ಏನು ಮಾಡಲು ಬಯಸುತ್ತೀರಿ ಎಂದು ಸ್ಪಷ್ಟಪಡಿಸುವಿರಾ? ನೀವು ಇಮೇಲ್ ರಚಿಸಲು, ಭಾಷಾಂತರಿಸಲು ಅಥವಾ ಪ್ರಶ್ನೆ ಕೇಳಲು ಹೇಳಬಹುದು.",
        "hi": "मुझे आपका अनुरोध पूरी तरह समझ नहीं आया। कृपया स्पष्ट करें कि आप क्या करना चाहते हैं? आप मुझसे ईमेल लिखने, अनुवाद करने या सवाल पूछने के लिए कह सकते हैं।",
        "ta": "உங்கள் நோக்கம் சரியாகப் புரியவில்லை. நீங்கள் என்ன செய்ய விரும்புகிறீர்கள் என்பதைத் தெளிவுபடுத்த முடியுமா? மின்னஞ்சல் எழுத, மொழிபெயர்க்க அல்லது தகவல்களைத் தேடக் கேட்கலாம்.",
        "te": "మీరు ఏమి చేయాలనుకుంటున్నారో నాకు స్పష్టంగా అర్థం కాలేదు. దయచేసి స్పష్టం చేయగలరా? మీరు ఇమెయిల్ రాయమని, అనువదించమని లేదా సమాచారం కోసం అడగవచ్చు.",
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
        return "ನಮಸ್ಕಾರ ಸ್ನೇಹಿತರೇ! ನಾನು ಕಾರ್ಟೆಕ್ಸ್ — ನಿಮ್ಮ ಆಪ್ತ AI ಸಹಾಯಕ ಮತ್ತು ಮಿತ್ರ. ಅಪ್ಲಿಕೇಶನ್‌ಗಳು, ಇಮೇಲ್, ವೆಬ್ ಹುಡುಕಾಟ ಅಥವಾ ಯಾವುದೇ ವಿಷಯವಿರಲಿ — ನಿಮ್ಮ ಜೊತೆ ಮಾತನಾಡಿ ಸಹಾಯ ಮಾಡಲು ಸದಾ ಸಿದ್ಧ!"
    elif lang_code == "hi":
        return "नमस्ते दोस्त! मैं Cortex हूँ — आपका सच्चा AI असिस्टेंट और साथी। ऐप्स खोलना, ईमेल, वेब सर्च, या किसी भी सवाल पर बात करना — मैं हमेशा आपके साथ हूँ!"
    elif lang_code == "ta":
        return "வணக்கம் நண்பா! நான் Cortex — உங்கள் அன்பான AI தோழன். ஆப்கள் திறப்பது, மெயில், இணையத் தேடல் எதுவானாலும் உங்களுக்கு உதவ நான் தயார்!"
    elif lang_code == "te":
        return "నమస్కారం మిత్రమా! నేను Cortex — మీ ఆప్త AI స్నేహితుడిని. యాప్స్ తెరవడం, ఇమెయిల్స్, వెబ్ సెర్చ్ లేదా ఏదైనా విషయం గురించి మాట్లాడటానికి నేను ఎప్పుడూ సిద్ధమే!"
    return "Hey there! I'm Cortex — your friendly AI companion. Whether it's managing your desktop, searching the web, sending emails, or chatting about anything under the sun, I'm right here with you!"


def get_cortex_capabilities(lang_code: str = "en") -> str:
    """Returns authoritative, current integration and capability status for Cortex."""
    if lang_code == "kn":
        return (
            "### ಕಾರ್ಟೆಕ್ಸ್ ಸಾಮರ್ಥ್ಯಗಳು ಮತ್ತು ಸ್ಥಿತಿ (Cortex Capabilities)\n\n"
            "**ಈ ಮ್ಯಾಕ್‌ನಲ್ಲಿ ಲಭ್ಯವಿರುವ ಪರಿಶೀಲಿಸಿದ ಸಾಮರ್ಥ್ಯಗಳು:**\n"
            "1. **ನೈಸರ್ಗಿಕ ಸಂಭಾಷಣೆ ಮತ್ತು ಸಾಮಾನ್ಯ ಜ್ಞಾನ**: ಕನ್ನಡ, ಇಂಗ್ಲಿಷ್, ಹಿಂದಿ ಮತ್ತು ಮಿಶ್ರ Kanglish/Hinglish ಭಾಷೆಗಳಲ್ಲಿ ಸುಲಭ ಸಂಭಾಷಣೆ.\n"
            "2. **ಸಫಾರಿ ವೆಬ್ ಸಂಶೋಧನೆ (Safari Web Research)**: ಸಫಾರಿ ತೆರೆದು ನೈಜ-ಸಮಯದ ಹುಡುಕಾಟ, ಲೇಖನ ಪರಿಶೀಲನೆ ಮತ್ತು ಮೂಲ ಲಿಂಕ್‌ಗಳೊಂದಿಗೆ ಸಾರಾಂಶ.\n"
            "3. **ಆಪಲ್ ಮೇಲ್ ಆಟೊಮೇಷನ್ (Apple Mail)**: ಹೊಸ ಕರಡು ಇಮೇಲ್ ರಚನೆ, ತಿದ್ದುಪಡಿ ಮತ್ತು ಕಳುಹಿಸುವ ಮುನ್ನ ಕಡ್ಡಾಯ ಅನುಮೋದನೆ ಗೇಟ್.\n"
            "4. **ಫೈಂಡರ್ ಪರಿಶೀಲನೆ (Finder Inspection)**: ಡೌನ್‌ಲೋಡ್ಸ್ ಫೋಲ್ಡರ್‌ನಲ್ಲಿರುವ ಫೈಲ್‌ಗಳನ್ನು ಓದುವ-ಮಾತ್ರ ವಿಧಾನದಲ್ಲಿ ಪಟ್ಟಿ ಮಾಡುವುದು.\n"
            "5. **ಆಪಲ್ ನೋಟ್ಸ್ ನಿರ್ವಹಣೆ (Apple Notes)**: ಹೊಸ ನೋಟ್ ರಚಿಸುವುದು ಮತ್ತು ಅಂಶಗಳನ್ನು (bullets) ಸೇರಿಸುವುದು.\n\n"
            "**ಷರತ್ತುಬದ್ಧ ಅಗತ್ಯತೆಗಳು (ಅನುಮತಿ ಅಗತ್ಯ):**\n"
            "• **ಸ್ಕ್ರೀನ್ ವೀಕ್ಷಣೆ (Screen Observation)**: ಮ್ಯಾಕ್ Accessibility & Screen Recording ಅನುಮತಿಗಳು ಸಕ್ರಿಯವಾಗಿರಬೇಕು.\n"
            "• **ವ್ಯಾಟ್ಸಾಪ್ ಮೆಸೇಜಿಂಗ್ (WhatsApp Desktop)**: WhatsApp Desktop ಇನ್‌ಸ್ಟಾಲ್ ಆಗಿರಬೇಕು (ಕರಡು-ಮಾತ್ರ ರಕ್ಷಣೆ).\n\n"
            "🔒 **ಸುರಕ್ಷತಾ ಮಿತಿಗಳು**: ನಿಮ್ಮ ಸ್ಪಷ್ಟ ಅನುಮೋದನೆಯಿಲ್ಲದೆ ಯಾವುದೇ ಇಮೇಲ್ ಅಥವಾ ಸಂದೇಶವನ್ನು ಸ್ವಯಂಚಾಲಿತವಾಗಿ ಕಳುಹಿಸಲಾಗುವುದಿಲ್ಲ; ಫೈಲ್ ಅಳಿಸುವಿಕೆ ಬೆಂಬಲಿಸುವುದಿಲ್ಲ."
        )
    elif lang_code == "hi":
        return (
            "### Cortex क्षमताएं और सिस्टम स्थिति (Capabilities Status)\n\n"
            "**इस मैक पर सत्यापित और उपलब्ध क्षमताएं:**\n"
            "1. **प्राकृतिक संवाद और बुद्धिमत्ता**: हिंदी, अंग्रेजी, कन्नड़ और Hinglish में सहज बातचीत व संदर्भ समझ।\n"
            "2. **सफारी वेब रिसर्च (Safari Web Research)**: सफारी में सर्च, वेब पेज सामग्री का विश्लेषण और प्रामाणिक सोर्स लिंक के साथ सारांश।\n"
            "3. **एप्पल मेल (Apple Mail)**: ड्राफ्ट तैयार करना, बहु-चरणीय संपादन और भेजने से पहले अनिवार्य उपयोगकर्ता स्वीकृति।\n"
            "4. **फाइंडर फाइल निरीक्षण (Finder Inspection)**: डाउनलोड्स डायरेक्टरी में सुरक्षित रीड-ओनली फाइल सूची प्रदर्शन।\n"
            "5. **एप्पल नोट्स प्रबंधन (Apple Notes)**: नए नोट्स बनाना और बुलेट बिंदु जोड़ना।\n\n"
            "**सिस्टम अनुमतियों के अधीन:**\n"
            "• **स्क्रीन अवलोकन (Screen Observation)**: मैक Accessibility और Screen Recording अनुमतियां आवश्यक हैं।\n"
            "• **व्हाट्सएप डेस्कटॉप (WhatsApp Desktop)**: केवल स्थापित ऐप और सत्यापित संपर्कों के लिए ड्राफ्ट तैयार करना।\n\n"
            "🔒 **सुरक्षा सीमाएं**: बिना आपकी स्पष्ट अनुमति के कोई भी ईमेल या मैसेज नहीं भेजा जाएगा; फाइल विलोपन निषिद्ध है।"
        )
    return (
        "### Cortex System Capabilities & Status\n\n"
        "**Available & Verified on this Mac:**\n"
        "1. **Conversational Intelligence**: Fluent multilingual reasoning (English, Kannada, Hindi, Kanglish, Hinglish) with persistent session context.\n"
        "2. **Safari Web Research**: Live browser activation, web search, real-time article inspection, and structured synthesis with cited URLs.\n"
        "3. **Apple Mail Automation**: Contextual draft creation, iterative revisions across turns, and a strict supervised approval gate.\n"
        "4. **Finder Inspection**: Safe, read-only navigation of user directories (such as Downloads) and visible filename listing without file alterations.\n"
        "5. **Apple Notes Management**: Creating new notes, updating titles, appending bullet points, and foregrounding Notes.\n\n"
        "**Implemented with System Permission / Setup Requirements:**\n"
        "• **macOS Screen Observation**: Multi-source desktop perception (macOS Accessibility API & ScreenCaptureKit); requires Accessibility and Screen Recording permissions in System Settings.\n"
        "• **WhatsApp Desktop Integration**: Recipient resolution and draft staging in visible composer; requires WhatsApp Desktop installed.\n\n"
        "🔒 **Safety Boundaries & Unsupported Operations:**\n"
        "• **Supervised Safety Model**: Consequential actions (sending emails or WhatsApp messages) strictly require your explicit confirmation before execution.\n"
        "• **Non-Destructive Operations**: Cortex does not delete user files or execute destructive terminal commands."
    )


def get_cortex_status(lang_code: str) -> str:
    """Returns warm, localized status ('How are you?') response as a close friend."""
    if lang_code == "kn":
        return "ನಾನು ತುಂಬಾ ಚೆನ್ನಾಗಿದ್ದೇನೆ ಸ್ನೇಹಿತರೇ! ನಿಮ್ಮ ದಿನ ಹೇಗಿದೆ? ಇವತ್ತು ನಿಮಗಾಗಿ ಏನು ಮಾಡಲಿ?"
    elif lang_code == "hi":
        return "मैं एकदम बढ़िया और मस्त हूँ दोस्त! आप बताइए, आज आपके लिए क्या करूँ?"
    elif lang_code == "ta":
        return "நான் ரொம்ப நல்லா இருக்கேன் நண்பா! உங்க நாள் எப்படி போகுது? இன்னைக்கு என்ன உதவி வேணும்?"
    elif lang_code == "te":
        return "నేను చాలా బాగున్నాను మిత్రమా! మీరు ఎలా ఉన్నారు? ಈరోజు ನಿಮಗೆ ಹೇಗೆ ಸಹಾಯ ಮಾಡಲಿ?"
    return "I'm doing fantastic, thanks for asking! How are you doing today, and what can we tackle together?"


def get_offline_knowledge(query: str, lang_code: str) -> str | None:
    """
    Offline factual knowledge fallback for frequent general knowledge questions
    in Indic languages and English.
    """
    q = query.lower().strip()

    # Capital of India
    if any(p in q for p in ("capital of india", "india capital", "india da capital", "ಭಾರತದ ರಾಜಧಾನಿ", "भारत की राजधानी", "bharat ki rajdhani", "bharathada rajadhani", "இந்தியாவின் தலைநகரம்", "భారతదేశ రాజధాని")):
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
    if any(p in q for p in ("capital of karnataka", "karnataka capital", "karnataka da capital", "karnataka rajadhani", "karnatakada rajadhani", "ಕರ್ನಾಟಕದ ರಾಜಧಾನಿ", "कर्नाटक की राजधानी", "கர்நாடகாவின் தலைநகரம்", "కర్ణాటక రాజధాని")):
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

    # Big Bang Theory (Cosmology)
    if any(p in q for p in ("big bang", "big bang theory", "ಮಹಾಸ್ಪೋಟ", "महाविस्फोट", "பெருவெடிப்பு")):
        if lang_code == "kn":
            return "ಮಹಾಸ್ಪೋಟ ಸಿದ್ಧಾಂತ (Big Bang Theory) ವಿಶ್ವದ ಉಗಮ ಮತ್ತು ವಿಕಾಸವನ್ನು ವಿವರಿಸುವ ಪ್ರಮುಖ ವೈಜ್ಞಾನಿಕ ಸಿದ್ಧಾಂತವಾಗಿದೆ. ಸುಮಾರು 13.8 ಶತಕೋಟಿ ವರ್ಷಗಳ ಹಿಂದೆ ಅಗಾಧವಾದ ಸಾಂದ್ರತೆ ಮತ್ತು ತಾಪಮಾನದ ಒಂದು ಏಕೈಕ ಬಿಂದುವಿನಿಂದ ವಿಶ್ವವು ನಿರಂತರವಾಗಿ ವಿಸ್ತರಿಸಲಾರಂಭಿಸಿತು ಎಂದು ಇದು ತಿಳಿಸುತ್ತದೆ."
        elif lang_code == "hi":
            return "बिग बैंग सिद्धांत (Big Bang Theory) ब्रह्मांड की उत्पत्ति और विस्तार को समझाने वाला प्रमुख वैज्ञानिक मॉडल है। इसके अनुसार, लगभग 13.8 अरब वर्ष पहले ब्रह्मांड एक अत्यधिक गर्म और घने बिंदु से निरंतर विस्तारित होना शुरू हुआ था।"
        return "The Big Bang theory is the prevailing scientific cosmological model explaining the origin and expansion of the observable universe from an initial high-density, high-temperature state approximately 13.8 billion years ago."

    # Quantum computing
    if any(p in q for p in ("quantum computing", "quantum computer", "ಕ್ವಾಂಟಮ್ ಕಂಪ್ಯೂಟಿಂಗ್", "क्वांटम कंप्यूटिंग")):
        if lang_code == "kn":
            return "ಕ್ವಾಂಟಮ್ ಕಂಪ್ಯೂಟಿಂಗ್ ಎನ್ನುವುದು ಸೂಪರ್‌ಪೊಸಿಷನ್ ಮತ್ತು ಎಂಟಾಂಗಲ್‌ಮೆಂಟ್‌ನಂತಹ ಕ್ವಾಂಟಮ್ ಭೌತಶಾಸ್ತ್ರದ ತತ್ವಗಳನ್ನು ಬಳಸಿಕೊಂಡು ಸಾಂಪ್ರದಾಯಿಕ ಕಂಪ್ಯೂಟರ್‌ಗಳಿಗಿಂತ ಅತ್ಯಂತ ವೇಗವಾಗಿ ಸಂಕೀರ್ಣ ಲೆಕ್ಕಾಚಾರಗಳನ್ನು ನಿರ್ವಹಿಸುವ ಸುಧಾರಿತ ತಂತ್ರಜ್ಞಾನವಾಗಿದೆ."
        elif lang_code == "hi":
            return "क्वांटम कंप्यूटिंग एक उन्नत तकनीक है जो सुपरपोजिशन और एंटैंगलमेंट जैसे क्वांटम यांत्रिकी के सिद्धांतों का उपयोग करके पारंपरिक कंप्यूटरों की तुलना में जटिल गणनाओं को तेजी से हल करती है।"
        return "Quantum computing is a rapidly-emerging technology that harnesses the laws of quantum mechanics, utilizing qubits in superposition and entanglement to solve complex computational problems exponentially faster than classical computers."

    # Bruce Lee
    if "bruce lee" in q or "ಬ್ರೂಸ್ ಲೀ" in q or "ब्रूस ली" in q:
        if lang_code == "kn":
            return "ಬ್ರೂಸ್ ಲೀ (1940–1973) ವಿಶ್ವಪ್ರಸಿದ್ಧ ಮಾರ್ಷಲ್ ಆರ್ಟ್ಸ್ ಪಟು, ತತ್ವಜ್ಞಾನಿ ಮತ್ತು ನಟ. ಅವರು ಜೀತ್ ಕುನೆ ಡೊ (Jeet Kune Do) ಎಂಬ ಹೊಸ ಸಮರಕಲಾ ತತ್ವವನ್ನು ಸ್ಥಾಪಿಸಿ, ಜಾಗತಿಕ ಸಿನೆಮಾರಂಗದಲ್ಲಿ ಮಾರ್ಷಲ್ ಆರ್ಟ್ಸ್‌ಗೆ ಅಪಾರ ಜನಪ್ರಿಯತೆ ತಂದುಕೊಟ್ಟರು."
        elif lang_code == "hi":
            return "ब्रूस ली (1940–1973) एक प्रसिद्ध मार्शल आर्टिस्ट, दार्शनिक और अभिनेता थे। उन्होंने जीत कुने दो (Jeet Kune Do) की स्थापना की और वैश्विक स्तर पर मार्शल आर्ट्स सिनेमा को नई पहचान दिलाई।"
        return "Bruce Lee (1940–1973) was an iconic martial artist, philosopher, and cultural icon who founded Jeet Kune Do and revolutionized martial arts in global cinema."

    return None
