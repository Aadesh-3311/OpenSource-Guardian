# OpenSource Guardian

> Intelligent open-source repository governance, automated triage, and security orchestration powered by Switch AI. Built for the **Flip the Switch Hackathon**.

---

## Overview

**OpenSource Guardian** is an automated repository custodian and pedagogical AI teammate designed to bridge GitHub project activities (incoming pull requests, security alerts, and contributor inquiries) with real-time, human-in-the-loop triage rooms powered by **Switch AI** (`switch-core`).

Instead of isolated bots posting disconnected comments or developers drowning in notification noise, OpenSource Guardian facilitates collaborative triage directly in messaging channels (bridged to **Discord** via Switch Collaboration Bridges) where maintainers, new contributors, and specialized AI agents work together with shared context.

---

## End-to-End System Architecture

```
[ Contributor / Maintainer ]  ◄──►  [ Other Switch Agents ]
              │                               │
              ▼                               ▼
       [ Discord Channel / Bridged Thread ]
                       │
                       ▼ (Discord Gateway)
         [ Switch Discord Collaboration Bridge ]
                       │
                       ▼ (WebSocket Domain Events)
             [ Switch Agent Bridge / Room ]
                       │
                       ▼
       [ OpenSource Guardian Service ]
         ├── Switch Client & WebSocket Listener (Heartbeat + Reconnect)
         ├── Switch Event Dispatcher & Thread Memory Context
         ├── Command Router (@guardian review PR #X, onboard, find issues)
         ├── PR Guardian Reviewer (Static Unified Diff Parser & Heuristics)
         ├── Repo Onboarder & Issue Discovery Engine
         └── GitHub REST API Adapter (Read-Only)
                       │
                       ▼ (HTTPS REST)
               [ GitHub API (v3) ]
```

### Key Workflow & Multi-Agent Collaboration

1. **Contributor Mentions Guardian in Discord**:
   - In a bridged Discord channel or thread, a contributor types:
     `@guardian review PR #42`
2. **Switch Collaboration Bridge Routes to Room**:
   - The Discord bridge translates chat events into normalized Switch domain events (`type: "message"` or `"chat_message"`) with sender identity, room ID, message content, and thread ID.
3. **Loop-Safe Multi-Agent Event Dispatch**:
   - The `SwitchEventDispatcher` inspects incoming messages.
   - Outbound messages from Guardian omit self-mentions.
   - Messages sent by Guardian itself or containing Guardian's identity are ignored to guarantee zero infinite loops when collaborating with other AI agents in the room.
4. **Execution & Analysis**:
   - Guardian resolves repository targets (`owner/repo`), queries the read-only GitHub API for PR metadata and raw diff text, parses hunks deterministically without executing code, runs security/educational heuristics, and formats a constructive Markdown review.
5. **Threaded Follow-Ups & Memory**:
   - Guardian records active thread context (`ThreadContext`) indexed by `thread_id`.
   - Maintainers or contributors can ask follow-ups in the thread (e.g., `@guardian what tests are missing?`, `@guardian is there any security concern?`, or `@guardian review again`) without re-specifying the PR number or repository.
6. **Delivery Back to Discord**:
   - Guardian posts the response back to Switch (`POST /agents/{agent_id}/ops/post_message`) with the appropriate `room_id` and `thread_id`, which the Discord bridge renders directly inside the active Discord conversation.

---

## Supported Commands & Interactions

| Command | Description | Example |
| :--- | :--- | :--- |
| `review PR #<number>` | Performs static unified diff analysis, security checks, and educational review | `@guardian review PR #12` |
| `find good first issues` | Queries and ranks beginner-friendly issues with setup tips | `@guardian find good first issues` |
| `find issues <topic>` | Searches open issues matching a topic or language | `@guardian find issues python` |
| `onboard` | Generates a quick repository overview, tech stack, and setup guide | `@guardian onboard` |
| `help` | Lists available commands and usage hints | `@guardian help` |
| *Thread Follow-up: Tests* | In a review thread, checks test coverage and missing test cases | `@guardian what tests are missing?` |
| *Thread Follow-up: Security* | In a review thread, details secret findings and security smells | `@guardian is there any security concern?` |
| *Thread Follow-up: Recap* | In a review thread, provides a bulleted executive summary | `@guardian recap findings` |
| *Thread Follow-up: Re-review*| In a review thread, triggers a fresh diff review of the PR | `@guardian review again` |

---

## Configuration & Environment Variables

OpenSource Guardian is configured via environment variables or a `.env` file loaded via `pydantic-settings`:

| Variable | Required | Default | Description |
| :--- | :--- | :--- | :--- |
| `SWITCH_API_URL` | Yes (for Switch) | `http://localhost:8080` | Base URL for `switch-core` Agent Bridge |
| `SWITCH_AGENT_ID` | Yes (for Switch) | — | Registered Agent ID in Switch |
| `SWITCH_API_KEY` | Yes (for Switch) | — | Bearer token / API key for Switch Agent Bridge |
| `SWITCH_ROOMS` | No | `default` | Comma-separated list of room IDs to join |
| `GITHUB_TOKEN` | Recommended | — | Personal Access Token for GitHub API (higher rate limits) |
| `DEFAULT_REPO` | No | `aadesh-2006/OpenSource-Guardian` | Default `owner/repo` when unspecified in commands |
| `APP_ENV` | No | `development` | Application environment (`development`, `staging`, `production`) |
| `LOG_LEVEL` | No | `INFO` | Logging level (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |

---

## Verification & Automated Smoke Test

Guardian includes an automated end-to-end pipeline smoke test (`scripts/smoke_test.py`) that validates the complete integration contract across 5 sequential stages:

```bash
# Run the pipeline smoke test in offline contract / mock mode:
python scripts/smoke_test.py --mock

# Run against live Switch and GitHub services (requires live credentials):
python scripts/smoke_test.py
```

### Smoke Test Stages
1. **Config Validation**: Checks loaded settings and verifies credentials safely (without printing raw secret values).
2. **FastAPI Health Check**: Probes the local ASGI health endpoint (`/health`).
3. **GitHub API Probe**: Validates read-only access to repository metadata and issues.
4. **Switch Bridge Probe**: Tests Switch Agent Bridge connectivity and health.
5. **Event Dispatch & Educational Review**: Dispatches a simulated Discord event through the Switch dispatcher, runs the PR reviewer, and verifies thread context caching.

### Exit Codes
- `0`: All stages passed successfully.
- `1`: Probe failure in one or more stages.
- `2`: Missing required credentials for live mode probe (aborted safely without failure).

---

## Running the Application

### 1. Setup Virtual Environment
```bash
python -m venv .venv
# Windows:
.\.venv\Scripts\activate
# Linux/macOS:
source .venv/bin/activate

pip install -e .
```

### 2. Run Test Suite
```bash
pytest -v
```

### 3. Start the Local FastAPI Service
```bash
uvicorn src.guardian.main:app --host 0.0.0.0 --port 8000 --reload
```

---

## Security & Execution Guardrails

- **Zero Arbitrary Code Execution**: PR diffs are parsed and analyzed purely via static string and syntax heuristics. Untrusted code submitted in pull requests is never executed, evaluated, or imported.
- **Read-Only GitHub Permissions**: OpenSource Guardian never posts PR comments, modifies branches, or approves/merges PRs directly on GitHub. All feedback is delivered inside the collaborative Switch/Discord chat room.
- **Secret Redaction**: Detected secret tokens, API keys, and credentials are never exposed in log output, console output, review findings, or chat messages.

---

## Project Structure

```text
OpenSource-Guardian/
├── .env.example                # Example configuration template
├── pyproject.toml              # Project dependencies and tool configuration
├── README.md                   # Project documentation and architectural overview
├── docs/                       # Architecture designs and milestone roadmaps
│   ├── ARCHITECTURE.md         # Full system architecture and Switch boundaries
│   └── ROADMAP.md              # Milestone tracking and completion log
├── scripts/
│   └── smoke_test.py           # Multi-stage automated pipeline smoke test
├── src/
│   └── guardian/
│       ├── main.py             # FastAPI entrypoint and health probe
│       ├── adapters/
│       │   ├── github_client.py # Read-only async GitHub REST client
│       │   ├── switch_client.py # Switch Agent Bridge WS + REST adapter
│       │   └── switch_dispatcher.py # Discord event router & thread memory
│       └── modules/
│           ├── onboarding.py   # Repository onboarding summary generator
│           ├── issue_finder.py # Good first issue discovery engine
│           └── pr_reviewer.py  # Diff parser & educational review engine
└── tests/                      # Comprehensive pytest test suite
    ├── test_main.py
    ├── test_github_client.py
    ├── test_modules.py
    ├── test_pr_reviewer.py
    ├── test_switch_client.py
    ├── test_switch_dispatcher.py
    ├── test_e2e_integration.py
    └── test_smoke_test.py
```

---

## Hackathon Milestone Status

- **M0 — Repository Reconnaissance**: Completed
- **M1 — Repository Initialization**: Completed
- **M2 — Architecture & Roadmap Specification**: Completed
- **M3 — Application Foundation & Configuration**: Completed
- **M4 — GitHub Integration Adapter**: Completed
- **M5 — Repository Onboarding & Issue Discovery**: Completed
- **M6 — PR Guardian Reviewer**: Completed
- **M7 — Switch Agent Integration**: Completed
- **M8 — End-to-End Integration & Multi-Agent Collaboration**: Completed
- **M9 — Polish & Hackathon Submission**: Next
