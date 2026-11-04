"""Discord / Switch chat command dispatcher and event router for OpenSource Guardian."""

from __future__ import annotations

import logging
import re
from typing import Any
from pydantic import BaseModel, ConfigDict, Field
from src.guardian.adapters.github_client import (
    GitHubAuthError,
    GitHubClient,
    GitHubError,
    GitHubNotFoundError,
    GitHubRateLimitError,
)
from src.guardian.adapters.switch_client import SwitchRestClient
from src.guardian.adapters.switch_protocol import DomainEventFrame, MessagePayload
from src.guardian.config import Settings, get_settings
from src.guardian.modules.issue_finder import IssueFinder
from src.guardian.modules.onboarding import RepoOnboarder
from src.guardian.modules.pr_reviewer import PRReviewer, ReviewFinding

logger = logging.getLogger("guardian.adapters.switch_dispatcher")


class ThreadContext(BaseModel):
    """Context state for an ongoing conversation thread."""

    model_config = ConfigDict(extra="ignore")

    thread_id: str = Field(description="Unique thread identifier")
    owner: str = Field(description="Repository owner")
    repo: str = Field(description="Repository name")
    last_action: str = Field(description="Last executed action (e.g. review_pr, find_issues)")
    last_pr_number: int | None = Field(default=None, description="Last reviewed PR number if applicable")
    last_report_markdown: str | None = Field(default=None, description="Last generated report Markdown")
    findings: list[ReviewFinding] = Field(default_factory=list, description="Findings from the last review")
    positive_notes: list[str] = Field(default_factory=list, description="Positive notes from the last review")


class SwitchEventDispatcher:
    """Dispatches incoming Switch room / Discord chat events to Guardian core modules."""

    MAX_THREAD_HISTORY = 100

    MENTION_PATTERN = re.compile(r"(?i)@(?:opensource-guardian|guardian)\b|!guardian\b")

    # Command matching patterns
    PR_REVIEW_PATTERN = re.compile(
        r"(?i)(?:review|check)\s+(?:pull\s*request\s*|pr\s*)?#?\s*(?:([a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+)#)?(\d+)"
    )
    PR_REREVIEW_PATTERN = re.compile(
        r"(?i)\b(?:re-?review|review\s+again|check\s+again|recheck|refresh\s+review|update\s+review)\b"
    )
    FIND_ISSUES_PATTERN = re.compile(
        r"(?i)(?:find|list|show|get|search)?\s*(?:good\s*first\s*issue[s]?|beginner\s*issue[s]?|open\s*issue[s]?|issues)(?:\s+(?:in|for)\s+([a-zA-Z0-9_+#.-]+))?"
    )
    ONBOARD_PATTERN = re.compile(
        r"(?i)\b(?:onboard|repo\s*summary|explain\s*(?:repo|repository|codebase)|(?:repo|codebase)\s*(?:overview|architecture|guide)|intro)\b"
    )
    REPO_SPEC_PATTERN = re.compile(r"\b([a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+)\b")

    # Thread follow-up topic patterns
    TOPIC_TEST_PATTERN = re.compile(r"(?i)\b(?:test|tests|testing|coverage|pytest|unit\s*test)\b")
    TOPIC_SECURITY_PATTERN = re.compile(r"(?i)\b(?:security|secret|token|key|password|credential|leak)\b")
    TOPIC_SUMMARY_PATTERN = re.compile(r"(?i)\b(?:summary|summarize|recap|verdict|recommendation|priority|first)\b")

    def __init__(
        self,
        switch_client: SwitchRestClient,
        github_client: GitHubClient,
        onboarder: RepoOnboarder | None = None,
        issue_finder: IssueFinder | None = None,
        pr_reviewer: PRReviewer | None = None,
        default_repo: str | None = None,
    ) -> None:
        settings: Settings = get_settings()
        self.switch_client = switch_client
        self.github_client = github_client
        self.onboarder = onboarder or RepoOnboarder(github_client=github_client)
        self.issue_finder = issue_finder or IssueFinder(github_client=github_client)
        self.pr_reviewer = pr_reviewer or PRReviewer(github_client=github_client)
        self.default_repo = default_repo or settings.default_repo
        self.thread_contexts: dict[str, ThreadContext] = {}

    def _record_thread_context(
        self,
        thread_id: str,
        owner: str,
        repo: str,
        last_action: str,
        last_pr_number: int | None = None,
        last_report_markdown: str | None = None,
        findings: list[ReviewFinding] | None = None,
        positive_notes: list[str] | None = None,
    ) -> None:
        """Record bounded thread conversation context for follow-up questions."""
        if len(self.thread_contexts) >= self.MAX_THREAD_HISTORY:
            oldest_key = next(iter(self.thread_contexts))
            del self.thread_contexts[oldest_key]

        self.thread_contexts[thread_id] = ThreadContext(
            thread_id=thread_id,
            owner=owner,
            repo=repo,
            last_action=last_action,
            last_pr_number=last_pr_number,
            last_report_markdown=last_report_markdown,
            findings=findings or [],
            positive_notes=positive_notes or [],
        )

    def is_addressed(self, body: str, addressed_flag: bool = False) -> bool:
        """Determine whether the message was intended for Guardian."""
        if addressed_flag:
            return True
        return bool(self.MENTION_PATTERN.search(body))

    def _extract_repo_and_clean_text(self, body: str) -> tuple[str, str, str]:
        """Strip mention prefixes and extract (owner, repo, cleaned_prompt)."""
        cleaned = self.MENTION_PATTERN.sub("", body).strip()

        # Check if an explicit owner/repo was specified in the text
        repo_match = self.REPO_SPEC_PATTERN.search(cleaned)
        if repo_match:
            spec = repo_match.group(1)
            parts = spec.split("/")
            if len(parts) == 2 and parts[0] and parts[1]:
                return parts[0], parts[1], cleaned

        # Fallback to default configured repo
        default_parts = self.default_repo.split("/")
        if len(default_parts) == 2:
            return default_parts[0], default_parts[1], cleaned

        return "aadesh-2006", "OpenSource-Guardian", cleaned

    def parse_command(
        self,
        body: str,
        addressed_flag: bool = False,
        thread_id: str | None = None,
    ) -> tuple[str, dict[str, Any]] | None:
        """Parse clean text into a structured command tuple: (command_name, params)."""
        if not self.is_addressed(body, addressed_flag):
            return None

        owner, repo, prompt = self._extract_repo_and_clean_text(body)
        thread_ctx = self.thread_contexts.get(thread_id) if thread_id else None

        # 1. PR Review Command (explicit PR number)
        pr_match = self.PR_REVIEW_PATTERN.search(prompt)
        if pr_match:
            explicit_repo_part = pr_match.group(1)
            pr_num_str = pr_match.group(2)
            if explicit_repo_part:
                parts = explicit_repo_part.split("/")
                if len(parts) == 2:
                    owner, repo = parts[0], parts[1]
            return "review_pr", {"owner": owner, "repo": repo, "pr_number": int(pr_num_str)}

        # 2. Contextual Re-review in an existing PR thread
        if thread_ctx and thread_ctx.last_pr_number and self.PR_REREVIEW_PATTERN.search(prompt):
            return "review_pr", {
                "owner": thread_ctx.owner,
                "repo": thread_ctx.repo,
                "pr_number": thread_ctx.last_pr_number,
            }

        # 3. Contextual Thread Follow-up Questions
        if thread_ctx and thread_ctx.last_action == "review_pr" and thread_ctx.last_pr_number:
            if self.TOPIC_TEST_PATTERN.search(prompt):
                return "followup_test", {"context": thread_ctx, "prompt": prompt}
            if self.TOPIC_SECURITY_PATTERN.search(prompt):
                return "followup_security", {"context": thread_ctx, "prompt": prompt}
            if self.TOPIC_SUMMARY_PATTERN.search(prompt):
                return "followup_summary", {"context": thread_ctx, "prompt": prompt}
            # General follow-up inquiry about the PR under discussion
            if any(prompt.lower().startswith(q) for q in ("what", "why", "how", "can", "explain", "is", "tell", "should")):
                return "followup_general", {"context": thread_ctx, "prompt": prompt}

        # 4. Issue Discovery Command
        issue_match = self.FIND_ISSUES_PATTERN.search(prompt)
        if issue_match and any(keyword in prompt.lower() for keyword in ("issue", "issues")):
            language = issue_match.group(1)
            return "find_issues", {"owner": owner, "repo": repo, "language": language}

        # 5. Repository Onboarding Command
        if self.ONBOARD_PATTERN.search(prompt):
            return "onboard", {"owner": owner, "repo": repo}

        # 6. Fallback / Help Command
        return "help", {"owner": owner, "repo": repo, "prompt": prompt}

    async def handle_message(self, message: MessagePayload, room_id: str) -> str | None:
        """Process incoming chat message, execute requested action, and post reply to room."""
        # Loop avoidance: ignore messages sent by Guardian itself
        if self.switch_client.agent_id and self.switch_client.agent_id in message.sender:
            return None
        if "guardian" in message.sender_name.lower():
            return None

        parsed = self.parse_command(message.body, message.addressed, message.thread_id)
        if parsed is None:
            return None

        cmd, params = parsed
        reply_content: str

        try:
            if cmd == "review_pr":
                owner, repo, pr_number = params["owner"], params["repo"], params["pr_number"]
                logger.info("Executing PR review for %s/%s #%d", owner, repo, pr_number)
                report = await self.pr_reviewer.review_pr(owner=owner, repo=repo, pr_number=pr_number)
                reply_content = report.formatted_markdown

                if message.thread_id:
                    self._record_thread_context(
                        thread_id=message.thread_id,
                        owner=owner,
                        repo=repo,
                        last_action="review_pr",
                        last_pr_number=pr_number,
                        last_report_markdown=report.formatted_markdown,
                        findings=report.findings,
                        positive_notes=report.positive_notes,
                    )

            elif cmd == "followup_test":
                ctx: ThreadContext = params["context"]
                reply_content = self._format_followup_test_markdown(ctx)

            elif cmd == "followup_security":
                ctx = params["context"]
                reply_content = self._format_followup_security_markdown(ctx)

            elif cmd == "followup_summary":
                ctx = params["context"]
                reply_content = self._format_followup_summary_markdown(ctx)

            elif cmd == "followup_general":
                ctx = params["context"]
                reply_content = self._format_followup_general_markdown(ctx, params["prompt"])

            elif cmd == "find_issues":
                owner, repo, language = params["owner"], params["repo"], params.get("language")
                logger.info("Discovering issues for %s/%s (lang=%s)", owner, repo, language)
                discovery_report = await self.issue_finder.find_good_first_issues(
                    owner=owner, repo=repo, language=language
                )
                reply_content = self._format_issues_markdown(discovery_report, owner, repo)

                if message.thread_id:
                    self._record_thread_context(
                        thread_id=message.thread_id,
                        owner=owner,
                        repo=repo,
                        last_action="find_issues",
                    )

            elif cmd == "onboard":
                owner, repo = params["owner"], params["repo"]
                logger.info("Running onboarding summary for %s/%s", owner, repo)
                onboard_report = await self.onboarder.onboard(owner=owner, repo=repo)
                reply_content = self._format_onboarding_markdown(onboard_report)

                if message.thread_id:
                    self._record_thread_context(
                        thread_id=message.thread_id,
                        owner=owner,
                        repo=repo,
                        last_action="onboard",
                    )

            else:  # help
                reply_content = self._format_help_markdown(params["owner"], params["repo"])

        except GitHubNotFoundError as err:
            reply_content = f"🔍 **Not Found**: {err}. Please verify the repository name and issue/PR number."
        except GitHubRateLimitError as err:
            reply_content = f"⏳ **GitHub Rate Limit Reached**: {err}. Please try again once the window resets."
        except GitHubAuthError:
            reply_content = "🔒 **GitHub Authentication Error**: Please ensure a valid GITHUB_TOKEN is configured."
        except GitHubError as err:
            reply_content = f"⚠️ **GitHub Error**: An error occurred while communicating with GitHub: {err}"
        except Exception as err:
            logger.error("Unexpected error executing Guardian command '%s': %s", cmd, err, exc_info=True)
            reply_content = f"⚠️ **Internal Error**: OpenSource Guardian encountered an unexpected error: {err}"

        # Post reply back to Switch room (in thread if applicable)
        await self.switch_client.post_message(
            room_id=room_id,
            content=reply_content,
            thread_id=message.thread_id,
        )
        return reply_content

    async def dispatch_event(self, frame: DomainEventFrame) -> None:
        """Top-level handler for DomainEventFrames received over the WebSocket."""
        if frame.data.type == "message" and isinstance(frame.data.payload, MessagePayload):
            await self.handle_message(frame.data.payload, frame.data.room_id)

    # -----------------------------------------------------------------------
    # Follow-up Formatters for Thread Context
    # -----------------------------------------------------------------------

    def _format_followup_test_markdown(self, ctx: ThreadContext) -> str:
        """Format an educational answer regarding testing for the active PR."""
        test_findings = [f for f in ctx.findings if f.category == "TESTING"]
        lines = [f"### 🧪 Test Status for PR #{ctx.last_pr_number} (`{ctx.owner}/{ctx.repo}`)", ""]
        if test_findings:
            lines.append("⚠️ **Observations on Testing**:")
            for f in test_findings:
                lines.append(f"- **{f.message}**")
                lines.append(f"  *Recommendation*: {f.suggestion}")
        else:
            lines.append("✅ **Test Coverage Looks Good!**")
            lines.append(
                "No testing deficiencies were flagged. Automated test files were either updated alongside "
                "the source changes, or the pull request touches only non-executable documentation/configuration."
            )
        return "\n".join(lines)

    def _format_followup_security_markdown(self, ctx: ThreadContext) -> str:
        """Format an educational answer regarding security findings for the active PR."""
        sec_findings = [f for f in ctx.findings if f.category == "SECURITY"]
        lines = [f"### 🛡️ Security Status for PR #{ctx.last_pr_number} (`{ctx.owner}/{ctx.repo}`)", ""]
        if sec_findings:
            lines.append("🚨 **Critical Security Concerns Detected**:")
            for f in sec_findings:
                loc = f"`{f.file_path}:{f.line_number}`" if f.file_path and f.line_number else (f"`{f.file_path}`" if f.file_path else "General")
                lines.append(f"- **[{f.severity}]** {loc}: {f.message}")
                lines.append(f"  *Action*: {f.suggestion}")
            lines.append("")
            lines.append("> [!CAUTION]")
            lines.append("> Any committed credentials or private tokens must be immediately revoked and rotated.")
        else:
            lines.append("✅ **No Security Secrets Detected!**")
            lines.append("No obvious hardcoded tokens, AWS credentials, or private cryptographic keys were found in the diff.")
        return "\n".join(lines)

    def _format_followup_summary_markdown(self, ctx: ThreadContext) -> str:
        """Format a concise maintainer recap for the active PR."""
        lines = [
            f"### 📋 Review Summary for PR #{ctx.last_pr_number} (`{ctx.owner}/{ctx.repo}`)",
            "",
            f"- **Total Findings**: {len(ctx.findings)} finding(s)",
        ]
        if ctx.positive_notes:
            lines.append("- **Positive Practices**: " + "; ".join(ctx.positive_notes[:2]))
        if ctx.findings:
            severities = [f.severity for f in ctx.findings]
            lines.append(f"- **Severity Breakdown**: {severities.count('CRITICAL')} Critical, {severities.count('WARNING')} Warning, {severities.count('INFO')} Info")
            lines.append(f"- **Top Priority**: {ctx.findings[0].message}")
        else:
            lines.append("- **Verdict**: Changes are clean, compact, and ready for maintainer review.")
        lines.append("")
        lines.append("*Tip: Type `@guardian review again` anytime new commits are pushed to re-run analysis.*")
        return "\n".join(lines)

    def _format_followup_general_markdown(self, ctx: ThreadContext, prompt: str) -> str:
        """Provide bounded educational context for general follow-up questions."""
        lines = [
            f"### 💬 Thread Follow-up: PR #{ctx.last_pr_number} (`{ctx.owner}/{ctx.repo}`)",
            "",
            f"Regarding your question (`\"{prompt[:60]}\"`):",
            f"As a static heuristic reviewer, I analyzed PR #{ctx.last_pr_number} without executing repository code. "
            f"There are currently **{len(ctx.findings)}** active review finding(s) in this thread.",
            "",
            "**Available Follow-up Actions**:",
            f"- Ask `@guardian what tests are missing?` for test advice.",
            f"- Ask `@guardian is this secure?` for credential inspection.",
            f"- Say `@guardian review again` after pushing new changes.",
        ]
        return "\n".join(lines)

    # -----------------------------------------------------------------------
    # Markdown Formatters for Chat Display
    # -----------------------------------------------------------------------

    def _format_issues_markdown(self, report: Any, owner: str, repo: str) -> str:
        """Format issue discovery results into a concise Discord/Chat message."""
        lines = [f"## 🎯 Good First Issues for `{owner}/{repo}`", ""]
        issues = getattr(report, "ranked_issues", getattr(report, "issues", []))
        if not issues:
            lines.append("No open beginner-friendly issues currently found. Check back later or open a discussion!")
            return "\n".join(lines)

        for issue in issues[:5]:
            labels_str = " ".join(f"`{lbl}`" for lbl in issue.labels[:3])
            score = getattr(issue, "suitability_score", getattr(issue, "score", 0))
            lines.append(f"- **[#{issue.number} {issue.title}]({issue.html_url})** (Score: {score})")
            if labels_str:
                lines.append(f"  *Labels*: {labels_str}")
            mentor_tip = getattr(issue, "mentor_tip", None)
            if mentor_tip:
                lines.append(f"  💡 *Tip*: {mentor_tip}")
            elif getattr(issue, "score_reasons", None):
                reasons = ", ".join(issue.score_reasons[:2])
                lines.append(f"  💡 *Signals*: {reasons}")
            lines.append("")
        return "\n".join(lines)

    def _format_onboarding_markdown(self, report: Any) -> str:
        """Format onboarding report into an educational chat guide."""
        display_name = getattr(report, "full_name", report.repo_name)
        lines = [
            f"## 🚀 Welcome to `{display_name}`",
            "",
            f"**Description**: {report.description or 'No description provided.'}",
            f"**Default Branch**: `{report.default_branch}` | **Language**: {report.primary_language or 'Not specified'}",
            "",
        ]
        if report.readme_summary:
            lines.append("### 📖 About the Project")
            lines.append(report.readme_summary)
            lines.append("")

        if getattr(report, "setup_instructions", None):
            lines.append("### ⚙️ Getting Started & Setup")
            lines.append(report.setup_instructions)
            lines.append("")

        if getattr(report, "contribution_guidelines", None):
            lines.append("### 🤝 Contribution Guidelines")
            lines.append(report.contribution_guidelines)
            lines.append("")

        return "\n".join(lines)

    def _format_help_markdown(self, owner: str, repo: str) -> str:
        """Format helpful usage instructions for contributors and maintainers."""
        return (
            "## 🛡️ OpenSource Guardian — Available Commands\n\n"
            f"Currently serving repository: `{owner}/{repo}`\n\n"
            "- `@guardian review PR #<number>` — Perform an educational, constructive static code review.\n"
            "- `@guardian find issues [in <language>]` — Discover curated good-first-issues for newcomers.\n"
            "- `@guardian onboard` — Get an architectural overview and setup instructions for this codebase.\n"
            "- `@guardian help` — Show this command directory.\n"
        )
