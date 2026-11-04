# OpenSource Guardian — Flip the Switch Hackathon Submission

> **Intelligent open-source repository governance, automated educational triage, and multi-agent collaboration powered by Switch AI.**

---

## 1. Project Title & One-Line Pitch

**OpenSource Guardian**: A pedagogical AI teammate and triage custodian that bridges GitHub repository activities with real-time, human-in-the-loop Switch rooms and Discord channels to educate contributors and unburden maintainers.

---

## 2. Problem Statement

Open-source sustainability faces a pervasive human bottleneck:

- **New Contributor Intimidation**: Newcomers eager to contribute are confronted with monolithic codebases, unclear setup requirements, and fragmented documentation. Getting to a working local dev environment often requires trial-and-error that burns initial enthusiasm.
- **The "Good First Issue" Dilemma**: Issues labeled `good first issue` are frequently neglected, claim-abandoned without assignment, or secretly entail deep domain dependencies. Beginners pick up issues they cannot finish and get stranded.
- **Impersonal & Cryptic PR Reviews**: When contributors submit pull requests, they often meet sterile automated CI failure messages or silence from overloaded maintainers. Traditional bots leave disconnected, robotic comments on GitHub PRs that criticize code without explaining *why* a particular design or test is required.

Maintainers want to mentor, but lack the hours; contributors want to learn, but lack accessible guidance.

---

## 3. Target Users

1. **First-Time & Growing Contributors**: Developers seeking clear onboarding paths, curated entry-level tasks, and constructive code feedback that teaches best practices rather than just rejecting diffs.
2. **Open-Source Maintainers**: Project leads who need to reduce triage overhead, ensure pull requests meet test and security baselines, and welcome newcomers without burning out.
3. **Engineering Teams & Community Organizers**: Communities that use collaborative chat platforms (such as Discord) to coordinate open-source projects with human-in-the-loop governance.

---

## 4. Solution & Core Workflows

OpenSource Guardian operates directly where developer communities converse — inside **Discord** channels and threads bridged to **Switch AI** rooms. Rather than acting as an isolated script posting on GitHub, Guardian participates as an interactive peer in chat:

### Core Capabilities:
- **Repository Onboarding (`RepoOnboarder`)**:
  - Automatically fetches and parses repository documentation (`README.md`, `CONTRIBUTING.md`, architectural specifications, and project metadata).
  - Synthesizes clear, structured onboarding briefings covering what the project does, key architectural layers, and exact local setup instructions.
- **Beginner Issue Discovery (`IssueFinder`)**:
  - Queries open repository issues, filters out pull requests, and analyzes issue titles, descriptions, and labels.
  - Ranks beginner-friendly issues deterministically based on description clarity, prerequisite availability, and setup guidance.
- **Pedagogical PR Review (`PRReviewer`)**:
  - Ingests raw GitHub unified diffs and parses them into typed file modifications and hunks without executing repository code.
  - Runs educational heuristics: diff size assessment, test accompaniment, documentation synchronization, secret credential detection, and leftover debug statements.
  - Highlights positive contributions first, followed by clear, actionable explanations of why changes are recommended.
- **Conversational Thread Memory (`ThreadContext`)**:
  - Maintains in-memory thread state associating Discord conversation threads with specific PR reviews and repository contexts.
  - Enables natural follow-ups: contributors can ask `@guardian what tests are missing?` or `@guardian is there any security concern?` without repeating the PR number.

---

## 5. Why Switch AI is Central to the Solution

Traditional GitHub bots operate in a closed feedback loop: a GitHub webhook triggers a serverless action, which posts a standalone comment on the pull request. This approach suffers from critical limitations:

1. **Isolation from Community Discussion**: Architectural questions and mentorship happen in chat platforms like Discord or Slack, not in noisy GitHub PR notification threads.
2. **Lack of Multi-Agent Collaboration**: Real-world triage requires multiple specialized tools (CI analyzers, policy verifiers, documentation assistants). Switch provides a shared room and message bus where multiple agents collaborate alongside human maintainers.
3. **Unified Protocol**: Switch’s Agent Bridge protocol provides standard WebSocket streaming, heartbeat keep-alives, sequence cursor resumption, and normalized event frames across diverse messaging channels.

By integrating with **Switch AI**, OpenSource Guardian becomes an accessible collaborator in chat, bringing GitHub repository intelligence directly to the community table.

---

## 6. Technical Architecture

The system consists of five distinct layers:

```
[ Discord Community Channel / Bridged Thread ]
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

1. **Chat Ingestion**: Discord messages are received by the Switch Discord Bridge and forwarded into a Switch room as domain event frames (`type: "message"` or `"chat_message"`).
2. **Agent Gateway (`SwitchClient`)**: Maintains an asynchronous WebSocket connection to `/agents/{agent_id}/connection/ws`, replying to 2-second heartbeat pings with immediate pongs and recovering after disconnects.
3. **Dispatch & Multi-Agent Safeguards (`SwitchEventDispatcher`)**: Normalizes message payloads, suppresses self-messages to avoid loops, ignores unrelated third-party agent chatter, and routes recognized commands.
4. **Analysis Engines (`guardian/modules`)**:
   - `onboarding.py`: Gathers markdown files from GitHub and structures onboarding briefings.
   - `issue_finder.py`: Discovers and scores `good first issue` candidates.
   - `pr_reviewer.py`: Tokenizes and parses git unified diffs, running rule-based heuristics.
5. **Read-Only GitHub Client (`GitHubClient`)**: Queries repository metadata, file contents, open issues, and PR diffs with rate-limit handling and zero write permissions.

---

## 7. Switch Integration Highlights

- **Standard Switch Protocol Adherence**: Built directly against Switch specifications with typed Pydantic models for control frames (`ping`, `pong`, `connection_state`, `evicted`, `refused`) and domain events (`DomainEventFrame`, `DomainEventData`, `MessagePayload`).
- **Resilient Connection Lifecycle**: Automatically initiates WebSocket handshakes with required Authorization bearer tokens, tracks event cursors, and processes disconnect/resume lifecycles.
- **REST Operations (`SwitchRestClient`)**: Posts responses directly back to Switch rooms using the standard endpoint `POST /agents/{agent_id}/ops/post_message`, properly binding messages to parent Discord threads (`thread_id`).
- **Multi-Agent Room Harmony**: Evaluated under simulated scenarios where a human maintainer, a third-party CI agent, and OpenSource Guardian share a single room. Guardian only acts when addressed and sanitizes outbound replies to prevent recursive agent loops.

---

## 8. Safety & Reliability Decisions

Security and deterministic behavior were foundational architectural constraints:

1. **Zero Arbitrary Code Execution**: OpenSource Guardian never runs, evaluates, or imports untrusted code from pull requests. All diff analysis is performed statically via string parsing, hunk boundary detection, and regular expressions.
2. **Read-Only GitHub Permissions**: The GitHub adapter requires only read permissions. OpenSource Guardian never directly leaves comments on GitHub PRs, modifies git refs, or merges pull requests. All guidance remains in the human-in-the-loop chat room.
3. **Strict Credential Redaction**: Secret detection heuristics inspect added lines in diffs for GitHub PATs, AWS access keys, SSH private keys, and generic auth tokens. Any detected credentials are automatically masked; raw secret strings are never logged, formatted into reports, or transmitted to chat.
4. **Graceful Degeneration & Rate-Limit Handling**: GitHub 403/429 rate limit responses and 404 resource errors are mapped to friendly user notices rather than unhandled service crashes.

---

## 9. What is Implemented & Verified

- **Full Pytest Test Suite**: **78 passing tests** across 10 test modules covering configuration, health endpoints, GitHub REST operations, onboarding heuristics, issue discovery, unified diff parsing, secret masking, Switch protocol frames, WebSocket connection lifecycle, event dispatching, thread context memory, and end-to-end integration workflows.
- **Automated Smoke Test (`scripts/smoke_test.py`)**:
  - Mock Mode (`--mock`): Validates all 5 stages (Configuration, ASGI Health Check, GitHub Client Contract, Switch REST Operation, and Event Dispatching) offline with 100% pass rate.
  - Live Mode Guard: Detects missing credentials safely, logs requirements without exposing secrets, and exits with code `2`.
- **FastAPI ASGI Health Service**: Standalone service providing `GET /health` responding with service name and status.
- **Thread Context Memory**: In-memory FIFO cache supporting up to 100 active conversation threads for multi-turn follow-ups.

---

## 10. What Remains Unverified or Future Work

- **Live Switch & Discord Server Verification**:
  - Live interaction with a running `switch-core` instance and live Discord server was not verified during development due to the absence of external Switch cluster credentials and bot tokens in the local test environment.
  - All Switch protocol contracts, WebSocket lifecycles, and REST operations were instead verified against specification-compliant mock transports.
- **Persistent Storage for Thread Memory**:
  - Active thread contexts are currently stored in-memory and will reset upon service restart. Future iterations can back this state with PostgreSQL or Redis.
- **Semantic Code Understanding**:
  - Current review heuristics are static and syntactic. Integrating language-server or AST-based semantic analysis would allow cross-file symbol resolution and type-checking insights.

---

## 11. Demo Walkthrough

### Scenario 1: Onboarding a New Contributor
- **Contributor in Discord**: `@guardian onboard`
- **Guardian Reply**: Provides an executive briefing of the repository, key modules (`adapters`, `modules`, `config`), and instructions for virtual environment setup and testing.

### Scenario 2: Finding a Beginner-Friendly Issue
- **Contributor in Discord**: `@guardian find good first issues`
- **Guardian Reply**: Lists curated issues ranked by description clarity, highlighting prerequisites and suggested starting files.

### Scenario 3: Reviewing a Pull Request with Educational Feedback
- **Contributor in Discord**: `@guardian review PR #42`
- **Guardian Reply**:
  - Acknowledges positive changes: clean module structure and small diff size.
  - Flags missing unit tests for newly added payment processing logic.
  - Explains *why* testing edge cases (e.g. negative amounts) protects repository integrity.

### Scenario 4: Contextual Thread Follow-Up
- **Maintainer in Discord Thread**: `@guardian what tests are missing?`
- **Guardian Reply**: Reads from thread memory context and provides targeted recommendations for test cases covering negative inputs and boundary conditions.

---

## 12. Future Vision

OpenSource Guardian demonstrates how AI can foster healthier open-source communities. The future roadmap includes:
- **Interactive Mentorship Sandboxes**: Generating guided, interactive reproduction steps for reported issues.
- **Multi-Repository Federation**: Allowing maintainers of multiple sibling repositories to oversee cross-repo contributions in a centralized Switch operations room.
- **Automated Contributor Appreciation**: Celebrating milestone contributions and highlighting contributor growth over time.
