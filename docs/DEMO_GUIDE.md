# OpenSource Guardian — Demo & Reproduction Guide

> Comprehensive walkthrough, judge reproduction steps, and presentation guide for **OpenSource Guardian**.

---

## 1. Demo Narrative & Executive Summary

OpenSource Guardian demonstrates how an AI teammate, integrated through **Switch AI** and bridged to **Discord**, transforms open-source repository triage into an educational, welcoming experience.

### Suggested Demo Duration
**3 to 5 minutes**

### Narrative Arc
1. **The Arrival (Onboarding)**: A new contributor joins the Discord channel and uses `@guardian onboard` to immediately grasp project architecture and local setup without digging through fragmented documentation.
2. **Finding the First Contribution (Issue Discovery)**: The contributor requests beginner-friendly tasks with `@guardian find good first issues`. Guardian recommends curated issues ranked by clarity, explaining required prerequisites and starting files.
3. **The First Pull Request (Educational Review)**: The contributor submits a pull request and asks `@guardian review PR #42`. Instead of cold automated criticism, Guardian congratulates them on good architecture, flags missing tests, explains *why* edge cases matter, and ensures no credentials were leaked.
4. **The Mentorship Dialogue (Thread Follow-Up)**: The maintainer jumps into the Discord thread and asks `@guardian what tests are missing?`. Guardian uses thread memory to give specific unit test recommendations.
5. **Team Harmony (Multi-Agent Collaboration)**: A third-party CI agent posts in the room. Guardian ignores it, avoiding infinite loops while collaborating seamlessly in the shared space.

---

## 2. Prerequisites & Environment Setup

### Judge Reproduction Prerequisites
- **Python**: 3.11, 3.12, or 3.13 installed
- **Git**: Installed
- **Terminal**: Bash, PowerShell, or zsh

### 1-Minute Setup
```bash
# 1. Clone repository
git clone https://github.com/aadesh-2006/OpenSource-Guardian.git
cd OpenSource-Guardian

# 2. Create and activate virtual environment
python -m venv .venv

# Windows (PowerShell):
.\.venv\Scripts\Activate.ps1
# Linux / macOS:
source .venv/bin/activate

# 3. Install in editable mode
pip install -e .

# 4. Copy configuration
cp .env.example .env
```

---

## 3. Judge Reproduction Paths

We provide two clear paths for judges:
- **Path A (Instant Offline Verification)**: Uses contract dry-run and comprehensive test suites (zero external dependencies required).
- **Path B (Live Verification)**: Probes live Switch and GitHub services if external credentials are provided.

---

### Path A — Instant Offline Verification (Recommended)

#### Step 1: Run Full Pytest Suite (78 Tests)
Verify that all system components pass validation:
```bash
pytest -v
```
**Expected Outcome**:
`78 passed, 1 warning` in ~15-20 seconds. (The Starlette warning is standard for httpx-based FastAPI test clients).

#### Step 2: Run Automated 5-Stage Smoke Test
Run the end-to-end integration pipeline in contract mock mode:
```bash
python scripts/smoke_test.py --mock
```
**Expected Outcome**:
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

#### Step 3: Run the End-to-End Test Suite Specifically
Inspect the exact interaction scenarios executed against mock Switch and GitHub protocols:
```bash
pytest tests/test_e2e_integration.py -v
```
**Expected Outcome**:
- `test_e2e_contributor_pr_review_workflow` PASSED
- `test_e2e_contributor_issue_discovery_workflow` PASSED
- `test_e2e_maintainer_followups_in_same_thread` PASSED
- `test_e2e_multi_agent_collaboration_and_loop_prevention` PASSED
- `test_e2e_resilience_not_found_handling` PASSED

---

### Path B — Live Verification (With Live Switch Cluster)

If you have a live `switch-core` instance and Discord bridge configured:

1. Configure `.env`:
   ```ini
   SWITCH_API_URL=http://your-switch-server:8080
   SWITCH_AGENT_ID=your-registered-agent-id
   SWITCH_API_KEY=your-bearer-api-key
   SWITCH_ROOMS=general
   GITHUB_TOKEN=your-github-token
   ```
2. Run the live pipeline smoke test:
   ```bash
   python scripts/smoke_test.py
   ```
3. Start the FastAPI service:
   ```bash
   uvicorn src.guardian.main:app --host 0.0.0.0 --port 8000
   ```

---

## 4. Detailed Scenario Walkthroughs

### Scenario 1: Educational PR Review Workflow

**Input in Discord**:
> `@guardian review PR #42`

**System Action**:
1. Discord Collaboration Bridge delivers `DomainEventFrame(type="message")` with message content and thread root ID.
2. `SwitchEventDispatcher` recognizes the `@guardian` mention and extracts PR number `42`.
3. `GitHubClient` fetches PR metadata and raw diff text via HTTPS.
4. `PRReviewer` parses hunks into `FileDiff` structures without code execution.
5. Static heuristics evaluate diff size, test additions, documentation updates, and secrets.
6. `SwitchRestClient` posts Markdown report back to the room and thread.

**Expected Markdown Output Delivered in Discord**:
```markdown
### 🛡️ PR Guardian Review — #42: Add payment processing core

**Status**: ⚠️ **Needs Attention**
**Summary**: 2 files changed (+14, -0 lines).

#### 🌟 Positive Highlights
- **Focused Scope**: Well-contained diff (+14 lines) makes this PR straightforward to review.
- **Clean Architecture**: Good separation between core service and test fixtures.

#### 💡 Recommendations & Educational Feedback
- **Missing Test Coverage**: Added `CorePaymentService.process` with logic branching for negative amounts, but negative amount assertion is missing edge cases (e.g. `amount == 0`).
  *Why this matters*: In financial workflows, boundary values (0 and negative numbers) are common sources of silent regressions. Adding dedicated test cases protects system stability.

#### 🔒 Security & Code Hygiene
- No hardcoded secrets or credentials detected.
- No debug print statements or leftover breakpoints found.
```

---

### Scenario 2: Conversational Thread Follow-Up

**Context**: In the thread spawned by Scenario 1, the maintainer or contributor asks a follow-up question.

**Input in Thread**:
> `@guardian what tests are missing?`

**System Action**:
1. `SwitchEventDispatcher` identifies that the incoming message is inside an active thread (`thread_id="thread-42"`).
2. It retrieves `ThreadContext` from the in-memory cache without requiring a new PR fetch.
3. Recognizes the question intent matches `TOPIC_TEST_PATTERN`.
4. Synthesizes a focused reply from stored findings.

**Expected Output in Thread**:
```markdown
📋 **Test Accompaniment Breakdown for PR #42**:

The following areas require additional test coverage before merge:
1. `src/service.py`: Verify behavior when `amount == 0`.
2. Ensure assertions test both successful and rejected payment states.

*Tip: Adding unit tests directly inside `tests/test_service.py` ensures CI will catch future regressions.*
```

---

### Scenario 3: Beginner Issue Discovery

**Input in Discord**:
> `@guardian find good first issues`

**System Action**:
1. Dispatcher routes to `IssueFinder.find_good_first_issues()`.
2. GitHub client queries open issues labeled `good first issue` or `beginner`.
3. Engine scores issues by clarity, presence of reproduction steps, and required prerequisites.
4. Formats a curated guide for the contributor.

**Expected Output in Discord**:
```markdown
### 🌟 Curated Beginner Issues for First-Time Contributors

Here are the top-ranked beginner-friendly issues to get started:

1. **#15: Improve CLI error message formatting**
   - **Labels**: `good first issue`, `documentation`
   - **Prerequisites**: Basic Python string formatting
   - **Getting Started**: Check `src/guardian/main.py` where CLI flags are parsed.
   - **Link**: https://github.com/aadesh-2006/OpenSource-Guardian/issues/15

*Feel free to ask questions in this thread once you start working on one!*
```

---

### Scenario 4: Multi-Agent Collaboration & Loop Prevention

**Scenario**:
1. Human maintainer (`@sarah-maintainer`) asks another bot: `@ci-helper-agent run lint checks`.
2. Third-party bot responds in the room: `Lint checks completed with 0 errors.`
3. **Guardian Behavior**: Ignored. Guardian does not reply to unaddressed room messages.
4. Human asks Guardian: `@guardian review PR #42`.
5. Guardian posts review. In its reply, Guardian does not mention `@guardian`, preventing infinite ping-pong loops between automated agents.

---

## 5. Live vs. Simulated Status Disclosure

To ensure complete transparency during hackathon evaluation:

| Feature | Verified via Automated Tests | Verified with Live Servers |
| :--- | :---: | :---: |
| GitHub Client Read-Only Operations | **YES** (Mock & Live PAT) | **YES** (with public GitHub) |
| Unified Diff Parsing & Static Heuristics | **YES** | **YES** |
| Secret Detection & Redaction | **YES** | **YES** |
| Switch WebSocket Frame Parsing & Heartbeats | **YES** (Mock transport) | *Unverified (No local Switch)* |
| Switch REST Operations (`post_message`) | **YES** (Mock transport) | *Unverified (No local Switch)* |
| Discord Collaboration Bridge Ingestion | **YES** (E2E simulation) | *Unverified (No Discord bot token)* |
| Thread Context Caching (100 Entries FIFO) | **YES** | **YES** |
| Multi-Agent Loop Prevention | **YES** | **YES** |

---

## 6. Video Recording Script & Shot List

Because live Switch cluster and Discord bot tokens were not present in the local environment, no pre-recorded video or fake screenshots were fabricated. Instead, here is the complete recording script and shot list for community teams or judges recording a live presentation:

### Shot List (3-Minute Presentation)
- **Shot 1 (0:00 - 0:45)**: *Problem Overview & Slide/Diagram*
  - Show the Mermaid architecture diagram from `README.md`.
  - Explain the open-source contributor barrier and the need for pedagogical AI.
- **Shot 2 (0:45 - 1:30)**: *Discord Ingestion & Repository Onboarding*
  - In Discord channel, type `@guardian onboard`.
  - Show Guardian's structured response highlighting repository layers and setup steps.
- **Shot 3 (1:30 - 2:30)**: *Pull Request Review & Pedagogical Feedback*
  - In Discord channel, type `@guardian review PR #42`.
  - Show the educational Markdown report highlighting positive contributions and actionable test recommendations.
- **Shot 4 (2:30 - 3:00)**: *Thread Follow-Up & Multi-Agent Collaboration*
  - Reply in the thread: `@guardian what tests are missing?`.
  - Show the context-aware reply generated from in-memory thread memory.
  - Conclude with architecture and hackathon submission highlights.

---

## 7. Screenshot Capture Checklist (For Live Deployments)

When deploying to a live Discord community connected to Switch:
- [ ] `shot1_discord_onboard.png`: Contributor typing `@guardian onboard` and Guardian's response.
- [ ] `shot2_discord_good_first_issues.png`: Contributor typing `@guardian find good first issues` with curated cards.
- [ ] `shot3_discord_pr_review.png`: Full educational review rendered inside a Discord channel.
- [ ] `shot4_discord_thread_followup.png`: Follow-up discussion inside the Discord review thread.
- [ ] `shot5_terminal_smoke_test.png`: Terminal output running `python scripts/smoke_test.py --mock` with 5/5 passed.
