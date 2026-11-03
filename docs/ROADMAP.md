# OpenSource Guardian — Implementation Roadmap

This roadmap defines the sequential, reviewable milestones for developing **OpenSource Guardian** within the 4-day **Flip the Switch Hackathon** timeframe.

Each milestone has clear deliverables and unambiguous acceptance criteria.

---

## Milestone Summary

| Milestone | Title | Focus Area | Status |
| :--- | :--- | :--- | :--- |
| **M0** | Repository Reconnaissance | Inspect environment, GitHub repo, and Switch docs | **Completed** |
| **M1** | Repository Initialization | Git workspace setup, `.gitignore`, initial README | **Completed** |
| **M2** | Architecture Specification | System architecture, boundaries, data flows, roadmap | **In Review** |
| **M3** | Application Foundation | Python environment, `pyproject.toml`, settings, FastAPI skeleton | Next Up |
| **M4** | GitHub Integration | Async GitHub REST API client, unit tests, mock fixtures | Planned |
| **M5** | Onboarding & Issue Discovery | Repository summary & "good first issue" recommendation modules | Planned |
| **M6** | PR Guardian Reviewer | Educational PR diff parsing & structured code review generator | Planned |
| **M7** | Switch Agent Integration | Switch Agent Bridge connection (WebSocket + REST ops) | Planned |
| **M8** | End-to-End Testing | Live testing across Discord, Switch Room, and GitHub API | Planned |
| **M9** | Polish & Hackathon Submission | Documentation, demo recording, presentation artifacts | Planned |

---

## Detailed Milestones & Acceptance Criteria

### M2: Architecture Specification
- **Deliverables**:
  - `docs/ARCHITECTURE.md` (System architecture, component boundaries, data flows, security boundaries, error strategies).
  - `docs/ROADMAP.md` (Milestone definitions and acceptance criteria).
- **Acceptance Criteria**:
  - [x] Clear division between GitHub API, Switch Agent Bridge, and Guardian core.
  - [x] Verified Switch capabilities clearly separated from implementation-stage details.
  - [x] Zero arbitrary code execution and read-only GitHub access constraints documented.
  - [x] Reviewable without modifying application code or creating git commits.

---

### M3: Application Foundation & Configuration
- **Deliverables**:
  - `pyproject.toml` or `requirements.txt` declaring minimal dependencies (`fastapi`, `uvicorn`, `httpx`, `pydantic-settings`, `websockets`, `pytest`, `pytest-asyncio`).
  - `config/settings.py` loading configurations via Pydantic (`SWITCH_API_URL`, `SWITCH_AGENT_ID`, `SWITCH_API_KEY`, `GITHUB_TOKEN`).
  - `.env.example` documenting required configuration variables.
  - Minimal FastAPI application with `/health` endpoint in `src/guardian/main.py`.
- **Acceptance Criteria**:
  - [ ] App starts cleanly without runtime errors when running `python -m src.guardian.main` or `uvicorn`.
  - [ ] `GET /health` returns `200 OK` with service name and status.
  - [ ] Configuration validates missing required variables with helpful error messages.
  - [ ] Unit tests for configuration and health checks pass.

---

### M4: GitHub Integration Adapter
- **Deliverables**:
  - `src/guardian/adapters/github_client.py`: Async GitHub REST client using `httpx`.
  - Methods to fetch repository metadata, files (`README.md`, `CONTRIBUTING.md`), open issues with labels, and pull request diffs.
  - Rate limiting detection and error handling.
  - Unit tests with mock responses in `tests/test_github_client.py`.
- **Acceptance Criteria**:
  - [ ] Client successfully parses repository information, issues, and PR diffs against public GitHub repositories.
  - [ ] GitHub rate limiting (403/429) is caught and transformed into a user-friendly domain exception.
  - [ ] Unit test suite passes without making actual network calls (using pytest mocks/fixtures).

---

### M5: Repository Onboarding & Issue Discovery
- **Deliverables**:
  - `src/guardian/modules/onboarding.py`: Analyzes repository structure, documentation, and tech stacks to generate quick onboarding summaries.
  - `src/guardian/modules/issue_finder.py`: Queries and ranks beginner-friendly issues (`good first issue`, `documentation`), extracting prerequisites and context.
  - Unit tests covering parsing and ranking heuristics.
- **Acceptance Criteria**:
  - [ ] Calling onboarding module on a sample repository returns a clear, structured summary of what the project does and how to run it.
  - [ ] Issue discovery module filters out closed issues and ranks issues by clarity, providing actionable guidance for first-time contributors.
  - [ ] Markdown formatters render clean responses suitable for chat displays (Discord).

---

### M6: PR Guardian (Educational Code Reviewer)
- **Deliverables**:
  - `src/guardian/modules/pr_reviewer.py`: Unified diff analyzer and educational feedback generator.
  - Heuristic checks:
    - Modified lines / diff size assessment.
    - Presence of test file changes alongside feature changes.
    - Documentation sync (e.g. modified APIs matching updated docs).
    - Basic code pattern smells (hardcoded credentials, debug prints).
  - Generates supportive, constructive reviews focused on helping contributors learn.
- **Acceptance Criteria**:
  - [ ] Successfully parses unified git diffs into structured file changes.
  - [ ] Produces a formatted markdown review report highlighting positive contributions and actionable recommendations.
  - [ ] Does not execute untrusted PR code under any circumstance.
  - [ ] Comprehensive unit test suite with sample diff fixtures.

---

### M7: Switch Agent Integration
- **Deliverables**:
  - `src/guardian/adapters/switch_client.py`:
    - WebSocket connection to `switch-core` Agent Bridge (`/agents/{agent_id}/connection/ws`).
    - Periodic ping/pong handler (2-second interval).
    - Event dispatcher matching `@guardian` mentions and commands (`review PR #<n>`, `find issues`, `onboard`).
    - HTTP REST client for Switch operations (`post_message`, `connect_to_room`).
  - Unit tests for message parsing and event routing.
- **Acceptance Criteria**:
  - [ ] Client can connect to a local or remote `switch-core` server using a registered Agent ID and Bearer token.
  - [ ] Automatically handles connection drops and resumes via cursor tracking.
  - [ ] Correctly routes incoming chat commands to the appropriate module (Onboarding, Issue Discovery, or PR Reviewer) and posts responses back to the room.

---

### M8: End-to-End Integration & Multi-Agent Collaboration
- **Deliverables**:
  - Integrated workflow connecting Discord -> Switch Discord Bridge -> Switch Room -> OpenSource Guardian -> GitHub API -> Reply to Discord.
  - Multi-agent interaction test (e.g. OpenSource Guardian collaborating with human maintainers and other Switch agents in the same room).
  - Automated smoke test script verifying the full pipeline.
- **Acceptance Criteria**:
  - [ ] A contributor types `@guardian review PR #X` in a Discord channel bridged to Switch, and Guardian replies with an educational PR review in thread.
  - [ ] A contributor asks for beginner issues, and Guardian provides curated issues with contribution tips.
  - [ ] Maintainers can ask follow-up questions within the same thread.

---

### M9: Polish, Documentation & Hackathon Submission
- **Deliverables**:
  - Updated `README.md` with complete setup instructions, screenshots, and demo scenarios.
  - Video demonstration showing live triage in Discord via Switch.
  - Hackathon submission write-up covering problem statement, Switch integration highlights, architecture, and future vision.
- **Acceptance Criteria**:
  - [ ] Complete documentation with clear reproduction steps for judges.
  - [ ] Clean repository with zero secrets or temporary artifacts committed.
  - [ ] Working demo ready for presentation.
