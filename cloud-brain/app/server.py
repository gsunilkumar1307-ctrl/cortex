import os
import io
import sys
from pathlib import Path

# ── PATH must be set BEFORE importing speech_recognition ──────────────────────
# SpeechRecognition uses shutil.which("flac") at import time on some platforms.
# Prepend our native ARM64 flac wrapper so it is found before the broken x86 binary.
ROOT = Path(__file__).resolve().parents[2]
bin_path = str(ROOT / "cloud-brain" / "bin")
if bin_path not in os.environ.get("PATH", ""):
    os.environ["PATH"] = f"{bin_path}:{os.environ.get('PATH', '')}"

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn
import speech_recognition as sr

sys.path.insert(0, str(ROOT / "shared-sdk" / "python"))
sys.path.insert(0, str(ROOT / "automation-engine"))
sys.path.insert(0, str(ROOT / "memory-service"))
sys.path.insert(0, str(ROOT / "cloud-brain" / "app"))

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

def main() -> None:
    host = "127.0.0.1"
    port = 8765
    print(f"Cortex backend listening on http://{host}:{port}")
    uvicorn.run(app, host=host, port=port, log_level="info")

if __name__ == "__main__":
    main()
