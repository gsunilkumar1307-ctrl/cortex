# Cortex Developer Guide

## Prerequisites
- macOS Sonoma / Sequoia (or Linux / Windows 11)
- Python 3.9+ (Python 3.11+ recommended)
- Node.js 18+ and npm
- Google Gemini API key (`export GEMINI_API_KEY="your-key"`)

---

## Workspace Setup
1. **Clone & Install Dependencies:**
   ```bash
   cd Codex/2026-06-17/files-mentioned-by-the-user-cortex
   pip install -r backend/requirements.txt
   python3 -m playwright install chromium
   npm install --prefix apps/desktop
   ```

2. **Configure Environment:**
   Add your Gemini API key to your shell profile (`~/.zshrc`) or `.env`:
   ```bash
   export GEMINI_API_KEY="AIzaSy..."
   ```

---

## Running the Application
Launch both backend and the Electron companion UI in one command:
```bash
npm start
# OR directly
./start-cortex.sh
```

- **Backend API:** `http://127.0.0.1:8765`
- **Vite Dev Server:** `http://127.0.0.1:5173`
- **Logs:** `logs/brain.log` and `logs/vite.log`

---

## Running Tests
Run the entire automated test suite (177 tests):
```bash
npm test
# OR directly
python3 -m unittest discover -s tests
```

To run a specific test suite:
```bash
python3 -m unittest tests/test_agent_pipeline_and_email_engine.py
python3 -m unittest tests/test_intelligent_email_agent.py
python3 -m unittest tests/test_master_directive_compliance.py
```

---

## Live System Verification
To verify the full live agent pipeline (recipient resolution, grounded composition, Apple Mail draft creation, and cryptographic approval gate):
```bash
npm run verify
# OR directly
python3 scripts/verify_mail_live.py
```

---

## Building Production Desktop App
To compile and bundle the desktop application:
```bash
npm run build
```
The optimized bundle will be generated in `apps/desktop/dist/`.
