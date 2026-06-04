# ADA Agent — Secure AI Executive Assistant

> A safety-first AI agent for managing email workflows with human-in-the-loop controls, Gmail integration, and Google Cloud persistence.

![Python](https://img.shields.io/badge/Python-3.12-blue)
![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-green)
![Gemini](https://img.shields.io/badge/LLM-Gemini%202.5%20Flash-purple)
![Firestore](https://img.shields.io/badge/Database-Firestore-orange)
![Gmail](https://img.shields.io/badge/Email-Gmail%20API-red)

---

## Overview

ADA Agent is an AI-powered email assistant that helps professionals draft, schedule, and send emails — all under strict human-in-the-loop approval. Every sensitive action requires explicit user confirmation before execution.

**Key principles:**
- 🔒 No email is ever sent without your explicit approval
- 🛡️ All external content (email bodies, meeting notes) is sanitised before reaching the LLM
- 👤 Each user has their own isolated account and data
- 📋 Every agent action is recorded in a tamper-evident audit log

---

## Features

| Feature | Description |
|---|---|
| ✉️ **AI Draft Generation** | Describe what you need in plain language — the agent drafts the email |
| 🎨 **Tone Profiles** | Automatically learns your writing style per recipient from Gmail sent history |
| 📎 **Meeting Notes** | Attach `.txt` or `.md` files as context for drafts |
| 🗓️ **Scheduled Sending** | Schedule emails for future delivery — saved to Gmail Drafts immediately |
| ⚑ **Approval Gates** | Every send and schedule action requires explicit confirmation |
| 🔍 **Audit Log** | Append-only, tamper-evident record of all agent actions |
| 👥 **Multi-user** | Separate accounts with unique emails and isolated data |
| ☁️ **Cloud Persistence** | Users, sessions, and audit logs stored in Google Cloud Firestore |

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Python 3.12, FastAPI, Uvicorn |
| Frontend | Vanilla HTML/CSS/JS (no framework) |
| LLM | Google Gemini 2.5 Flash via `google-generativeai` |
| Email | Gmail API via `google-api-python-client` |
| Database | Google Cloud Firestore |
| Auth | OAuth 2.0 (Gmail), SHA-256 password hashing |

---

## Project Structure

```
├── src/
│   ├── approval/          # Approval gate controller
│   ├── audit/             # Append-only audit logger
│   ├── auth/              # Session manager, OAuth flow
│   ├── db/                # Firestore database layer
│   ├── gmail/             # Gmail API client
│   ├── integration/       # Orchestrator factory
│   ├── models/            # Pydantic data models
│   ├── orchestrator/      # Central agent coordinator
│   ├── permissions/       # Permission manager
│   ├── prompt/            # Prompt builder & sanitiser
│   ├── scheduling/        # Scheduled draft manager + background scheduler
│   ├── tone/              # Tone profile engine
│   └── ui/                # FastAPI routes + static frontend
├── tests/                 # Unit and integration tests
├── run_ui.py              # Entry point
├── gmail_auth.py          # One-time Gmail OAuth setup
└── pyproject.toml
```

---

## Prerequisites

- Python 3.12+
- A [Google Cloud project](https://console.cloud.google.com) with:
  - Gmail API enabled
  - Firestore database created (Native mode)
  - Application Default Credentials configured (`gcloud auth application-default login`)
- A [Gemini API key](https://aistudio.google.com/app/apikey)

---

## Setup

### 1. Clone the repository

```bash
git clone https://github.com/YOUR_USERNAME/ada-agent.git
cd ada-agent
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

Or if using `pyproject.toml`:

```bash
pip install -e .
```

### 3. Configure environment variables

Create a `.env` file in the project root:

```env
# Gemini API key — get one at https://aistudio.google.com/app/apikey
GEMINI_API_KEY=your_gemini_api_key_here

# Gemini model (optional, default shown)
GEMINI_MODEL=gemini-2.5-flash

# Google Cloud Firestore
GOOGLE_CLOUD_PROJECT=your-project-id
FIRESTORE_DATABASE=your-database-name
```

### 4. Authorise Gmail access

Download `credentials.json` from Google Cloud Console (OAuth 2.0 Desktop Client), place it in the project root, then run:

```bash
python gmail_auth.py
```

This opens a browser for Google sign-in and saves `token.json`.

### 5. Configure Application Default Credentials (for Firestore)

```bash
gcloud auth application-default login --project=your-project-id
```

### 6. Start the server

```bash
python run_ui.py
```

Open [http://localhost:8000](http://localhost:8000) in your browser.

---

## First Use

1. Click **Sign Up** and create an account with your email and a password
2. Sign in
3. Go to **Chat with Agent**
4. Select **✉ Draft** mode and type: *"Draft an email to alice@example.com about the project update"*
5. Review the generated draft and click **↗ Send this draft** to send it via Gmail

---

## Usage Guide

### Drafting an email
Select **✉ Draft** mode, describe the email in plain language. The agent will:
- Fetch related emails from your Gmail inbox for context
- Derive a tone profile from your sent history to that recipient
- Generate a draft with subject and body

### Scheduling an email
Select **🗓 Schedule** mode and include a time in your instruction:
> *"Schedule an email to bob@example.com about the Monday standup for tomorrow at 9am"*

Confirm the approval gate → the draft is saved to your Gmail Drafts folder and sent automatically at the scheduled time.

### Attaching meeting notes
Click the 📎 button in the chat input to attach a `.txt` or `.md` file. The agent uses it as context when drafting.

### Cancelling a scheduled email
Select **✖ Cancel** mode, or click the Cancel button in the Scheduled Drafts view.

---

## Security

- **Prompt injection prevention** — all email bodies and meeting notes are wrapped in `<untrusted_content>` delimiters and never treated as instructions
- **Human-in-the-loop** — no email is sent or scheduled without explicit user confirmation
- **Credential safety** — `token.json`, `credentials.json`, and `.env` are excluded from version control

### Files never to commit

```
token.json          # Gmail OAuth tokens
credentials.json    # Google OAuth client credentials
.env                # API keys
data/               # Local SQLite fallback (if used)
```

---

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `GEMINI_API_KEY` | ✓ | Gemini API key from Google AI Studio |
| `GEMINI_MODEL` | ✗ | Model name (default: `gemini-2.5-flash`) |
| `GOOGLE_CLOUD_PROJECT` | ✓ | Google Cloud project ID |
| `FIRESTORE_DATABASE` | ✓ | Firestore database name |

---

## Running Tests

```bash
pytest tests/
```

---

## Architecture

See the [System Architecture](./docs/architecture.md) for a full diagram, or refer to the design document at `.kiro/specs/secure-ai-executive-assistant/design.md`.

---

## Licence

MIT
