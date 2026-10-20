# Cortex Desktop MVP

Cortex is a desktop-first AI operating assistant MVP focused on safe device control. This repository is structured as a monorepo so the desktop shell, backend orchestration, memory, automation, voice, and shared contracts can evolve independently while sharing one task model.

## What Works In This MVP

- Shared task and approval contracts for Python and TypeScript.
- Safety classification for allowed, approval-gated, and blocked commands.
- Python backend with `/health`, `/chat`, `/tasks/:id/approve`, `/tasks/:id/cancel`, `/tasks/:id/events`, and `/memory`.
- Device automation adapters for macOS and Windows with a dry-run default.
- Encrypted local SQLite memory and audit storage.
- Electron + React + Tailwind desktop app scaffold.
- Unit and integration tests using the Python standard library.

## Quick Start

Run backend tests:

```bash
python3 -m unittest discover -s tests
```

Run the dependency-light backend:

```bash
python3 cloud-brain/app/server.py
```

Open the browser voice UI:

```text
http://127.0.0.1:8765/
```

Then call it:

```bash
curl -X POST http://127.0.0.1:8765/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"open calculator"}'
```

By default, device execution uses dry-run mode. Set `CORTEX_EXECUTION_MODE=live` only after reviewing the command adapters.

## App Automation Commands

Try these by voice or text:

```text
open Calculator
close Calculator
switch to Notes
type hello world in Notes
press command s in Notes
choose New from File menu in Notes
open Notes then type hello in Notes then press command s in Notes
calculate 9 times 8
write note called Groceries saying buy milk
send message to Sam saying hello
```

These commands are powered by universal OS automation primitives. They work best for normal desktop apps with standard windows, menus, and keyboard shortcuts. Complex app-specific workflows will be added as dedicated skills on top of these primitives.

Message sending requires explicit approval before Cortex sends anything.

## Production Dependencies To Add

The code is intentionally runnable without network access. For the production beta, install the declared frontend and backend dependencies in each package and replace the stdlib HTTP server with FastAPI routing from the same orchestration layer.
