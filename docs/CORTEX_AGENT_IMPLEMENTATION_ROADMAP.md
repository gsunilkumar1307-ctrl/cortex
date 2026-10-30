# Cortex Agent — Implementation Roadmap & Execution Plan

**Objective:** Transform Cortex Agent into an autonomous, context-aware desktop operator with robust desktop application control and verifiable WhatsApp automation.

---

## Roadmap Phases

### Phase 1: Goal-Driven Agent Engine & Capability Registry
- **Deliverable:** Structured goal representations (`StructuredGoal`), deterministic schema validation, decoupled understanding/planning/execution/verification, composable capability registry.
- **Key Modules:** `backend/core/contracts.py`, `backend/tools/registry.py`, `backend/agent/planner.py`.

### Phase 2: Robust Desktop Control & Application Lifecycle
- **Deliverable:** Verified application resolution with aliases, running status checks, window close vs application quit distinction, unsaved changes safeguard.
- **Key Modules:** `backend/capabilities/device_actions.py`, `backend/tools/desktop_tool.py`.

### Phase 3: WhatsApp Automation (High Priority)
- **Deliverable:** Dedicated WhatsApp integration (`WhatsAppAutomation`), phone number & contact resolution, human-like message composition, conversational multi-turn follow-ups, preview & cryptographic approval gate, verifiable send outcome.
- **Key Modules:** `backend/capabilities/whatsapp_actions.py`, `backend/agent/orchestrator.py`, `backend/agent/recipient_resolver.py`.

### Phase 4: General-Purpose Tasks & Productivity
- **Deliverable:** File movement (`move_file`), document creation (`create_document`), default browser navigation, robust task execution with observable verification.
- **Key Modules:** `backend/capabilities/device_actions.py`, `backend/tools/file_tool.py`.

### Phase 5: Verification, Multi-Turn Continuity & Quality Assurance
- **Deliverable:** Comprehensive automated test suites, regression protection for all 362 existing tests, production build verification.
- **Key Modules:** `tests/test_cortex_desktop_operator.py`, `tests/test_whatsapp_automation.py`.

