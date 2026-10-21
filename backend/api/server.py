from __future__ import annotations
import os
import io
import sys
from pathlib import Path
from typing import Optional, List

# ── PATH must be set BEFORE importing speech_recognition ──────────────────────
# SpeechRecognition uses shutil.which("flac") at import time on some platforms.
# Prepend our native ARM64 flac wrapper so it is found before the broken x86 binary.
ROOT = Path(__file__).resolve().parents[2]
bin_path = str(ROOT / "backend" / "core" / "bin")
if not Path(bin_path).exists():
    bin_path = str(ROOT / "cloud-brain" / "bin")
if bin_path not in os.environ.get("PATH", ""):
    os.environ["PATH"] = f"{bin_path}:{os.environ.get('PATH', '')}"

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn
import speech_recognition as sr

sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "shared-sdk" / "python"))
sys.path.insert(0, str(ROOT / "automation-engine"))
sys.path.insert(0, str(ROOT / "memory-service"))
sys.path.insert(0, str(ROOT / "cloud-brain" / "app"))

try:
    from backend.agent.orchestrator import CortexOrchestrator
    from backend.api.voice_ui import VOICE_UI
except ImportError:
    from orchestrator import CortexOrchestrator
    from voice_ui import VOICE_UI

app = FastAPI(title="Cortex Cloud Brain", version="0.2.0")

# Setup CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

orchestrator = CortexOrchestrator()

class ChatRequest(BaseModel):
    message: str
    source: str = "text"

class ApproveRequest(BaseModel):
    approved: bool

@app.get("/", response_class=HTMLResponse)
async def get_index():
    return VOICE_UI

@app.get("/health")
async def get_health():
    return {"ok": True, "service": "cortex-cloud-brain"}

@app.get("/memory")
async def get_memory():
    return {"items": orchestrator.memories()}

@app.get("/tasks/{task_id}/events")
async def get_task_events(task_id: str):
    try:
        return {"events": orchestrator.events(task_id)}
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/chat")
async def post_chat(req: ChatRequest):
    message = req.message.strip()
    if not message:
        raise HTTPException(status_code=400, detail="message is required")
    try:
        return orchestrator.chat(message, req.source)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/audio_chat")
async def post_audio_chat(request: Request):
    """
    Accepts raw WAV audio data from the desktop microphone,
    transcribes it via local/Google speech recognition, and routes it to orchestrator.chat().
    """
    audio_bytes = await request.body()
    if not audio_bytes or len(audio_bytes) < 400:
        return {"transcript": "", "message": "I didn't catch that — could you say it again?", "task": None}

    transcript = ""
    try:
        r = sr.Recognizer()
        with sr.AudioFile(io.BytesIO(audio_bytes)) as source:
            audio = r.record(source)
        transcript = r.recognize_google(audio).strip()
    except sr.UnknownValueError:
        return {"transcript": "", "message": "I didn't catch that — could you say it again?", "task": None}
    except Exception as e:
        print(f"[cortex] Speech recognition error: {e}", file=sys.stderr)
        return {"transcript": "", "message": "I had trouble hearing clearly. Please try again.", "task": None}

    if not transcript:
        return {"transcript": "", "message": "I didn't hear anything.", "task": None}

    result = orchestrator.chat(transcript, source="voice")
    result["transcript"] = transcript
    return result

@app.post("/tasks/{task_id}/approve")
async def post_approve(task_id: str, req: ApproveRequest):
    try:
        return orchestrator.approve(task_id, req.approved)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/tasks/{task_id}/cancel")
async def post_cancel(task_id: str):
    try:
        return orchestrator.cancel(task_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

class EditDraftRequest(BaseModel):
    recipient: Optional[str] = None
    subject: Optional[str] = None
    body: Optional[str] = None
    sender_account: Optional[str] = None
    attachments: Optional[List[str]] = None

class OAuthCallbackRequest(BaseModel):
    code: str
    redirect_uri: str

@app.post("/tasks/{task_id}/edit")
async def post_edit_draft(task_id: str, req: EditDraftRequest):
    try:
        return orchestrator.edit_pending_draft(
            task_id=task_id,
            recipient=req.recipient,
            subject=req.subject,
            body=req.body,
            sender_account=req.sender_account,
            attachments=req.attachments,
        )
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/email/accounts")
async def get_email_accounts():
    """List connected email accounts across Apple Mail and Gmail."""
    try:
        from providers.manager import MailProviderManager
        mgr = MailProviderManager(dry_run=False)
        return {"accounts": mgr.list_accounts()}
    except Exception as e:
        return {"accounts": [], "error": str(e)}

@app.get("/email/auth/url")
async def get_gmail_auth_url(redirect_uri: str = "http://127.0.0.1:8765/email/auth/callback"):
    """Get Google OAuth2 authorization URL for Gmail consent."""
    try:
        from providers.gmail_provider import GmailProvider
        gmail = GmailProvider()
        url = gmail.get_authorization_url(redirect_uri=redirect_uri)
        return {"url": url, "redirect_uri": redirect_uri}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/email/auth/callback")
async def post_gmail_auth_callback(req: OAuthCallbackRequest):
    """Exchange authorization code for Gmail tokens."""
    try:
        from providers.gmail_provider import GmailProvider
        gmail = GmailProvider()
        res = gmail.exchange_code(req.code, req.redirect_uri)
        return res
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/email/disconnect")
async def post_email_disconnect(provider_name: str = "gmail"):
    """Disconnect and revoke provider credentials."""
    try:
        from providers.manager import MailProviderManager
        mgr = MailProviderManager(dry_run=False)
        prov = mgr.providers.get(provider_name.lower())
        if prov:
            return prov.disconnect()
        return {"ok": False, "error": f"Unknown provider {provider_name}"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

def main() -> None:
    host = "127.0.0.1"
    port = 8765
    print(f"Cortex backend listening on http://{host}:{port}")
    uvicorn.run(app, host=host, port=port, log_level="info")

if __name__ == "__main__":
    main()
