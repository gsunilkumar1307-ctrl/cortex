import { useState, useEffect, useRef, useCallback } from "react";
import { useExternalStoreRuntime } from "@assistant-ui/react";
import cortexApi from "./cortexApi";

function generateUUID() {
  if (typeof crypto !== "undefined" && crypto.randomUUID) {
    return crypto.randomUUID();
  }
  return "msg-" + Math.random().toString(36).substring(2, 9) + "-" + Date.now();
}

export function useCortexRuntime({ preferredLanguage = "auto", onTaskChange, onAudioPlay } = {}) {
  const [messages, setMessages] = useState([]);
  const [isRunning, setIsRunning] = useState(false);
  const [activeTask, setActiveTask] = useState(null);
  const [threadId, setThreadId] = useState(() => "thread-" + Date.now());
  const [threadTitle, setThreadTitle] = useState("New Conversation");
  const [threads, setThreads] = useState([]);
  const abortControllerRef = useRef(null);

  // Load existing threads on mount
  const refreshThreads = useCallback(async () => {
    try {
      const list = await cortexApi.listThreads();
      setThreads(list);
    } catch (err) {
      console.warn("[cortexRuntime] Could not load threads:", err);
    }
  }, []);

  useEffect(() => {
    refreshThreads();
  }, [refreshThreads]);

  // Sync active task to parent / HUD
  useEffect(() => {
    if (onTaskChange) onTaskChange(activeTask);
  }, [activeTask, onTaskChange]);

  // Persist current thread messages to Cortex encrypted database
  const persistThread = useCallback(async (currentMsgs, currentTitle = threadTitle, id = threadId) => {
    try {
      await cortexApi.saveThread({
        id,
        title: currentTitle,
        messages: currentMsgs,
        metadata: {
          lang: preferredLanguage,
          updatedAt: new Date().toISOString(),
        },
      });
      refreshThreads();
    } catch (err) {
      console.warn("[cortexRuntime] Thread persistence error:", err);
    }
  }, [threadTitle, threadId, preferredLanguage, refreshThreads]);

  // Cancel generation
  const onCancel = useCallback(async () => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
    }
    setIsRunning(false);

    if (activeTask && activeTask.id) {
      try {
        await cortexApi.cancelTask(activeTask.id);
      } catch (err) {
        console.warn("[cortexRuntime] Cancel task error:", err);
      }
    }
  }, [activeTask]);

  // Send a new user message and stream response from Cortex
  const executeQuery = useCallback(async (text, existingMessages = messages) => {
    if (!text || !text.trim()) return;
    const cleanText = text.trim();

    const userMessageId = generateUUID();
    const userMsg = {
      id: userMessageId,
      role: "user",
      content: [{ type: "text", text: cleanText }],
      createdAt: new Date(),
    };

    const assistantMessageId = generateUUID();
    const initialAssistantMsg = {
      id: assistantMessageId,
      role: "assistant",
      content: [{ type: "text", text: "" }],
      createdAt: new Date(),
      task: null,
    };

    const updatedMessages = [...existingMessages, userMsg, initialAssistantMsg];
    setMessages(updatedMessages);
    setIsRunning(true);

    const controller = new AbortController();
    abortControllerRef.current = controller;

    let accumulatedText = "";
    let finalTask = null;

    try {
      await cortexApi.chatStream(cleanText, {
        source: "text",
        preferredLanguage,
        threadId,
        signal: controller.signal,
        onStart: () => {},
        onDelta: (delta) => {
          accumulatedText += delta;
          setMessages((prev) =>
            prev.map((m) =>
              m.id === assistantMessageId
                ? {
                    ...m,
                    content: [{ type: "text", text: accumulatedText }],
                  }
                : m
            )
          );
        },
        onTaskUpdate: (task) => {
          finalTask = task;
          setActiveTask(task);
          setMessages((prev) =>
            prev.map((m) =>
              m.id === assistantMessageId
                ? {
                    ...m,
                    task,
                  }
                : m
            )
          );
        },
        onDone: (data) => {
          const finalMsgText = data.message || accumulatedText || "Completed.";
          finalTask = data.task || finalTask;
          setActiveTask(finalTask);

          const finalMessages = updatedMessages.map((m) =>
            m.id === assistantMessageId
              ? {
                  ...m,
                  content: [{ type: "text", text: finalMsgText }],
                  task: finalTask,
                }
              : m
          );

          setMessages(finalMessages);

          // Update title if first turn
          let newTitle = threadTitle;
          if (existingMessages.length === 0) {
            newTitle = cleanText.slice(0, 36);
            setThreadTitle(newTitle);
          }

          persistThread(finalMessages, newTitle, threadId);

          if (onAudioPlay && finalMsgText) {
            const lang = finalTask?.language || data.language || "en";
            onAudioPlay(finalMsgText, lang);
          }
        },
        onError: (err) => {
          const errText = `Execution error: ${err.message || "Failed to communicate with Cortex."}`;
          setMessages((prev) =>
            prev.map((m) =>
              m.id === assistantMessageId
                ? {
                    ...m,
                    content: [{ type: "text", text: errText }],
                    error: err.message,
                  }
                : m
            )
          );
        },
      });
    } catch (err) {
      if (err.name !== "AbortError") {
        setMessages((prev) =>
          prev.map((m) =>
            m.id === assistantMessageId
              ? {
                  ...m,
                  content: [{ type: "text", text: `Error: ${err.message}` }],
                }
              : m
          )
        );
      }
    } finally {
      setIsRunning(false);
      abortControllerRef.current = null;
    }
  }, [messages, preferredLanguage, threadId, threadTitle, persistThread, onAudioPlay]);

  // onNew handler for assistant-ui Composer
  const onNew = useCallback(async (appendMessage) => {
    let text = "";
    if (Array.isArray(appendMessage.content)) {
      for (const part of appendMessage.content) {
        if (part.type === "text" && part.text) text += part.text;
      }
    } else if (typeof appendMessage.content === "string") {
      text = appendMessage.content;
    }
    await executeQuery(text);
  }, [executeQuery]);

  // onEdit handler: truncate thread at edited point and re-run
  const onEdit = useCallback(async (editedMessage) => {
    const editIndex = messages.findIndex((m) => m.id === editedMessage.id);
    if (editIndex === -1) return;

    let text = "";
    if (Array.isArray(editedMessage.content)) {
      for (const part of editedMessage.content) {
        if (part.type === "text" && part.text) text += part.text;
      }
    } else if (typeof editedMessage.content === "string") {
      text = editedMessage.content;
    }

    const priorMessages = messages.slice(0, editIndex);
    await executeQuery(text, priorMessages);
  }, [messages, executeQuery]);

  // onReload handler: regenerate last assistant turn
  const onReload = useCallback(async () => {
    if (messages.length < 2) return;
    const lastUserIdx = messages.map(m => m.role).lastIndexOf("user");
    if (lastUserIdx === -1) return;

    const userMessage = messages[lastUserIdx];
    let text = "";
    for (const part of userMessage.content || []) {
      if (part.type === "text") text += part.text;
    }

    const priorMessages = messages.slice(0, lastUserIdx);
    await executeQuery(text, priorMessages);
  }, [messages, executeQuery]);

  // Switch to a new thread
  const startNewThread = useCallback(() => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
    }
    const newId = "thread-" + Date.now();
    setThreadId(newId);
    setThreadTitle("New Conversation");
    setMessages([]);
    setActiveTask(null);
    setIsRunning(false);
  }, []);

  // Switch to an existing thread
  const loadThread = useCallback(async (id) => {
    try {
      if (abortControllerRef.current) {
        abortControllerRef.current.abort();
      }
      setIsRunning(false);
      const threadData = await cortexApi.getThread(id);
      if (threadData) {
        setThreadId(id);
        setThreadTitle(threadData.title || "Conversation");
        setMessages(threadData.messages || []);
        setActiveTask(null);
      }
    } catch (err) {
      console.warn("[cortexRuntime] Failed to load thread:", err);
    }
  }, []);

  // Delete thread
  const deleteThread = useCallback(async (id) => {
    try {
      await cortexApi.deleteThread(id);
      if (id === threadId) {
        startNewThread();
      }
      refreshThreads();
    } catch (err) {
      console.warn("[cortexRuntime] Failed to delete thread:", err);
    }
  }, [threadId, startNewThread, refreshThreads]);

  // Rename thread
  const renameThread = useCallback(async (id, newTitle) => {
    try {
      await cortexApi.renameThread(id, newTitle);
      if (id === threadId) setThreadTitle(newTitle);
      refreshThreads();
    } catch (err) {
      console.warn("[cortexRuntime] Failed to rename thread:", err);
    }
  }, [threadId, refreshThreads]);

  // assistant-ui external store runtime bridge
  const runtime = useExternalStoreRuntime({
    messages,
    isRunning,
    onNew,
    onEdit,
    onReload,
    onCancel,
    setMessages,
  });

  return {
    runtime,
    messages,
    isRunning,
    activeTask,
    threadId,
    threadTitle,
    threads,
    onNew,
    onCancel,
    onReload,
    onEdit,
    startNewThread,
    loadThread,
    deleteThread,
    renameThread,
    refreshThreads,
    setActiveTask,
    setMessages,
  };
}
export default useCortexRuntime;

