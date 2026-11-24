from __future__ import annotations

import json
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from typing import Any, Dict, Optional, Tuple

DEFAULT_OLLAMA_ENDPOINT = "http://127.0.0.1:11434"
DEFAULT_OLLAMA_MODEL = "qwen3.5:9b"
DEFAULT_CONTEXT_WINDOW = 8192


class LocalAIStatus:
    STARTING = "Starting Local AI…"
    CONNECTING = "Connecting to Ollama…"
    LOADING_MODEL = "Loading model…"
    READY = "Local AI Ready"
    UNAVAILABLE = "Local AI Unavailable"


class OllamaLifecycleManager:
    """
    Automatic Ollama lifecycle management for Cortex.
    Detects running instance, launches Ollama on macOS without duplicate processes,
    waits for health with bounded retries, verifies configured model availability,
    and supports safe runtime recovery without restart loops.
    """

    def __init__(
        self,
        model_name: str = DEFAULT_OLLAMA_MODEL,
        base_url: str = DEFAULT_OLLAMA_ENDPOINT,
    ) -> None:
        self.model_name = os.getenv("OLLAMA_MODEL", model_name) or DEFAULT_OLLAMA_MODEL
        self.base_url = (os.getenv("OLLAMA_HOST", base_url) or DEFAULT_OLLAMA_ENDPOINT).rstrip("/")
        self._lock = threading.RLock()
        self._status = LocalAIStatus.CONNECTING
        self._ready = False
        self._error: Optional[str] = None
        self._spawned_process: Optional[subprocess.Popen] = None
        self._startup_thread: Optional[threading.Thread] = None
        self._last_recovery_time = 0.0
        self._min_recovery_interval = 30.0  # Safe recovery cooldown in seconds

    def is_service_running(self, timeout: float = 1.0) -> bool:
        """Checks whether the Ollama HTTP API responds at base_url."""
        try:
            req = urllib.request.Request(f"{self.base_url}/api/tags")
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.status == 200
        except Exception:
            return False

    @staticmethod
    def is_process_running() -> bool:
        """Checks whether an Ollama process is already running on the host system."""
        try:
            res = subprocess.run(["pgrep", "-x", "ollama"], capture_output=True, timeout=2.0)
            if res.returncode == 0:
                return True
        except Exception:
            pass

        try:
            # Fallback check using ps
            res = subprocess.run(["ps", "-A", "-o", "comm"], capture_output=True, text=True, timeout=2.0)
            if "ollama" in res.stdout.lower():
                return True
        except Exception:
            pass

        return False

    @staticmethod
    def find_ollama_binary() -> Optional[str]:
        """Locates the existing Ollama executable on macOS."""
        which_path = shutil.which("ollama")
        if which_path and os.path.isfile(which_path) and os.access(which_path, os.X_OK):
            return which_path

        candidates = [
            "/usr/local/bin/ollama",
            "/opt/homebrew/bin/ollama",
            "/Applications/Ollama.app/Contents/Resources/ollama",
        ]
        for path in candidates:
            if os.path.isfile(path) and os.access(path, os.X_OK):
                return path

        return None

    def verify_model_available(self, timeout: float = 2.0) -> Tuple[bool, str]:
        """
        Verifies that the configured model required by Cortex is installed locally.
        Does NOT download or pull models automatically without explicit user consent.
        """
        try:
            req = urllib.request.Request(f"{self.base_url}/api/tags")
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                models = [m.get("name") or m.get("model") for m in data.get("models", [])]
                target_base = self.model_name.split(":")[0]
                has_model = any(
                    m == self.model_name or (m and m.split(":")[0] == target_base)
                    for m in models
                )
                if not has_model:
                    return False, f"Model '{self.model_name}' not found locally. To download it, run: ollama pull {self.model_name}"
                return True, f"Model '{self.model_name}' verified."
        except urllib.error.URLError:
            return False, "Ollama service is unreachable."
        except Exception as e:
            return False, f"Model verification error: {e}"

    def ensure_ready(self, max_wait_seconds: float = 20.0) -> bool:
        """
        Executes the authoritative startup flow:
        1. Check whether Ollama service is already running.
        2. If running, connect to it without launching a duplicate process.
        3. If not running, start Ollama using existing installation on macOS.
        4. Wait for Ollama to become healthy, using bounded retries and timeouts.
        5. Verify configured model is available locally.
        6. Enable chat if ready, or display truthful status and actionable error.
        """
        with self._lock:
            # 1. Check if already healthy and model verified
            if self.is_service_running(timeout=1.0):
                self._status = LocalAIStatus.LOADING_MODEL
                self._error = None
                has_model, model_msg = self.verify_model_available(timeout=2.0)
                if has_model:
                    self._status = LocalAIStatus.READY
                    self._ready = True
                    self._error = None
                    return True
                else:
                    self._status = LocalAIStatus.UNAVAILABLE
                    self._ready = False
                    self._error = model_msg
                    return False

            # 2. Ollama is not responding. Check if process is already starting
            if not self.is_process_running():
                # Start Ollama using existing macOS installation
                self._status = LocalAIStatus.STARTING
                self._ready = False
                self._error = None

                ollama_bin = self.find_ollama_binary()
                if ollama_bin:
                    try:
                        self._spawned_process = subprocess.Popen(
                            [ollama_bin, "serve"],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                            start_new_session=True,
                        )
                    except Exception as e:
                        self._status = LocalAIStatus.UNAVAILABLE
                        self._ready = False
                        self._error = f"Failed to start Ollama executable: {e}"
                        return False
                elif os.path.exists("/Applications/Ollama.app"):
                    try:
                        subprocess.Popen(["open", "-a", "Ollama", "--background"])
                    except Exception as e:
                        self._status = LocalAIStatus.UNAVAILABLE
                        self._ready = False
                        self._error = f"Failed to launch Ollama app: {e}"
                        return False
                else:
                    self._status = LocalAIStatus.UNAVAILABLE
                    self._ready = False
                    self._error = "Ollama is not installed on this system. Please install Ollama from https://ollama.com."
                    return False
            else:
                self._status = LocalAIStatus.CONNECTING
                self._ready = False
                self._error = None

            # 3. Wait for Ollama to become healthy with bounded retries
            self._status = LocalAIStatus.CONNECTING
            deadline = time.time() + max_wait_seconds
            service_up = False
            while time.time() < deadline:
                if self.is_service_running(timeout=0.8):
                    service_up = True
                    break
                time.sleep(0.5)

            if not service_up:
                self._status = LocalAIStatus.UNAVAILABLE
                self._ready = False
                self._error = f"Ollama service did not become healthy within {int(max_wait_seconds)}s. Run 'ollama serve' in Terminal."
                return False

            # 4. Verify configured model
            self._status = LocalAIStatus.LOADING_MODEL
            has_model, model_msg = self.verify_model_available(timeout=3.0)
            if has_model:
                self._status = LocalAIStatus.READY
                self._ready = True
                self._error = None
                return True
            else:
                self._status = LocalAIStatus.UNAVAILABLE
                self._ready = False
                self._error = model_msg
                return False

    def start_background(self) -> None:
        """Starts the startup and health verification asynchronously without blocking UI/server startup."""
        with self._lock:
            if self._startup_thread and self._startup_thread.is_alive():
                return
            self._startup_thread = threading.Thread(
                target=self.ensure_ready,
                kwargs={"max_wait_seconds": 25.0},
                daemon=True,
                name="ollama-lifecycle-worker",
            )
            self._startup_thread.start()

    def handle_connection_failure(self, exc: Optional[Exception] = None) -> None:
        """Handles mid-session crash or connection drop safely with cooldown against restart loops."""
        now = time.time()
        with self._lock:
            self._ready = False
            self._status = LocalAIStatus.UNAVAILABLE
            self._error = f"Connection to Ollama was lost: {exc}" if exc else "Connection to Ollama was lost."

            if now - self._last_recovery_time >= self._min_recovery_interval:
                self._last_recovery_time = now
                self.start_background()

    def get_status(self) -> Dict[str, Any]:
        """Returns the truthful, current status of Local AI."""
        with self._lock:
            return {
                "status": self._status,
                "ready": self._ready,
                "model": self.model_name,
                "endpoint": self.base_url,
                "error": self._error,
            }

    def is_ready(self) -> bool:
        with self._lock:
            return self._ready


_GLOBAL_LIFECYCLE: Optional[OllamaLifecycleManager] = None
_GLOBAL_LIFECYCLE_LOCK = threading.Lock()


def get_ollama_lifecycle(
    model_name: str = DEFAULT_OLLAMA_MODEL,
    base_url: str = DEFAULT_OLLAMA_ENDPOINT,
) -> OllamaLifecycleManager:
    """Returns the shared Ollama lifecycle manager singleton."""
    global _GLOBAL_LIFECYCLE
    with _GLOBAL_LIFECYCLE_LOCK:
        if _GLOBAL_LIFECYCLE is None:
            _GLOBAL_LIFECYCLE = OllamaLifecycleManager(model_name=model_name, base_url=base_url)
        return _GLOBAL_LIFECYCLE


class OllamaUnavailableError(Exception):
    """Raised when the local Ollama service cannot be reached."""
    pass


class OllamaModelNotFoundError(Exception):
    """Raised when the requested model is not found in the local Ollama registry."""
    pass


class OllamaResponse:
    """Standardized response object matching the generate_content() contract."""

    def __init__(self, raw: dict[str, Any], text: str, tool_calls: Optional[list[dict[str, Any]]] = None) -> None:
        self.raw = raw
        self.text = text
        self.tool_calls = tool_calls or []

    def __str__(self) -> str:
        return self.text

    def __repr__(self) -> str:
        return f"OllamaResponse(text={self.text[:40]!r}...)"


def clean_thinking_output(text: str) -> str:
    """Suppresses internal reasoning/thinking tokens (<think>...</think>) from responses."""
    if not text:
        return ""
    cleaned = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    # Also strip stray unclosed <think> if response got cut off
    cleaned = re.sub(r"<think>.*$", "", cleaned, flags=re.DOTALL)
    return cleaned.strip()


class OllamaModel:
    """
    Lightweight, native client for local Ollama inference using qwen3.5:9b.
    Adheres directly to the existing generate_content() contract to maintain
    100% backward compatibility with existing Cortex agent components.
    """

    def __init__(
        self,
        model_name: str = DEFAULT_OLLAMA_MODEL,
        base_url: str = DEFAULT_OLLAMA_ENDPOINT,
        system_instruction: Optional[str] = None,
        num_ctx: int = DEFAULT_CONTEXT_WINDOW,
    ) -> None:
        self.model_name = os.getenv("OLLAMA_MODEL", model_name) or DEFAULT_OLLAMA_MODEL
        self.base_url = (os.getenv("OLLAMA_HOST", base_url) or DEFAULT_OLLAMA_ENDPOINT).rstrip("/")
        self.endpoint = self.base_url
        self.system_instruction = system_instruction
        self.num_ctx = int(os.getenv("OLLAMA_NUM_CTX", str(num_ctx)))
        self._available_cache: Optional[bool] = None

    def check_health(self, timeout: float = 2.0) -> tuple[bool, str]:
        """Verifies that Ollama is running and qwen3.5:9b is installed."""
        try:
            req = urllib.request.Request(f"{self.base_url}/api/tags", headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                models = [m.get("name") or m.get("model") for m in data.get("models", [])]
                # Match exact or with :latest / tag variant
                target_base = self.model_name.split(":")[0]
                has_model = any(
                    m == self.model_name or (m and m.split(":")[0] == target_base)
                    for m in models
                )
                if not has_model:
                    return False, f"The required local model '{self.model_name}' was not found in Ollama."
                return True, "Ollama service and model active."
        except urllib.error.URLError:
            return False, "Cortex's local AI engine is unavailable. Please start Ollama and try again."
        except Exception as e:
            return False, f"Ollama health check error: {e}"

    def generate_content(
        self,
        contents: Any,
        generation_config: Optional[dict[str, Any]] = None,
        request_options: Optional[dict[str, Any]] = None,
        tools: Optional[list[dict[str, Any]]] = None,
    ) -> OllamaResponse:
        """
        Executes local inference on Ollama matching the existing generate_content contract.
        """
    def _prepare_messages(self, contents: Any) -> list[dict[str, Any]]:
        messages: list[dict[str, Any]] = []

        if self.system_instruction:
            messages.append({"role": "system", "content": self.system_instruction})

        # Format input contents
        if isinstance(contents, str):
            messages.append({"role": "user", "content": contents})
        elif isinstance(contents, list):
            for item in contents:
                if isinstance(item, str):
                    messages.append({"role": "user", "content": item})
                elif isinstance(item, dict):
                    # Check for Gemini-style parts format
                    if "role" in item and "parts" in item:
                        role = "assistant" if item["role"] in ("model", "assistant") else "user"
                        text_parts: list[str] = []
                        images: list[str] = []
                        for p in item["parts"]:
                            if isinstance(p, str):
                                text_parts.append(p)
                            elif isinstance(p, dict):
                                if "mime_type" in p and "data" in p:
                                    images.append(p["data"])
                                elif "text" in p:
                                    text_parts.append(p["text"])
                        msg: dict[str, Any] = {"role": role, "content": " ".join(text_parts)}
                        if images:
                            msg["images"] = images
                        messages.append(msg)
                    elif "role" in item and "content" in item:
                        role = "assistant" if item["role"] in ("model", "assistant") else "user"
                        messages.append({"role": role, "content": item["content"]})
                    elif "mime_type" in item and "data" in item:
                        # Direct image part appended to last message or new user message
                        if messages and messages[-1].get("role") == "user":
                            messages[-1].setdefault("images", []).append(item["data"])
                        else:
                            messages.append({"role": "user", "content": "", "images": [item["data"]]})
        elif isinstance(contents, dict):
            messages.append(contents)

        return messages

    def generate_content(
        self,
        contents: Any,
        generation_config: Optional[dict[str, Any]] = None,
        request_options: Optional[dict[str, Any]] = None,
        tools: Optional[list[dict[str, Any]]] = None,
    ) -> OllamaResponse:
        """
        Executes local inference on Ollama matching the existing generate_content contract.
        """
        messages = self._prepare_messages(contents)

        # Merge generation config
        gen_cfg = generation_config or {}
        req_opts = request_options or {}
        timeout_val = float(req_opts.get("timeout", float(os.getenv("OLLAMA_TIMEOUT", "60.0"))))
        timeout = max(timeout_val, 45.0)

        options: dict[str, Any] = {
            "num_ctx": self.num_ctx,
        }
        if "temperature" in gen_cfg:
            options["temperature"] = float(gen_cfg["temperature"])
        else:
            options["temperature"] = 0.2

        payload: dict[str, Any] = {
            "model": self.model_name,
            "messages": messages,
            "stream": False,
            "think": False,  # Native Ollama suppression of internal reasoning
            "keep_alive": "1h",  # Pin model in unified memory to prevent repeated cold loads
            "options": options,
        }

        if gen_cfg.get("response_mime_type") == "application/json" or gen_cfg.get("format") == "json":
            payload["format"] = "json"

        if tools:
            payload["tools"] = tools

        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}/api/chat",
            data=body,
            headers={"Content-Type": "application/json"},
        )

        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as http_err:
            if http_err.code == 404:
                raise OllamaModelNotFoundError(
                    f"The required local model '{self.model_name}' was not found in Ollama. "
                    f"Please ensure '{self.model_name}' is installed and try again."
                ) from http_err
            err_body = ""
            try:
                err_body = http_err.read().decode("utf-8")
            except Exception:
                pass
            raise RuntimeError(f"Ollama inference HTTP {http_err.code}: {err_body}") from http_err
        except urllib.error.URLError as url_err:
            reason = getattr(url_err, "reason", None)
            if isinstance(reason, socket.timeout) or "timed out" in str(reason).lower():
                raise TimeoutError("Local Ollama inference timed out while generating response.") from url_err
            raise OllamaUnavailableError(
                "Cortex's local AI engine is unavailable. Please start Ollama and try again."
            ) from url_err
        except Exception as exc:
            raise RuntimeError(f"Ollama inference error: {exc}") from exc

        msg_obj = data.get("message", {})
        raw_text = msg_obj.get("content", "")
        clean_text = clean_thinking_output(raw_text)
        tool_calls = msg_obj.get("tool_calls", [])

        return OllamaResponse(raw=data, text=clean_text, tool_calls=tool_calls)

    def generate_content_stream(
        self,
        contents: Any,
        generation_config: Optional[dict[str, Any]] = None,
        request_options: Optional[dict[str, Any]] = None,
    ):
        """
        Streams response tokens progressively from local Ollama using the native streaming API.
        Yields individual text token strings as they arrive.
        """
        messages = self._prepare_messages(contents)
        gen_cfg = generation_config or {}
        req_opts = request_options or {}
        timeout_val = float(req_opts.get("timeout", float(os.getenv("OLLAMA_TIMEOUT", "60.0"))))
        timeout = max(timeout_val, 45.0)

        options: dict[str, Any] = {
            "num_ctx": self.num_ctx,
        }
        if "temperature" in gen_cfg:
            options["temperature"] = float(gen_cfg["temperature"])
        else:
            options["temperature"] = 0.2

        payload: dict[str, Any] = {
            "model": self.model_name,
            "messages": messages,
            "stream": True,
            "think": False,
            "keep_alive": "1h",
            "options": options,
        }

        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}/api/chat",
            data=body,
            headers={"Content-Type": "application/json"},
        )

        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                in_think_block = False
                while True:
                    raw_line = resp.readline()
                    if not raw_line:
                        break
                    try:
                        chunk = json.loads(raw_line.decode("utf-8"))
                        if chunk.get("done"):
                            break
                        content = chunk.get("message", {}).get("content", "")
                        if not content:
                            continue

                        # Filter any leaked thinking tags
                        if "<think>" in content:
                            in_think_block = True
                            content = content.split("<think>")[0]
                        if "</think>" in content:
                            in_think_block = False
                            content = content.split("</think>")[-1]

                        if not in_think_block and content:
                            yield content
                    except Exception:
                        continue
        except urllib.error.URLError as url_err:
            reason = getattr(url_err, "reason", None)
            if isinstance(reason, socket.timeout) or "timed out" in str(reason).lower():
                raise TimeoutError("Local Ollama streaming inference timed out.") from url_err
            raise OllamaUnavailableError(
                "Cortex's local AI engine is unavailable. Please start Ollama and try again."
            ) from url_err
        except Exception as exc:
            raise RuntimeError(f"Ollama streaming inference error: {exc}") from exc
