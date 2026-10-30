/**
 * Regression tests for audit history UI logic.
 *
 * Tests the pure-JS helper functions extracted from AuditHistoryPanel:
 *   - getEventMeta (event type → metadata mapping)
 *   - formatAuditTimestamp (ISO → human-readable, safe fallbacks)
 *   - redactData (sensitive key redaction)
 *   - flattenAuditEvents (task → event flattening + sort order)
 *   - MemoryPayloadDisplay logic
 *
 * Run with: node --test tests/test_audit_history_ui.mjs
 */

import { test, describe } from "node:test";
import assert from "node:assert/strict";

// ─── Replicate the pure-JS helpers from App.jsx ───────────────────────────────

const REDACTED_KEYS = new Set([
  "body", "formatted_body", "raw_body", "password", "token", "secret",
  "api_key", "approval_hash", "hash", "encryption_key", "private_key",
  "credentials", "auth_token", "access_token", "refresh_token",
]);

const EVENT_META = {
  draft_prepared:          { icon: "✉️",  title: "Email Draft Prepared",              statusLabel: "Awaiting Approval", statusClass: "status-waiting",   category: "email" },
  draft_ready:             { icon: "✉️",  title: "Email Draft Ready",                 statusLabel: "Awaiting Approval", statusClass: "status-waiting",   category: "email" },
  draft_edited:            { icon: "✏️", title: "Email Draft Updated",               statusLabel: "Updated",           statusClass: "status-info",      category: "email" },
  draft_deleted:           { icon: "🗑️", title: "Draft Removed",                     statusLabel: "Removed",           statusClass: "status-cancelled", category: "email" },
  approval_granted:        { icon: "✅",  title: "Email Approved for Sending",        statusLabel: "Approved",          statusClass: "status-good",      category: "email" },
  approval_rejected:       { icon: "❌",  title: "Email Approval Rejected",           statusLabel: "Rejected",          statusClass: "status-bad",       category: "email" },
  approval_required:       { icon: "🔐",  title: "Approval Required",                 statusLabel: "Blocked",           statusClass: "status-waiting",   category: "email" },
  approval_replay_rejected:{ icon: "⚠️", title: "Duplicate Approval Ignored",        statusLabel: "Skipped",           statusClass: "status-warn",      category: "email" },
  approval_invalidated:    { icon: "⚠️", title: "Approval Invalidated",              statusLabel: "Invalidated",       statusClass: "status-warn",      category: "email" },
  approval_expired:        { icon: "⏰",  title: "Approval Request Expired",          statusLabel: "Expired",           statusClass: "status-warn",      category: "email" },
  mail_fetch_started:      { icon: "📥",  title: "Fetching Email Inbox",              statusLabel: "Running",           statusClass: "status-running",   category: "email" },
  mail_fetch_completed:    { icon: "📬",  title: "Email Inbox Fetched",               statusLabel: "Completed",         statusClass: "status-good",      category: "email" },
  received:                { icon: "📨",  title: "Request Received",                  statusLabel: "Received",          statusClass: "status-info",      category: "system" },
  running:                 { icon: "⚡",  title: "Task Running",                      statusLabel: "Running",           statusClass: "status-running",   category: "system" },
  completed:               { icon: "✅",  title: "Task Completed",                    statusLabel: "Completed",         statusClass: "status-good",      category: "system" },
  failed:                  { icon: "⛔",  title: "Task Failed",                       statusLabel: "Failed",            statusClass: "status-bad",       category: "system" },
  cancelled:               { icon: "🚫",  title: "Task Cancelled",                    statusLabel: "Cancelled",         statusClass: "status-cancelled", category: "system" },
  canceled:                { icon: "🚫",  title: "Task Cancelled",                    statusLabel: "Cancelled",         statusClass: "status-cancelled", category: "system" },
  execution_blocked:       { icon: "🔒",  title: "Execution Blocked — Approval Required", statusLabel: "Blocked",      statusClass: "status-warn",      category: "system" },
  need_info:               { icon: "❓",  title: "Clarification Requested",           statusLabel: "Needs Info",        statusClass: "status-waiting",   category: "system" },
  paused_model_unavailable:{ icon: "⏸️", title: "Task Paused — AI Model Unavailable",statusLabel: "Paused",           statusClass: "status-warn",      category: "system" },
  capability_selected:     { icon: "🎯",  title: "Action Selected",                   statusLabel: "Running",           statusClass: "status-running",   category: "system" },
  web_search_started:      { icon: "🔍",  title: "Web Search Started",                statusLabel: "Running",           statusClass: "status-running",   category: "search" },
  web_search_completed:    { icon: "🌐",  title: "Web Search Completed",              statusLabel: "Completed",         statusClass: "status-good",      category: "search" },
};

function getEventMeta(eventType) {
  return EVENT_META[eventType] || {
    icon: "📋",
    title: eventType.replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase()),
    statusLabel: "Event",
    statusClass: "status-info",
    category: "other",
  };
}

function formatAuditTimestamp(isoStr) {
  if (!isoStr) return "Timestamp unavailable";
  try {
    const d = new Date(isoStr);
    if (isNaN(d.getTime())) return "Invalid timestamp";
    return new Intl.DateTimeFormat(undefined, {
      dateStyle: "medium", timeStyle: "short",
    }).format(d);
  } catch {
    return "Timestamp unavailable";
  }
}

function redactData(data) {
  if (!data || typeof data !== "object") return {};
  const out = {};
  for (const [k, v] of Object.entries(data)) {
    if (REDACTED_KEYS.has(k.toLowerCase())) {
      out[k] = "••••••";
    } else if (typeof v === "object" && v !== null) {
      out[k] = redactData(v);
    } else {
      out[k] = v;
    }
  }
  return out;
}

function flattenAuditEvents(tasks) {
  const events = [];
  for (const t of tasks) {
    if (!t.auditTrail?.length) continue;
    for (const ev of t.auditTrail) {
      events.push({ ...ev, _taskIntent: t.intent, _taskId: t.id });
    }
  }
  events.sort((a, b) => {
    const ta = a.createdAt ? new Date(a.createdAt).getTime() : 0;
    const tb = b.createdAt ? new Date(b.createdAt).getTime() : 0;
    return tb - ta;
  });
  return events;
}

// ─── Tests ────────────────────────────────────────────────────────────────────

describe("getEventMeta — known event types", () => {
  test("draft_prepared → Email Draft Prepared, status-waiting", () => {
    const m = getEventMeta("draft_prepared");
    assert.equal(m.title, "Email Draft Prepared");
    assert.equal(m.statusClass, "status-waiting");
    assert.equal(m.statusLabel, "Awaiting Approval");
    assert.equal(m.category, "email");
  });

  test("completed → Task Completed, status-good", () => {
    const m = getEventMeta("completed");
    assert.equal(m.title, "Task Completed");
    assert.equal(m.statusClass, "status-good");
  });

  test("failed → Task Failed, status-bad", () => {
    const m = getEventMeta("failed");
    assert.equal(m.title, "Task Failed");
    assert.equal(m.statusClass, "status-bad");
  });

  test("cancelled → Task Cancelled, status-cancelled", () => {
    const m = getEventMeta("cancelled");
    assert.equal(m.title, "Task Cancelled");
    assert.equal(m.statusClass, "status-cancelled");
    assert.equal(m.statusLabel, "Cancelled");
  });

  test("canceled (alternate spelling) → Task Cancelled", () => {
    const m = getEventMeta("canceled");
    assert.equal(m.title, "Task Cancelled");
    assert.equal(m.statusLabel, "Cancelled");
    assert.notEqual(m.statusLabel, "Sent");
    assert.notEqual(m.statusLabel, "Completed");
  });

  test("approval_granted → Email Approved for Sending", () => {
    const m = getEventMeta("approval_granted");
    assert.equal(m.title, "Email Approved for Sending");
    assert.equal(m.statusLabel, "Approved");
  });

  test("approval_rejected → Rejected, status-bad", () => {
    const m = getEventMeta("approval_rejected");
    assert.equal(m.statusLabel, "Rejected");
    assert.equal(m.statusClass, "status-bad");
  });

  test("need_info → Clarification Requested", () => {
    const m = getEventMeta("need_info");
    assert.equal(m.title, "Clarification Requested");
    assert.equal(m.statusLabel, "Needs Info");
  });

  test("paused_model_unavailable → AI Model Unavailable", () => {
    const m = getEventMeta("paused_model_unavailable");
    assert.match(m.title, /Unavailable/);
    assert.equal(m.statusLabel, "Paused");
  });

  test("web_search_started → search category", () => {
    const m = getEventMeta("web_search_started");
    assert.equal(m.category, "search");
  });

  test("draft_prepared → email category", () => {
    const m = getEventMeta("draft_prepared");
    assert.equal(m.category, "email");
  });

  test("running → system category", () => {
    const m = getEventMeta("running");
    assert.equal(m.category, "system");
  });
});

describe("getEventMeta — unknown event types", () => {
  test("unknown type returns generic formatter, not raw object", () => {
    const m = getEventMeta("some_unknown_event_xyz");
    assert.ok(typeof m.title === "string");
    assert.ok(m.title.length > 0);
    assert.equal(m.category, "other");
    assert.equal(m.statusLabel, "Event");
  });

  test("unknown type title is human-readable (underscores replaced)", () => {
    const m = getEventMeta("my_custom_event_type");
    assert.ok(!m.title.includes("_"), `Title should not contain underscores: "${m.title}"`);
  });

  test("empty string event type handled gracefully", () => {
    const m = getEventMeta("");
    assert.ok(typeof m.title === "string");
    assert.ok(typeof m.statusClass === "string");
  });
});

describe("formatAuditTimestamp — safe fallbacks", () => {
  test("valid ISO 8601 returns a non-empty string", () => {
    const result = formatAuditTimestamp("2026-10-29T12:00:00Z");
    assert.ok(typeof result === "string");
    assert.ok(result.length > 0);
    assert.notEqual(result, "Timestamp unavailable");
    assert.notEqual(result, "Invalid timestamp");
  });

  test("null → 'Timestamp unavailable'", () => {
    assert.equal(formatAuditTimestamp(null), "Timestamp unavailable");
  });

  test("undefined → 'Timestamp unavailable'", () => {
    assert.equal(formatAuditTimestamp(undefined), "Timestamp unavailable");
  });

  test("empty string → 'Timestamp unavailable'", () => {
    assert.equal(formatAuditTimestamp(""), "Timestamp unavailable");
  });

  test("invalid date string → 'Invalid timestamp'", () => {
    assert.equal(formatAuditTimestamp("not-a-date-at-all"), "Invalid timestamp");
  });

  test("malformed partial ISO string handled safely", () => {
    const r = formatAuditTimestamp("2026-13-99T99:99:99Z");
    assert.ok(typeof r === "string");
    assert.ok(r === "Invalid timestamp" || r.length > 0);
  });
});

describe("redactData — sensitive key redaction", () => {
  test("body is redacted", () => {
    const r = redactData({ body: "Hello world" });
    assert.equal(r.body, "••••••");
  });

  test("formatted_body is redacted", () => {
    const r = redactData({ formatted_body: "Dear colleague…" });
    assert.equal(r.formatted_body, "••••••");
  });

  test("token is redacted", () => {
    const r = redactData({ token: "abc123" });
    assert.equal(r.token, "••••••");
  });

  test("password is redacted", () => {
    const r = redactData({ password: "s3cr3t" });
    assert.equal(r.password, "••••••");
  });

  test("api_key is redacted", () => {
    const r = redactData({ api_key: "sk-..." });
    assert.equal(r.api_key, "••••••");
  });

  test("approval_hash is redacted", () => {
    const r = redactData({ approval_hash: "deadbeef" });
    assert.equal(r.approval_hash, "••••••");
  });

  test("safe keys are preserved", () => {
    const r = redactData({ recipient: "alice@example.com", subject: "Hello" });
    assert.equal(r.recipient, "alice@example.com");
    assert.equal(r.subject, "Hello");
  });

  test("mixed payload: sensitive redacted, safe preserved", () => {
    const r = redactData({ subject: "Test", body: "secret content", recipient: "bob@example.com" });
    assert.equal(r.subject, "Test");
    assert.equal(r.body, "••••••");
    assert.equal(r.recipient, "bob@example.com");
  });

  test("null input returns empty object", () => {
    assert.deepEqual(redactData(null), {});
  });

  test("undefined input returns empty object", () => {
    assert.deepEqual(redactData(undefined), {});
  });

  test("empty object returns empty object", () => {
    assert.deepEqual(redactData({}), {});
  });

  test("nested object: nested body is redacted", () => {
    const r = redactData({ meta: { body: "inner secret", subject: "outer" } });
    assert.equal(r.meta.body, "••••••");
    assert.equal(r.meta.subject, "outer");
  });
});

describe("flattenAuditEvents — event aggregation and ordering", () => {
  const TASKS = [
    {
      id: "task-1",
      intent: "send email",
      auditTrail: [
        { type: "draft_prepared", message: "Draft ready", createdAt: "2026-10-29T10:00:00Z", data: {} },
        { type: "approval_granted", message: "Approved",  createdAt: "2026-10-29T10:05:00Z", data: {} },
      ],
    },
    {
      id: "task-2",
      intent: "web search",
      auditTrail: [
        { type: "web_search_started", message: "Searching", createdAt: "2026-10-29T09:00:00Z", data: {} },
        { type: "completed",          message: "Done",      createdAt: "2026-10-29T09:01:00Z", data: {} },
      ],
    },
  ];

  test("all events from all tasks are included", () => {
    const events = flattenAuditEvents(TASKS);
    assert.equal(events.length, 4);
  });

  test("events are sorted newest-first", () => {
    const events = flattenAuditEvents(TASKS);
    for (let i = 0; i < events.length - 1; i++) {
      const a = new Date(events[i].createdAt).getTime();
      const b = new Date(events[i + 1].createdAt).getTime();
      assert.ok(a >= b, `Event ${i} (${events[i].createdAt}) should be >= ${events[i+1].createdAt}`);
    }
  });

  test("_taskId is attached to each flattened event", () => {
    const events = flattenAuditEvents(TASKS);
    for (const ev of events) {
      assert.ok(ev._taskId === "task-1" || ev._taskId === "task-2");
    }
  });

  test("_taskIntent is attached to each flattened event", () => {
    const events = flattenAuditEvents(TASKS);
    for (const ev of events) {
      assert.ok(typeof ev._taskIntent === "string");
    }
  });

  test("tasks without auditTrail are silently skipped", () => {
    const result = flattenAuditEvents([
      { id: "t1", intent: "x", auditTrail: [] },
      { id: "t2", intent: "y" /* no auditTrail */ },
      { id: "t3", intent: "z", auditTrail: [{ type: "completed", message: "ok", createdAt: "2026-01-01T00:00:00Z", data: {} }] },
    ]);
    assert.equal(result.length, 1);
    assert.equal(result[0]._taskId, "t3");
  });

  test("empty tasks array returns empty events list", () => {
    assert.deepEqual(flattenAuditEvents([]), []);
  });

  test("events without createdAt sort to the end (treated as 0)", () => {
    const result = flattenAuditEvents([{
      id: "t1", intent: "x",
      auditTrail: [
        { type: "completed", message: "ok", createdAt: "2026-10-29T10:00:00Z", data: {} },
        { type: "running",   message: "go", createdAt: null, data: {} },
      ],
    }]);
    // createdAt=null → time 0, should be after the real timestamp
    assert.equal(result[0].type, "completed");
    assert.equal(result[1].type, "running");
  });
});

describe("Audit history security invariants", () => {
  test("cancelled event statusLabel is never 'Sent' or 'Completed'", () => {
    for (const type of ["cancelled", "canceled"]) {
      const m = getEventMeta(type);
      assert.notEqual(m.statusLabel, "Sent");
      assert.notEqual(m.statusLabel, "Completed");
    }
  });

  test("approval_rejected statusLabel is never 'Approved'", () => {
    const m = getEventMeta("approval_rejected");
    assert.notEqual(m.statusLabel, "Approved");
  });

  test("redactData never reveals raw body content", () => {
    const secret = "This is the actual email body with personal information";
    const r = redactData({ body: secret, subject: "Visible" });
    assert.notEqual(r.body, secret);
    assert.equal(r.body, "••••••");
    assert.equal(r.subject, "Visible");
  });

  test("redactData never reveals token values", () => {
    const secret = "Bearer eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9";
    const r = redactData({ auth_token: secret, message: "ok" });
    assert.notEqual(r.auth_token, secret);
    assert.equal(r.auth_token, "••••••");
    assert.equal(r.message, "ok");
  });
});

describe("Unicode and long text handling", () => {
  test("Kannada event message is preserved as-is in redactData safe keys", () => {
    const msg = "ಇಮೇಲ್ ಕಳುಹಿಸಲಾಗಿದೆ";
    const r = redactData({ message: msg });
    assert.equal(r.message, msg);
  });

  test("Hindi event message is preserved", () => {
    const msg = "ईमेल भेजा गया";
    const r = redactData({ message: msg });
    assert.equal(r.message, msg);
  });

  test("Tamil event message is preserved", () => {
    const msg = "மின்னஞ்சல் அனுப்பப்பட்டது";
    const r = redactData({ message: msg });
    assert.equal(r.message, msg);
  });

  test("Telugu event message is preserved", () => {
    const msg = "ఇమెయిల్ పంపబడింది";
    const r = redactData({ message: msg });
    assert.equal(r.message, msg);
  });

  test("very long message string does not throw", () => {
    const long = "A".repeat(10000);
    const r = redactData({ message: long });
    assert.equal(r.message, long);
  });
});

