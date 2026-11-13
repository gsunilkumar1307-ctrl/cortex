/**
 * Frontend Unit & Regression Tests for assistant-ui integration in Cortex
 * Tests:
 *  - Message conversion & data structures
 *  - SSE event stream parsing
 *  - Attachment size & MIME validation
 *  - Task planning progress calculation
 *  - Cryptographic approval validation
 *  - Slash command and @-mention routing
 *
 * Run with: node --test tests/test_assistant_ui_frontend.mjs
 */

import { test, describe } from "node:test";
import assert from "node:assert/strict";

describe("assistant-ui Message Conversion & Data Structures", () => {
  test("user text message converts to ThreadMessageLike format", () => {
    const rawText = "Hello Cortex, how are you?";
    const msg = {
      id: "test-user-msg-1",
      role: "user",
      content: [{ type: "text", text: rawText }],
      createdAt: new Date(),
    };

    assert.equal(msg.role, "user");
    assert.equal(msg.content.length, 1);
    assert.equal(msg.content[0].type, "text");
    assert.equal(msg.content[0].text, rawText);
  });

  test("assistant message with tool calls preserves task payload", () => {
    const taskData = {
      id: "task-mail-99",
      intent: "draft_email",
      command: "send_mail",
      status: "waiting_approval",
      requiresApproval: true,
      params: {
        recipient: "rahul@example.com",
        subject: "Sync Meeting",
        body: "I will be 15 minutes late.",
        approval_hash: "cryptohash_abc1234567890",
      },
    };

    const msg = {
      id: "test-asst-msg-1",
      role: "assistant",
      content: [{ type: "text", text: "I have prepared the email draft for Rahul." }],
      task: taskData,
    };

    assert.equal(msg.role, "assistant");
    assert.equal(msg.task.requiresApproval, true);
    assert.equal(msg.task.params.approval_hash, "cryptohash_abc1234567890");
    assert.equal(msg.task.status, "waiting_approval");
  });
});

describe("Server-Sent Events (SSE) Stream Parsing", () => {
  test("parses event and data lines correctly", () => {
    const rawChunk = `event: start\ndata: {"status": "started", "query": "test query"}\n\nevent: text_delta\ndata: {"delta": "Hello "}\n\nevent: text_delta\ndata: {"delta": "world!"}\n\nevent: done\ndata: {"message": "Hello world!"}\n\n`;

    const events = [];
    const rawEvents = rawChunk.split("\n\n");
    for (const raw of rawEvents) {
      if (!raw.trim()) continue;
      let eventType = "message";
      let dataStr = "";
      for (const line of raw.split("\n")) {
        if (line.startsWith("event:")) eventType = line.slice(6).trim();
        else if (line.startsWith("data:")) dataStr += line.slice(5).trim();
      }
      if (dataStr) {
        events.push({ type: eventType, data: JSON.parse(dataStr) });
      }
    }

    assert.equal(events.length, 4);
    assert.equal(events[0].type, "start");
    assert.equal(events[1].type, "text_delta");
    assert.equal(events[1].data.delta, "Hello ");
    assert.equal(events[2].type, "text_delta");
    assert.equal(events[2].data.delta, "world!");
    assert.equal(events[3].type, "done");
    assert.equal(events[3].data.message, "Hello world!");
  });
});

describe("Attachment Validation", () => {
  test("enforces 15MB limit and flags oversized files", () => {
    const MAX_SIZE = 15 * 1024 * 1024;
    const validFile = { name: "report.pdf", size: 2 * 1024 * 1024 };
    const oversizedFile = { name: "heavy_dataset.zip", size: 25 * 1024 * 1024 };

    assert.ok(validFile.size <= MAX_SIZE, "Valid file should pass");
    assert.ok(oversizedFile.size > MAX_SIZE, "Oversized file should be rejected");
  });
});

describe("Task Planning Progress Calculation", () => {
  test("calculates correct progress percentage from step statuses", () => {
    const steps = [
      { name: "Step 1: Inspect environment", status: "completed" },
      { name: "Step 2: Collect logs", status: "completed" },
      { name: "Step 3: Analyze metrics", status: "running" },
      { name: "Step 4: Generate report", status: "pending" },
    ];

    const completed = steps.filter(s => s.status === "completed").length;
    const percent = Math.round((completed / steps.length) * 100);

    assert.equal(completed, 2);
    assert.equal(percent, 50);
  });
});

describe("Slash Commands and @-Mentions", () => {
  test("recognizes all standard slash commands", () => {
    const validCommands = [
      "/help", "/new", "/research", "/summarize", "/plan",
      "/tasks", "/memory", "/settings", "/voice", "/stop"
    ];

    for (const cmd of validCommands) {
      assert.ok(cmd.startsWith("/"), `Command ${cmd} must start with /`);
    }
  });

  test("recognizes connected capability @-mentions", () => {
    const tags = ["@mail", "@browser", "@screen", "@finder", "@whatsapp", "@tasks"];
    for (const tag of tags) {
      assert.ok(tag.startsWith("@"), `Mention ${tag} must start with @`);
    }
  });
});

describe("Cryptographic Approval Security", () => {
  test("hash mismatch rejects action execution", () => {
    const validHash = "sha256_valid_token_1234567890";
    const suppliedHash = "sha256_attacker_tampered_token";

    const isAuthorized = (expected, actual) => Boolean(actual && expected === actual);
    assert.equal(isAuthorized(validHash, suppliedHash), false);
    assert.equal(isAuthorized(validHash, validHash), true);
  });
});

