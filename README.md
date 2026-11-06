# OpenSource Guardian

> Intelligent open-source repository governance, automated educational triage, and multi-agent collaboration powered by Switch AI. Built for the **Flip the Switch Hackathon**.

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688.svg)](https://fastapi.tiangolo.com/)
[![Tests](https://img.shields.io/badge/pytest-83%20passed-brightgreen.svg)](tests/)
[![Switch AI](https://img.shields.io/badge/Switch%20AI-Agent%20Bridge-7952B3.svg)](https://docs.switchagents.ai)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

## Table of Contents

1. [Project Overview](#project-overview)
2. [The Problem: The Open-Source Contributor Barrier](#the-problem-the-open-source-contributor-barrier)
3. [How OpenSource Guardian Solves It](#how-opensource-guardian-solves-it)
4. [Switch Integration & Multi-Agent Collaboration](#switch-integration--multi-agent-collaboration)
5. [System Architecture](#system-architecture)
6. [Supported Commands & Interactive Workflows](#supported-commands--interactive-workflows)
7. [Step-by-Step Setup Guide](#step-by-step-setup-guide)
8. [Container & Cloud Deployment (Docker & Railway)](#container--cloud-deployment-docker--railway)
9. [Automated Pipeline Smoke Test](#automated-pipeline-smoke-test)
10. [Security Guardrails & Safety Baselines](#security-guardrails--safety-baselines)
11. [Known Limitations & Current Environment Status](#known-limitations--current-environment-status)
12. [Project Structure](#project-structure)
13. [Hackathon Milestone Progression](#hackathon-milestone-progression)
14. [Switch Demo](#switch-demo)

---

## Project Overview

**OpenSource Guardian** is an automated repository custodian and pedagogical AI teammate designed to bridge GitHub project activities (incoming pull requests, security alerts, and contributor inquiries) with real-time, human-in-the-loop triage rooms powered by **Switch AI** (`switch-core`).

Instead of isolated bots posting robotic, disconnected comments directly on pull requests or developers drowning in notification fatigue, OpenSource Guardian facilitates collaborative triage inside developer messaging channels (bridged to **Discord** via Switch Collaboration Bridges). In these rooms, human maintainers, first-time contributors, and specialized AI agents work together with shared context, conversational thread memory, and educational feedback.

---

## The Problem: The Open-Source Contributor Barrier

Open-source sustainability faces three chronic friction points:

1. **The Onboarding Maze**: New contributors often spend hours attempting to understand a project's purpose, structure, and development environment because setup documentation is outdated, buried across multiple directories, or non-existent.
2. **The "Good First Issue" Trap**: Issues labeled `good first issue` are frequently stale, taken without assignment, or secretly depend on unwritten domain knowledge. Beginners get stuck before writing their first line of code.
3. **Impersonal or Punitive PR Reviews**: Automated linters fail without explaining *why*, and busy maintainers rarely have the bandwidth to teach git conventions, test design, or security hygiene. Contributors feel discouraged and abandon their contributions.

---

## How OpenSource Guardian Solves It

OpenSource Guardian functions as a patient, knowledgeable mentor directly in community chat channels:

- **Repository Onboarding (`RepoOnboarder`)**: Parses `README.md`, `CONTRIBUTING.md`, architecture documents, and project manifests to synthesize an instant, structured summary of project goals, tech stack, and local development setup.
- **Beginner Issue Discovery (`IssueFinder`)**: Queries open issues, filters out pull requests, extracts prerequisites, evaluates issue clarity, and provides actionable guidance for newcomers.
- **Pedagogical PR Review (`PRReviewer`)**: Uses a deterministic unified diff parser and static heuristics to evaluate PRs. Rather than simply rejecting code, it highlights positive contributions first, checks for test accompaniment, flags accidental secrets or debug prints, and explains *why* a particular change is recommended.
- **Conversational Thread Memory (`ThreadContext`)**: Remembers the active PR number, findings, and positive notes within a Discord thread. Maintainers and contributors can ask contextual follow-up questions without repeating PR numbers or repository names.

---

## Switch Integration & Multi-Agent Collaboration

OpenSource Guardian connects to **Switch AI** through the official Agent Bridge protocol:

### 1. WebSocket Connection Lifecycle (`SwitchClient`)
- Establishes a persistent WebSocket connection to `switch-core` at `/agents/{agent_id}/connection/ws`.
- Sends WebSocket headers including `Authorization: Bearer <SWITCH_API_KEY>` and connection tracking headers.
- Handles periodic `ping` control frames with immediate `pong` replies (2-second interval) to keep the agent connection alive.
- Supports sequence cursor resumption and handles connection lifecycle frames (`connection_state`, `evicted`, `refused`).

### 2. Event Dispatching & Discord Bridge Ingestion (`SwitchEventDispatcher`)
- Listens to incoming domain events (`type: "message"` or `"chat_message"`) emitted by Switch rooms and Discord Collaboration Bridges.
- Detects mentions (`@opensource-guardian`, `@guardian`, `!guardian`) and extracts commands.
- Normalizes sender information, room IDs, message text, and thread root IDs (`thread_id`).

### 3. REST Operations
- Delivers rich Markdown reports and follow-up replies back to the Switch room and bridged Discord thread via `POST /agents/{agent_id}/ops/post_message`.
- Supports room joining operations via `POST /agents/{agent_id}/ops/connect_to_room`.

### 4. Multi-Agent Collaboration & Loop Prevention
- **Self-Message Suppression**: The dispatcher detects and drops messages from `guardian` or its own registered `agent_id`.
- **Outbound Mention Sanitization**: Guardian's replies never include `@guardian` triggers, preventing circular wakeups.
- **Unaddressed Chatter Filtering**: Messages exchanged between humans and third-party agents (e.g. `@sarah-maintainer check this from @ci-helper-agent`) are ignored.

### 5. Conversational Thread Context
- Stores a bounded in-memory cache of `ThreadContext` records (capped at 100 entries FIFO).
- Recognizes follow-up topics (test coverage, security status, summary recap, or re-review) and resolves context dynamically.

---

## System Architecture

```mermaid
flowchart TB
    subgraph Discord["Discord Community Workspace"]
        Contributor["New Contributor"]
        Maintainer["Project Maintainer"]
        OtherAgent["Third-Party Agent (e.g. CI Helper)"]
    end

    subgraph SwitchInfra["Switch Infrastructure (switch-core)"]
        Bridge["Discord Collaboration Bridge\n(Discord Gateway)"]
        Room["Switch Collaborative Room\n(Message Bus / Event Stream)"]
        AgentBridge["Switch Agent Bridge\n(WebSocket & REST Operations)"]
        
        Bridge <--> Room
        AgentBridge <--> Room
    end

    subgraph Guardian["OpenSource Guardian Service"]
        WS["Switch Client\n(WebSocket Stream & Heartbeats)"]
        Dispatcher["Switch Event Dispatcher\n(Command Router & Thread Memory)"]
        
        subgraph CoreEngines["Guardian Core Engines"]
            PR["PR Guardian Reviewer\n(Diff Parser & Static Heuristics)"]
            IF["Issue Finder\n(Clarity Ranker & Context Extractor)"]
            OB["Repo Onboarder\n(Documentation & Architecture Parser)"]
        end
        
        GH["GitHub Client Adapter\n(Async Read-Only REST)"]
        API["FastAPI App\n(Health & Diagnostics /health)"]
    end

    subgraph GitHub["GitHub Platform"]
        GHAPI["GitHub REST API v3\n(Metadata, Diffs, Issues, Files)"]
    end

    %% Communication Flows
    Contributor -->|Chat: @guardian review PR #12| Bridge
    Maintainer -->|Chat: @guardian what tests are missing?| Bridge
    OtherAgent -.->|Room Activity (Ignored by Loop Guard)| Bridge
    
    AgentBridge -->|WebSocket Domain Event Frame| WS
    WS --> Dispatcher
    Dispatcher --> CoreEngines
    CoreEngines --> GH
    GH -->|Read-Only HTTPS GET| GHAPI
    GHAPI -->|PR Diffs & Issue JSON| GH
    CoreEngines --> Dispatcher
    Dispatcher -->|REST: POST /agents/.../post_message| AgentBridge
    Room -->|Render Markdown in Active Thread| Bridge
    Bridge -->|Display in Thread| Contributor
    Bridge -->|Display in Thread| Maintainer
```

---

## Supported Commands & Interactive Workflows

All commands are case-insensitive and support both `@guardian` and `@opensource-guardian` mentions:

| Command | Action | Example |
| :--- | :--- | :--- |
| `review PR #<number>` | Parses PR diff, runs security and educational heuristics, and outputs structured Markdown review | `@guardian review PR #42` |
| `review <owner/repo>#<number>` | Reviews a PR on an explicit repository | `@guardian review acme/backend#10` |
| `find good first issues` | Queries and ranks beginner-friendly issues with setup prerequisites | `@guardian find good first issues` |
| `find issues <topic>` | Searches open issues matching a language or topic tag | `@guardian find issues python` |
| `onboard` | Synthesizes repository documentation into a new contributor guide | `@guardian onboard` |
| `help` | Lists available commands, examples, and follow-up guidance | `@guardian help` |

### Supported Thread Follow-Up Workflows

When replying within an existing review thread, the PR number and repository context are automatically preserved:

- **Test Status**: `@guardian what tests are missing?` or `@guardian test coverage`  
  *Summarizes test accompaniment findings and recommends specific unit tests to write.*
- **Security Check**: `@guardian is there any security concern?` or `@guardian security status`  
  *Confirms whether any hardcoded credentials or security smells were detected.*
- **Executive Recap**: `@guardian recap findings` or `@guardian summarize review`  
  *Produces a high-level briefing highlighting positive aspects and priority fixes.*
- **Re-review Diff**: `@guardian review again` or `@guardian re-review`  
  *Fetches the updated diff from GitHub and generates a fresh review report.*

---

## Step-by-Step Setup Guide

### 1. Prerequisites
- Python 3.11, 3.12, or 3.13
- Git
- (Optional) Running instance of `switch-core` (or use mock mode for offline testing)
- (Optional) GitHub Personal Access Token (for higher API rate limits)

### 2. Clone the Repository
```bash
git clone https://github.com/aadesh-2006/OpenSource-Guardian.git
cd OpenSource-Guardian
```

### 3. Setup Virtual Environment
```bash
# Create virtual environment
python -m venv .venv

# Activate environment
# On Windows (PowerShell):
.\.venv\Scripts\Activate.ps1
# On Linux / macOS:
source .venv/bin/activate
```

### 4. Install Dependencies
```bash
# Install package in editable mode with development dependencies
pip install -e .
```

### 5. Configure Environment Variables
Copy the example configuration file:
```bash
cp .env.example .env
```

Edit `.env` with your preferred settings:
```ini
# Application Configuration
APP_NAME="OpenSource Guardian"
ENVIRONMENT=development
LOG_LEVEL=INFO

# Server Bindings
HOST=0.0.0.0
PORT=8000

# GitHub Integration (Read-Only)
GITHUB_TOKEN=your_github_personal_access_token_here
GITHUB_API_BASE_URL=https://api.github.com
DEFAULT_REPO=aadesh-2006/OpenSource-Guardian

# Switch Agent Bridge Integration
SWITCH_API_URL=http://localhost:8080
SWITCH_AGENT_ID=agent-opensource-guardian
SWITCH_API_KEY=your_switch_agent_bearer_token
SWITCH_ROOMS=default
```

> [!IMPORTANT]
> Never commit your `.env` file to version control. The repository `.gitignore` automatically excludes `.env` and credential files.

### 6. Start the FastAPI Service
```bash
uvicorn src.guardian.main:app --host 0.0.0.0 --port 8000 --reload
```
Verify the health check in your browser or via curl:
```bash
curl http://localhost:8000/health
# Response: {"status":"healthy","app":"OpenSource Guardian"}
```

### 7. Run the Test Suite
Run the full test suite (83 tests covering unit, adapter, module, E2E, protocol, and server lifespan logic):
```bash
pytest -v
```

---

## Container & Cloud Deployment (Docker & Railway)

OpenSource Guardian is packaged with a minimal, production-ready `Dockerfile` based on `python:3.12-slim` and natively configured for deployment on **Railway**.

### 1. Build and Run with Docker Locally

#### Build the Docker Image
```bash
docker build -t opensource-guardian:latest .
```

#### Run in Health-Only Mode (Offline / Initial Smoke Test)
```bash
docker run --rm -p 8000:8000 opensource-guardian:latest
```
Verify the container health endpoint:
```bash
curl http://localhost:8000/health
# Response: {"status":"healthy","app":"OpenSource Guardian","version":"0.1.0","environment":"development","mode":"health_only"}
```

#### Run with Full Switch & GitHub Integration
```bash
docker run --rm -p 8000:8000 \
  -e SWITCH_API_URL="http://your-switch-server:8080" \
  -e SWITCH_AGENT_ID="your-agent-id" \
  -e SWITCH_API_KEY="your-switch-api-key" \
  -e GITHUB_TOKEN="your-github-token" \
  -e DEFAULT_REPO="aadesh-2006/OpenSource-Guardian" \
  opensource-guardian:latest
```

---

### 2. Deploying to Railway

Railway runs persistent Linux containers without aggressive HTTP sleep timeouts, making it ideal for maintaining the outbound Switch WebSocket connection.

1. **Create a Railway Project**:
   - Go to [railway.app](https://railway.app) and create a new project.
   - Select **Deploy from GitHub repo** and connect `OpenSource-Guardian`.
2. **Configuration Detection**:
   - Railway automatically detects [`railway.json`](file:///C:/Users/Aadesh/.gemini/antigravity/scratch/OpenSource-Guardian/railway.json) and builds using [`Dockerfile`](file:///C:/Users/Aadesh/.gemini/antigravity/scratch/OpenSource-Guardian/Dockerfile).
   - Railway automatically sets the dynamic `$PORT` environment variable, which Uvicorn binds to automatically.
3. **Configure Environment Variables in Railway**:
   Under the service **Variables** tab, set:
   - `ENVIRONMENT`: `production`
   - `LOG_LEVEL`: `INFO`
   - `DEFAULT_REPO`: `aadesh-2006/OpenSource-Guardian`
   - `GITHUB_TOKEN`: Your read-only GitHub PAT
   - `SWITCH_API_URL`: Base URL of your running Switch Core instance (e.g. `http://switch-core.railway.internal:8080` or public URL)
   - `SWITCH_AGENT_ID`: Your registered Switch Agent ID
   - `SWITCH_API_KEY`: Your Switch Agent bearer token
   - `SWITCH_ROOMS`: `default` (or your target room ID)
4. **Health Check Verification**:
   - Railway probes the configured `healthcheckPath: "/health"` after build completion.
   - Once verified, the service transitions to **Active**.

---

## Automated Pipeline Smoke Test

OpenSource Guardian provides a dedicated, multi-stage smoke-test runner in `scripts/smoke_test.py` that validates the complete integration pipeline.

### Running in Mock / Contract Dry-Run Mode (Offline / CI)
To validate configuration, ASGI service health, GitHub client contract, Switch REST operations, event dispatching, and thread context caching without requiring external servers:
```bash
python scripts/smoke_test.py --mock
```

**Expected Output**:
```text
=================================================================
OPENSOURCE GUARDIAN -- PIPELINE SMOKE TEST (MOCK / CONTRACT-DRY-RUN)
=================================================================

--- STAGE 1: Configuration Inspection ---
  SWITCH_API_URL:       Present
  SWITCH_AGENT_ID:      Missing
  SWITCH_API_KEY:       Missing
  GITHUB_TOKEN:         Present (Masked)
  DEFAULT_REPO:         aadesh-2006/OpenSource-Guardian
  TEST_ROOM_ID:         smoke-test-room
[1/5] [PASS] | Configuration Validation - Configuration verified safely.

--- STAGE 2: Local Service Health Check ---
[2/5] [PASS] | Service Health - HTTP 200 OK (app: OpenSource Guardian)

--- STAGE 3: GitHub Read-Only API Client Probe ---
[3/5] [PASS] | GitHub Read API - Mocked probe: repo 'aadesh-2006/OpenSource-Guardian' verified.

--- STAGE 4: Switch Agent Bridge REST Probe ---
[4/5] [PASS] | Switch REST Bridge - Mocked probe: simulated successful post_message.

--- STAGE 5: Event Dispatch & Review Pipeline ---
[5/5] [PASS] | Event Dispatch & Review - PR review generated and routed in thread.

=================================================================
SUMMARY: 5/5 stages passed.
=================================================================
```

### Running in Live Mode
When live Switch infrastructure and credentials are configured:
```bash
python scripts/smoke_test.py
```

- If credentials or Switch services are missing, the script cleanly prints missing requirements, provides troubleshooting guidance, and exits with code `2` without leaking secrets.
- When live services are reachable, it probes live endpoints and exits with code `0`.

---

## Security Guardrails & Safety Baselines

OpenSource Guardian enforces strict security and execution safety guardrails:

- **Zero Arbitrary Code Execution**: Pull request diffs are analyzed using static text tokenization, hunk boundary parsing, and regular expression heuristics. Contributor code is **never** executed, imported, or evaluated in a Python runtime.
- **Read-Only GitHub Access**: OpenSource Guardian requires only read-only permissions (`public_repo` or repository read access). It does not post direct PR comments on GitHub, approve PRs, or modify repository branches. All feedback is delivered inside the collaborative Switch/Discord room.
- **Strict Secret Masking**: Patterns matching GitHub tokens, AWS access keys, SSH private keys, and generic authorization tokens are detected and redacted. Detected secret values are never printed in logs, exception traces, review findings, or chat messages.

---

## Known Limitations & Current Environment Status

In accordance with hackathon evaluation standards, the following project boundaries and current limitations are transparently disclosed:

1. **Live Discord & Switch Server Verification**:
   - In the development environment, live Switch Agent Bridge and Discord bot credentials were not available.
   - All Switch WebSocket frame handling, cursor tracking, heartbeat handling, REST operations, and multi-agent interaction flows have been fully verified via automated tests with mock protocol transports (`tests/test_switch_client.py`, `tests/test_e2e_integration.py`).
2. **In-Memory Thread Context**:
   - The conversational thread memory (`ThreadContext`) is currently held in an in-memory dictionary bounded to 100 entries with FIFO eviction. Thread history does not persist across service restarts.
3. **Static Heuristic Depth**:
   - Diff analysis evaluates test presence, diff size, documentation synchronization, and common anti-patterns statically. It does not perform full abstract syntax tree (AST) semantic cross-file type resolution.

---

## Project Structure

```text
OpenSource-Guardian/
├── .dockerignore               # Docker build exclusions
├── .env.example                # Canonical environment variable configuration template
├── Dockerfile                  # Production container definition (Python 3.12-slim)
├── pyproject.toml              # Dependencies and project build configuration
├── railway.json                # Native Railway build, deploy & healthcheck configuration
├── README.md                   # Complete judge-ready documentation
├── docs/
│   ├── ARCHITECTURE.md         # Full system architecture and Switch boundaries
│   ├── ROADMAP.md              # Milestone tracking and completion status
│   ├── HACKATHON_SUBMISSION.md # Comprehensive hackathon submission write-up
│   └── DEMO_GUIDE.md           # Step-by-step reproduction and demo guide
├── scripts/
│   └── smoke_test.py           # Multi-stage automated pipeline smoke test
├── src/
│   └── guardian/
│       ├── main.py             # FastAPI entrypoint and health probe (/health)
│       ├── config/
│       │   └── settings.py     # Typed Pydantic configuration with secret masking
│       ├── adapters/
│       │   ├── github_client.py     # Async read-only GitHub REST client
│       │   ├── switch_client.py     # Switch Agent Bridge WS client & REST ops
│       │   ├── switch_protocol.py   # Switch frame and domain event models
│       │   └── switch_dispatcher.py # Command routing, multi-agent loop prevention & thread memory
│       └── modules/
│           ├── onboarding.py   # Repository onboarding summary generator
│           ├── issue_finder.py # Beginner issue curation and ranking engine
│           └── pr_reviewer.py  # Diff parser and educational review engine
└── tests/
    ├── test_main.py            # Application startup and configuration tests
    ├── test_health.py          # Health check endpoint tests
    ├── test_github_client.py   # GitHub adapter tests with mock transports
    ├── test_modules.py         # Onboarding and issue finder heuristic tests
    ├── test_pr_reviewer.py     # Diff parsing, secret masking, and review tests
    ├── test_switch_protocol.py # Frame parsing, validation, and serialization tests
    ├── test_switch_client.py   # WebSocket lifecycle, heartbeat, and REST ops tests
    ├── test_switch_dispatcher.py # Command parsing, routing, and thread context tests
    ├── test_e2e_integration.py # End-to-end workflows and multi-agent collaboration tests
    └── test_smoke_test.py      # Smoke test runner tests
```

---

## Hackathon Milestone Progression

- [x] **M0 — Repository Reconnaissance**: Environment verification and initial setup.
- [x] **M1 — Repository Initialization**: Git workspace setup, `.gitignore`, and foundational layout.
- [x] **M2 — Architecture & Roadmap Specification**: Comprehensive system architecture and milestone plans.
- [x] **M3 — Application Foundation & Configuration**: FastAPI skeleton, Pydantic settings, and health probe.
- [x] **M4 — GitHub Integration Adapter**: Async read-only GitHub REST client and error handling.
- [x] **M5 — Repository Onboarding & Issue Discovery**: Onboarding engine and beginner issue discovery.
- [x] **M6 — PR Guardian Reviewer**: Unified diff parser and educational review report generator.
- [x] **M7 — Switch Agent Integration**: Switch Agent Bridge WebSocket engine, heartbeats, and REST ops.
- [x] **M8 — End-to-End Integration & Multi-Agent Collaboration**: E2E pipeline, thread memory, loop guards, and smoke test.
- [x] **M9 — Polish, Documentation & Hackathon Submission**: Judge-ready README, submission write-up, and demo guide.

---

## Switch Demo

OpenSource Guardian demonstrates a repository review workflow
through Switch-connected AI agents.

The current local smoke test validates the review pipeline using
mocked Switch responses. Live Bridge credentials are required for
the standalone Guardian app to receive real Switch events.
