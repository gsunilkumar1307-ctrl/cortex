from __future__ import annotations
import os
import io
import re
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

import wave
import urllib.request
import urllib.parse
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, Response, StreamingResponse
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
    from backend.voice.transcription import VoiceTranscriber, is_audio_silent
    from backend.core.contracts import TaskStatus
except ImportError:
    from orchestrator import CortexOrchestrator
    from voice_ui import VOICE_UI
    from transcription import VoiceTranscriber, is_audio_silent
    from contracts import TaskStatus

try:
    from backend.core.auth import verify_session_token, require_session_auth
except ImportError:
    from auth import verify_session_token, require_session_auth

app = FastAPI(title="Cortex Cloud Brain", version="0.2.0")

# Setup Restricted CORS (Only trusted local Electron / Vite origins)
ALLOWED_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:8000",
    "http://127.0.0.1:8000",
    "cortex://desktop",
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

@app.middleware("http")
async def session_auth_middleware(request: Request, call_next):
    if request.method == "OPTIONS":
        return await call_next(request)
    path = request.url.path
    if path not in {"/", "/health", "/ping", "/docs", "/openapi.json", "/redoc"}:
        if os.getenv("CORTEX_DISABLE_AUTH", "0") != "1":
            token = request.headers.get("X-Cortex-Session")
            if not token:
                from fastapi.responses import JSONResponse
                return JSONResponse(
                    status_code=401,
                    content={"detail": "Unauthorized: Missing X-Cortex-Session token"},
                )
            if not verify_session_token(token):
                from fastapi.responses import JSONResponse
                return JSONResponse(
                    status_code=401,
                    content={"detail": "Unauthorized: Invalid X-Cortex-Session token"},
                )
    return await call_next(request)

orchestrator = CortexOrchestrator()
voice_transcriber = VoiceTranscriber()

class ChatRequest(BaseModel):
    message: str
    source: str = "text"
    preferred_language: Optional[str] = None
    thread_id: Optional[str] = None


class ThreadCreateOrUpdateRequest(BaseModel):
    id: str
    title: Optional[str] = None
    messages: List[dict] = []
    metadata: Optional[dict] = None


class ThreadRenameRequest(BaseModel):
    title: str


class ApproveRequest(BaseModel):
    approved: bool
    approval_hash: Optional[str] = None

class MemoryCreateRequest(BaseModel):
    id: str
    kind: str = "preference"
    payload: dict

@app.get("/", response_class=HTMLResponse)
async def get_index():
    return VOICE_UI

@app.get("/health")
async def get_health():
    return {"ok": True, "service": "cortex-cloud-brain"}

@app.get("/memory")
async def get_memory():
    return {"items": orchestrator.memories()}

@app.post("/memory")
async def post_memory(req: MemoryCreateRequest):
    try:
        orchestrator.memory.put(req.id, req.kind, req.payload)
        return {"ok": True, "id": req.id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/memory/{memory_id}")
async def delete_memory(memory_id: str):
    success = orchestrator.delete_memory(memory_id)
    if not success:
        raise HTTPException(status_code=404, detail=f"Memory {memory_id} not found")
    return {"ok": True, "deleted": memory_id}

@app.delete("/memory")
async def clear_memories(kind: Optional[str] = None):
    count = orchestrator.clear_memories(kind=kind)
    return {"ok": True, "cleared": count}

@app.post("/session/clear")
async def post_session_clear():
    orchestrator.clear_history()
    return {"ok": True, "message": "Conversation history cleared"}

@app.get("/tasks")
async def get_all_tasks(limit: int = 100):
    """Return recent tasks with their audit trails for the activity-log UI."""
    try:
        tasks = orchestrator.task_store.list_all_tasks(limit=limit)
        return {"tasks": [t.to_dict() for t in tasks]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/tasks/{task_id}/events")
async def get_task_events(task_id: str):
    try:
        return {"events": orchestrator.events(task_id)}
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

WAKE_WORD_PATTERNS = [
    r"^(?:hey\s+|ok\s+|okay\s+|hi\s+|hello\s+)?cortex[,\s—–-]*",
    r"^(?:ಹೇ\s+|ನಮಸ್ಕಾರ\s+)?ಕಾರ್ಟೆಕ್ಸ್[,\s—–-]*",
    r"^(?:सुनो\s+|नमस्ते\s+)?कोर्टेक्स[,\s—–-]*",
    r"^(?:ஹே\s+|வணக்கம்\s+)?கார்டெக்ஸ்[,\s—–-]*",
    r"^(?:హే\s+|నమస్కారం\s+)?కార్టెక్స్[,\s—–-]*",
]


def strip_wake_word(text: str) -> str:
    """Strips leading wake phrase if followed by an actionable command."""
    cleaned = text.strip()
    for pattern in WAKE_WORD_PATTERNS:
        match = re.search(pattern, cleaned, flags=re.IGNORECASE)
        if match:
            remainder = cleaned[match.end():].strip()
            if remainder:  # Only strip if there is actual command text following the wake word
                return remainder
    return cleaned


@app.post("/chat")
async def post_chat(req: ChatRequest):
    message = req.message.strip()
    if not message:
        raise HTTPException(status_code=400, detail="message is required")
    try:
        cleaned = strip_wake_word(message)
        return orchestrator.chat(cleaned, req.source, preferred_language=req.preferred_language)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/chat/stream")
async def post_chat_stream(req: ChatRequest, request: Request):
    """
    SSE streaming endpoint for assistant-ui with progressive text delivery,
    real-time tool/task events, and safe cancellation support.
    """
    message = req.message.strip()
    if not message:
        raise HTTPException(status_code=400, detail="message is required")

    async def event_generator():
        import asyncio
        import json
        import datetime

        try:
            cleaned = strip_wake_word(message)
            # Emit start event
            yield f'event: start\ndata: {json.dumps({"status": "started", "query": cleaned, "thread_id": req.thread_id})}\n\n'
            await asyncio.sleep(0.01)

            if await request.is_disconnected():
                return

            # Execute orchestrator in a thread worker so the event loop stays responsive
            result = await asyncio.to_thread(
                orchestrator.chat,
                cleaned,
                req.source,
                preferred_language=req.preferred_language,
            )

            full_msg = result.get("message", "")
            task_dict = result.get("task")
            lang = result.get("task", {}).get("language") if isinstance(result.get("task"), dict) else "en"

            # Stream progressive chunks of words for natural typing/streaming cadence
            words = full_msg.split(" ")
            chunk_size = 4
            for i in range(0, len(words), chunk_size):
                if await request.is_disconnected():
                    return
                chunk = " ".join(words[i:i + chunk_size])
                if i + chunk_size < len(words):
                    chunk += " "
                yield f'event: text_delta\ndata: {json.dumps({"delta": chunk, "index": i})}\n\n'
                await asyncio.sleep(0.018)

            # Emit task execution details / generative UI data
            if task_dict:
                yield f'event: task_update\ndata: {json.dumps({"task": task_dict})}\n\n'

            # Emit final completion
            yield f'event: done\ndata: {json.dumps({"message": full_msg, "task": task_dict, "language": lang})}\n\n'

        except asyncio.CancelledError:
            yield f'event: error\ndata: {json.dumps({"error": "Stream aborted by client"})}\n\n'
        except Exception as ex:
            yield f'event: error\ndata: {json.dumps({"error": str(ex)})}\n\n'

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/threads")
async def get_threads():
    """List all saved conversation threads for sidebar navigation."""
    try:
        threads = orchestrator.memory.list(kind="thread")
        result = []
        for t in threads:
            p = t.get("payload", {})
            result.append({
                "id": t["id"],
                "title": p.get("title", "Untitled Conversation"),
                "preview": p.get("preview", ""),
                "messageCount": len(p.get("messages", [])),
                "createdAt": t.get("createdAt"),
                "updatedAt": p.get("updatedAt", t.get("createdAt")),
            })
        return {"threads": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/threads")
async def post_thread(req: ThreadCreateOrUpdateRequest):
    """Save or update a conversation thread with full message history."""
    try:
        import datetime
        existing = orchestrator.memory.get(req.id)
        preview = ""
        for m in reversed(req.messages):
            c = m.get("content") or m.get("text") or ""
            if isinstance(c, str) and c.strip():
                preview = c.strip()[:100]
                break
            elif isinstance(c, list):
                for part in c:
                    if isinstance(part, dict) and part.get("text"):
                        preview = part["text"][:100]
                        break
                if preview:
                    break

        title = req.title
        if not title:
            if existing and existing.get("title"):
                title = existing["title"]
            else:
                for m in req.messages:
                    if m.get("role") == "user":
                        c = m.get("content")
                        if isinstance(c, str) and c.strip():
                            title = c.strip()[:40]
                            break
                        elif isinstance(c, list):
                            for part in c:
                                if isinstance(part, dict) and part.get("text"):
                                    title = part["text"][:40]
                                    break
                            if title:
                                break
                if not title:
                    title = "New Conversation"

        payload = {
            "title": title,
            "preview": preview,
            "messages": req.messages,
            "metadata": req.metadata or {},
            "updatedAt": datetime.datetime.utcnow().isoformat(),
        }
        orchestrator.memory.put(req.id, "thread", payload)
        return {"ok": True, "id": req.id, "title": title}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/threads/{thread_id}")
async def get_thread(thread_id: str):
    """Retrieve full thread message history."""
    thread = orchestrator.memory.get(thread_id)
    if not thread:
        raise HTTPException(status_code=404, detail=f"Thread {thread_id} not found")
    return {"id": thread_id, "thread": thread}


@app.delete("/threads/{thread_id}")
async def delete_thread(thread_id: str):
    """Delete a conversation thread."""
    deleted = orchestrator.memory.delete(thread_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Thread {thread_id} not found")
    return {"ok": True, "deleted": thread_id}


@app.patch("/threads/{thread_id}")
async def patch_thread(thread_id: str, req: ThreadRenameRequest):
    """Rename a conversation thread."""
    thread = orchestrator.memory.get(thread_id)
    if not thread:
        raise HTTPException(status_code=404, detail=f"Thread {thread_id} not found")
    thread["title"] = req.title.strip()
    orchestrator.memory.put(thread_id, "thread", thread)
    return {"ok": True, "id": thread_id, "title": thread["title"]}

def is_audio_silent(wav_bytes: bytes, threshold: int = 350) -> bool:
    """Checks whether the WAV audio has sufficient energy to contain human speech."""
    try:
        with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
            frames = wf.readframes(wf.getnframes())
            if not frames:
                return True
            import audioop
            rms = audioop.rms(frames, wf.getsampwidth())
            return rms < threshold
    except Exception:
        return False


def transcribe_audio_multilingual(audio_bytes: bytes, preferred_lang: Optional[str] = None) -> str:
    """
    Transcribes audio with multilingual support (Kannada, Hindi, Tamil, Telugu, English, mixed)
    using Gemini multimodal STT first, with fallback to Google Speech Recognition.
    """
    gemini_model = None
    if orchestrator.use_gemini and orchestrator.api_key:
        try:
            gemini_model = orchestrator._create_gemini_model()
        except Exception:
            pass
    return voice_transcriber.transcribe(
        audio_bytes,
        gemini_model=gemini_model,
        preferred_lang=preferred_lang,
    )


@app.post("/audio_chat")
async def post_audio_chat(request: Request):
    """
    Accepts raw WAV audio data from the desktop microphone,
    transcribes it multilingually (Kannada, Hindi, Tamil, Telugu, English),
    strips any leading wake word, and routes it to orchestrator.chat().
    """
    audio_bytes = await request.body()
    if not audio_bytes or len(audio_bytes) < 400:
        return {"transcript": "", "message": "I didn't catch that — could you say it again?", "task": None}

    transcript = transcribe_audio_multilingual(audio_bytes)

    if not transcript:
        return {"transcript": "", "message": "I didn't catch that — could you say it again?", "task": None}

    cleaned_command = strip_wake_word(transcript)
    result = orchestrator.chat(cleaned_command, source="voice")
    result["transcript"] = transcript
    result["cleaned_command"] = cleaned_command
    return result


_tts_cache: dict[str, bytes] = {}

@app.get("/tts")
def get_tts(text: str, lang: str = "en", rate: float = 1.0):
    """
    Streams high-fidelity, native spoken audio (MP3) for Kannada (kn), Hindi (hi),
    Tamil (ta), Telugu (te), and English (en). Uses an in-memory LRU cache for responsiveness.
    """
    if not text or not text.strip():
        raise HTTPException(status_code=400, detail="Text is required")

    import re
    cleaned = re.sub(r"```[\s\S]*?```", "", text)
    cleaned = re.sub(r"`([^`]+)`", r"\1", cleaned)
    cleaned = re.sub(r"https?://\S+", "", cleaned)
    cleaned = re.sub(r"[*_#~>[\]]", "", cleaned)
    cleaned = re.sub(r"^\s*[-•*]\s+", "", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r"^\s*\d+\.\s+", "", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if not cleaned:
        cleaned = text.strip()

    lang_code = lang.lower().strip()
    if lang_code not in ("kn", "hi", "ta", "te", "en"):
        lang_code = "en"

    cache_key = f"{lang_code}:{cleaned}"
    if cache_key in _tts_cache:
        return Response(content=_tts_cache[cache_key], media_type="audio/mpeg")

    # Chunk text under 140 chars for Google Translate TTS
    words = cleaned.split()
    chunks = []
    current = []
    curr_len = 0
    for w in words:
        if curr_len + len(w) + 1 > 140:
            chunks.append(" ".join(current))
            current = [w]
            curr_len = len(w)
        else:
            current.append(w)
            curr_len += len(w) + 1
    if current:
        chunks.append(" ".join(current))

    audio_data = bytearray()
    for chunk in chunks[:6]:  # Limit to 6 chunks for snappy voice response
        try:
            q = urllib.parse.quote(chunk)
            url = f"https://translate.google.com/translate_tts?ie=UTF-8&q={q}&tl={lang_code}&client=tw-ob"
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                audio_data.extend(resp.read())
        except Exception as e:
            print(f"[cortex tts] Chunk error: {e}", file=sys.stderr)

    if not audio_data:
        raise HTTPException(status_code=502, detail="TTS generation failed")

    result_bytes = bytes(audio_data)
    if len(_tts_cache) < 200:
        _tts_cache[cache_key] = result_bytes

    return Response(content=result_bytes, media_type="audio/mpeg")

@app.post("/tasks/{task_id}/approve")
async def post_approve(task_id: str, req: ApproveRequest):
    try:
        task = orchestrator.tasks.get(task_id)
        if not task:
            raise HTTPException(status_code=404, detail=f"Task {task_id} not found.")
        if task.status != TaskStatus.WAITING_APPROVAL:
            raise HTTPException(status_code=400, detail="Cannot approve: task is not waiting for approval or has already been executed.")
        if req.approved and task.params.get("approval_hash"):
            if not req.approval_hash:
                raise HTTPException(status_code=400, detail="Missing approval hash: an explicit approval hash token is required.")
            if req.approval_hash != task.params.get("approval_hash"):
                raise HTTPException(status_code=400, detail="Approval hash mismatch.")

        res = orchestrator.approve(task_id, req.approved, approval_hash=req.approval_hash)
        if isinstance(res, dict) and res.get("error"):
            err_msg = str(res["error"]).lower()
            if any(k in err_msg for k in ("mismatch", "invalidated", "replay", "canceled", "cancelled", "cannot approve", "already", "approval", "not waiting")):
                raise HTTPException(status_code=400, detail=res["error"])
        return res
    except HTTPException:
        raise
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
    cc: Optional[List[str]] = None
    bcc: Optional[List[str]] = None

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
            cc=req.cc,
            bcc=req.bcc,
        )
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/email/accounts")
async def get_email_accounts():
    """List connected email accounts across Apple Mail and Gmail."""
    try:
        try:
            from backend.integrations.email.manager import MailProviderManager
        except ImportError:
            from providers.manager import MailProviderManager
        mgr = MailProviderManager(dry_run=False)
        accounts = mgr.list_accounts()
        return {"ok": True, "accounts": accounts}
    except Exception as e:
        return {"ok": False, "accounts": [], "error": str(e), "detail": "Email provider discovery failed"}

@app.get("/email/auth/url")
async def get_gmail_auth_url(redirect_uri: str = "http://127.0.0.1:8765/email/auth/callback"):
    """Get Google OAuth2 authorization URL for Gmail consent."""
    try:
        try:
            from backend.integrations.email.gmail_provider import GmailProvider
        except ImportError:
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
        try:
            from backend.integrations.email.gmail_provider import GmailProvider
        except ImportError:
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
        try:
            from backend.integrations.email.manager import MailProviderManager
        except ImportError:
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
