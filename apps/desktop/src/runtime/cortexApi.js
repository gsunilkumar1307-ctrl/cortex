/**
 * Cortex Typed API Client
 * Connects the assistant-ui frontend to Cortex FastAPI backend (http://127.0.0.1:8765)
 * Protected by X-Cortex-Session header injection in Electron.
 */

const API_BASE = "http://127.0.0.1:8765";

class CortexApiClient {
  constructor(baseUrl = API_BASE) {
    this.baseUrl = baseUrl;
  }

  getHeaders(customHeaders = {}) {
    return {
      "Content-Type": "application/json",
      ...customHeaders,
    };
  }

  async fetchHealth() {
    try {
      const res = await fetch(`${this.baseUrl}/health`);
      return await res.json();
    } catch (err) {
      return { ok: false, error: err.message };
    }
  }

  /**
   * Single-shot chat request
   */
  async chat(message, { source = "text", preferredLanguage = "auto" } = {}) {
    const res = await fetch(`${this.baseUrl}/chat`, {
      method: "POST",
      headers: this.getHeaders(),
      body: JSON.stringify({
        message,
        source,
        preferred_language: preferredLanguage === "auto" ? null : preferredLanguage,
      }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(err.detail || "Failed to communicate with Cortex");
    }
    return await res.json();
  }

  /**
   * Real-time Server-Sent Events (SSE) streaming chat request
   */
  async chatStream(message, {
    source = "text",
    preferredLanguage = "auto",
    threadId = null,
    onStart,
    onDelta,
    onTaskUpdate,
    onDone,
    onError,
    signal,
  } = {}) {
    try {
      const res = await fetch(`${this.baseUrl}/chat/stream`, {
        method: "POST",
        headers: this.getHeaders({ Accept: "text/event-stream" }),
        body: JSON.stringify({
          message,
          source,
          preferred_language: preferredLanguage === "auto" ? null : preferredLanguage,
          thread_id: threadId,
        }),
        signal,
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(err.detail || "Streaming connection failed");
      }

      const reader = res.body.getReader();
      const decoder = new TextDecoder("utf-8");
      let buffer = "";

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const events = buffer.split("\n\n");
        buffer = events.pop() || "";

        for (const rawEvent of events) {
          if (!rawEvent.trim()) continue;
          let eventType = "message";
          let dataStr = "";

          const lines = rawEvent.split("\n");
          for (const line of lines) {
            if (line.startsWith("event:")) {
              eventType = line.slice(6).trim();
            } else if (line.startsWith("data:")) {
              dataStr += line.slice(5).trim();
            }
          }

          if (!dataStr) continue;

          try {
            const data = JSON.parse(dataStr);
            if (eventType === "start" && onStart) {
              onStart(data);
            } else if (eventType === "text_delta" && onDelta) {
              onDelta(data.delta, data.index);
            } else if (eventType === "task_update" && onTaskUpdate) {
              onTaskUpdate(data.task);
            } else if (eventType === "done" && onDone) {
              onDone(data);
            } else if (eventType === "error" && onError) {
              onError(new Error(data.error || "Streaming error"));
            }
          } catch (parseErr) {
            console.warn("[cortexApi] SSE parse warning:", parseErr, dataStr);
          }
        }
      }
    } catch (err) {
      if (err.name === "AbortError") {
        if (onDone) onDone({ message: "", task: null, aborted: true });
      } else {
        if (onError) onError(err);
        else throw err;
      }
    }
  }

  /**
   * Approve or deny a staged task action (e.g. sending email)
   */
  async approveTask(taskId, approved, approvalHash) {
    const res = await fetch(`${this.baseUrl}/tasks/${encodeURIComponent(taskId)}/approve`, {
      method: "POST",
      headers: this.getHeaders(),
      body: JSON.stringify({
        approved: Boolean(approved),
        approval_hash: approvalHash || null,
      }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      throw new Error(data.detail || data.error || "Action approval failed");
    }
    return data;
  }

  /**
   * Cancel an active or pending task
   */
  async cancelTask(taskId) {
    const res = await fetch(`${this.baseUrl}/tasks/${encodeURIComponent(taskId)}/cancel`, {
      method: "POST",
      headers: this.getHeaders(),
    });
    return await res.json();
  }

  /**
   * Edit a pending Apple Mail draft
   */
  async editDraft(taskId, draftData) {
    const res = await fetch(`${this.baseUrl}/tasks/${encodeURIComponent(taskId)}/edit`, {
      method: "POST",
      headers: this.getHeaders(),
      body: JSON.stringify(draftData),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || "Failed to update draft");
    }
    return await res.json();
  }

  /**
   * Thread persistence: list all conversation threads
   */
  async listThreads() {
    const res = await fetch(`${this.baseUrl}/threads`, {
      headers: this.getHeaders(),
    });
    if (!res.ok) throw new Error("Failed to load threads");
    const data = await res.json();
    return data.threads || [];
  }

  /**
   * Save or update full thread history
   */
  async saveThread(thread) {
    const res = await fetch(`${this.baseUrl}/threads`, {
      method: "POST",
      headers: this.getHeaders(),
      body: JSON.stringify(thread),
    });
    if (!res.ok) throw new Error("Failed to persist thread");
    return await res.json();
  }

  /**
   * Retrieve a thread by id
   */
  async getThread(threadId) {
    const res = await fetch(`${this.baseUrl}/threads/${encodeURIComponent(threadId)}`, {
      headers: this.getHeaders(),
    });
    if (!res.ok) throw new Error(`Thread not found: ${threadId}`);
    const data = await res.json();
    return data.thread;
  }

  /**
   * Delete a thread
   */
  async deleteThread(threadId) {
    const res = await fetch(`${this.baseUrl}/threads/${encodeURIComponent(threadId)}`, {
      method: "DELETE",
      headers: this.getHeaders(),
    });
    return await res.json();
  }

  /**
   * Rename a thread
   */
  async renameThread(threadId, title) {
    const res = await fetch(`${this.baseUrl}/threads/${encodeURIComponent(threadId)}`, {
      method: "PATCH",
      headers: this.getHeaders(),
      body: JSON.stringify({ title }),
    });
    return await res.json();
  }

  /**
   * Fetch recent tasks & audit trails
   */
  async listTasks(limit = 100) {
    const res = await fetch(`${this.baseUrl}/tasks?limit=${limit}`, {
      headers: this.getHeaders(),
    });
    if (!res.ok) return { tasks: [] };
    return await res.json();
  }

  /**
   * Fetch memory items
   */
  async listMemories() {
    const res = await fetch(`${this.baseUrl}/memory`, {
      headers: this.getHeaders(),
    });
    if (!res.ok) return { items: [] };
    return await res.json();
  }

  /**
   * Delete a specific memory item
   */
  async deleteMemory(memoryId) {
    const res = await fetch(`${this.baseUrl}/memory/${encodeURIComponent(memoryId)}`, {
      method: "DELETE",
      headers: this.getHeaders(),
    });
    return await res.json();
  }

  /**
   * Clear memories by kind
   */
  async clearMemories(kind = null) {
    const url = kind ? `${this.baseUrl}/memory?kind=${encodeURIComponent(kind)}` : `${this.baseUrl}/memory`;
    const res = await fetch(url, {
      method: "DELETE",
      headers: this.getHeaders(),
    });
    return await res.json();
  }

  /**
   * Audio chat with raw WAV
   */
  async audioChat(wavBlob) {
    const res = await fetch(`${this.baseUrl}/audio_chat`, {
      method: "POST",
      headers: { "Content-Type": "audio/wav" },
      body: wavBlob,
    });
    return await res.json();
  }

  /**
   * Get TTS MP3 URL
   */
  getTtsUrl(text, lang = "en", rate = 1.0) {
    const q = encodeURIComponent(text);
    const l = encodeURIComponent(lang);
    return `${this.baseUrl}/tts?text=${q}&lang=${l}&rate=${rate}`;
  }
}

export const cortexApi = new CortexApiClient();
export default cortexApi;

