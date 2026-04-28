#!/usr/bin/env python3
"""Render Claude Code transcripts to redacted Markdown for transcripts/.

Dev script. Run from the repo root:

    uv run --project plugins/gepa-research python scripts/render_transcripts.py render
    uv run --project plugins/gepa-research python scripts/render_transcripts.py render-one cdd453e0
"""

from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Iterator

import typer
import yaml

app = typer.Typer(no_args_is_help=False, add_completion=False)

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SOURCE_ROOT = Path.home() / ".claude" / "projects"
DEFAULT_OUTPUT_ROOT = REPO_ROOT / "transcripts"
DEFAULT_SKILLS_ROOT = Path.home() / ".claude" / "skills"


# ---------------------------------------------------------------------------
# Curated session manifest
# ---------------------------------------------------------------------------


@dataclass
class SessionSpec:
    session_id: str
    workspace_dir: str
    output_relpath: str
    title: str
    summary: str
    workspace: str
    date: str  # YYYY-MM-DD in user's local time


SESSIONS: list[SessionSpec] = [
    # --- 2026-04-20: build day -------------------------------------------------
    SessionSpec(
        session_id="cdd453e0-f2bf-4f13-8577-7fdb71790252",
        workspace_dir="-Users-knrz-Git-CyrusNuevoDia-geparesearch-evo",
        output_relpath="sessions/2026-04-20-build/01-rebrand-and-algo-migration.md",
        title="Rebrand evo → gepa-research and swap in the GEPA algorithm",
        summary="Kicked off with `/make`. Rename the project, replace the inner optimization loop with `gepa.optimize_anything`. Six parallel Explore subagents do mechanical find-replace across SDK, skills, tests, fixtures.",
        workspace="evo",
        date="2026-04-20",
    ),
    SessionSpec(
        session_id="432b690c-7b8e-42f5-93c2-2f41f76907e5",
        workspace_dir="-Users-knrz-Git-CyrusNuevoDia-geparesearch-evo",
        output_relpath="sessions/2026-04-20-build/02-cli-walkthrough.md",
        title="CLI walkthrough and tweaks",
        summary="Read through `src/gepa_research/cli.py`, validate the rename landed, propose tweaks.",
        workspace="evo",
        date="2026-04-20",
    ),
    SessionSpec(
        session_id="c41777ec-20de-4a21-ae14-e6c5b664a983",
        workspace_dir="-Users-knrz-Git-CyrusNuevoDia-geparesearch-evo",
        output_relpath="sessions/2026-04-20-build/03-end-to-end-smoke-test.md",
        title="Designing an end-to-end smoke test",
        summary="How would we wire a smoke test that exercises the full discover → optimize loop on a toy repo?",
        workspace="evo",
        date="2026-04-20",
    ),
    SessionSpec(
        session_id="9d8f32ff-8007-48b6-ab71-93413576fabe",
        workspace_dir="-Users-knrz-Git-CyrusNuevoDia-geparesearch",
        output_relpath="sessions/2026-04-20-build/04-running-in-autoresearch-dir.md",
        title="How do I run this in ./autoresearch?",
        summary="Quick setup question that kicks off the autoresearch workspace iteration.",
        workspace="geparesearch",
        date="2026-04-20",
    ),
    SessionSpec(
        session_id="68351d00-0974-4823-b9be-34b0e338284b",
        workspace_dir="-Users-knrz-Git-CyrusNuevoDia-geparesearch-autoresearch",
        output_relpath="sessions/2026-04-20-build/05-autoresearch-iteration.md",
        title="Autoresearch dashboard iteration: hypothesis labels, run filtering, long-running optimization",
        summary="Iterating on the discover/optimize dashboard — surface real GEPA hypotheses, fix metric direction, filter old runs, kick off an 8-hour optimization. Researcher / coder / tester subagents.",
        workspace="autoresearch",
        date="2026-04-20",
    ),
    # --- 2026-04-21: it works post-build cleanup ------------------------------
    SessionSpec(
        session_id="01a9291b-95de-4353-bbb7-53a1032bdab0",
        workspace_dir="-Users-knrz-Git-CyrusNuevoDia-geparesearch",
        output_relpath="sessions/2026-04-21-it-works/01-readme-rebrand-force-push.md",
        title="README rebrand and force push",
        summary="Strip evo / evo-hq mentions from the README, switch user/repo to CyrusNuevoDia/gepa-research, amend, force-push.",
        workspace="geparesearch",
        date="2026-04-21",
    ),
    # --- 2026-04-25: discover skill review -----------------------------------
    SessionSpec(
        session_id="74c7d9dd-c8a4-4cb2-97d5-28b8c0d6bc8f",
        workspace_dir="-Users-knrz-Git-CyrusNuevoDia-geparesearch",
        output_relpath="sessions/2026-04-25-discover-skill/01-discover-skill-review.md",
        title="Review the discover SKILL.md",
        summary="Read-through of `plugins/gepa-research/skills/discover/SKILL.md` to validate the methodology before further work.",
        workspace="geparesearch",
        date="2026-04-25",
    ),
    # --- 2026-04-27: polish day ----------------------------------------------
    SessionSpec(
        session_id="590cbb02-dd63-4d34-9376-1003fc57c8f3",
        workspace_dir="-Users-knrz-Git-CyrusNuevoDia-gepa-research",
        output_relpath="sessions/2026-04-27-polish/01-install-from-github.md",
        title="Install instructions: install the CLI from GitHub, not PyPI",
        summary="Update all install instructions (especially in skills) to install the CLI from this GitHub repo rather than from PyPI/npm.",
        workspace="gepa-research",
        date="2026-04-27",
    ),
    SessionSpec(
        session_id="c3e67933-8764-4681-bafe-50cb854a45c3",
        workspace_dir="-Users-knrz-Git-CyrusNuevoDia-gepa-research",
        output_relpath="sessions/2026-04-27-polish/02-fork-acknowledgment.md",
        title="Add a fork shoutout for evoresearch",
        summary="Mention at the end of the README that gepa-research is a fork of evoresearch (github.com/evo-hq/evo).",
        workspace="gepa-research",
        date="2026-04-27",
    ),
    SessionSpec(
        session_id="c05ba9a3-f237-4472-ac5b-847c53065bbb",
        workspace_dir="-Users-knrz-Git-CyrusNuevoDia-gepa-research",
        output_relpath="sessions/2026-04-27-polish/03-commit-and-push.md",
        title="Commit and push staged changes",
        summary="Operational session: stage, commit, and push the day's work.",
        workspace="gepa-research",
        date="2026-04-27",
    ),
    SessionSpec(
        session_id="2f3b13b7-fd14-4c6b-8cce-fd5d00563503",
        workspace_dir="-Users-knrz-Git-CyrusNuevoDia-gepa-research",
        output_relpath="sessions/2026-04-27-polish/04-pull-from-upstream.md",
        title="Pull useful changes from upstream evo-hq/evo",
        summary="The repo was forked weeks ago — what's worth pulling from upstream? Set up `git remote add upstream` and review.",
        workspace="gepa-research",
        date="2026-04-27",
    ),
    SessionSpec(
        session_id="c92d9448-6a06-462c-9282-905cec63b32c",
        workspace_dir="-Users-knrz-Git-CyrusNuevoDia-gepa-research",
        output_relpath="sessions/2026-04-27-polish/05-fix-failing-github-build.md",
        title="Investigate and fix failing GitHub build",
        summary="CI is red — find out why and fix.",
        workspace="gepa-research",
        date="2026-04-27",
    ),
]

# Sessions explicitly dropped (kept here so the renderer doesn't accidentally include them).
# Both drops are intentional — the renderer only renders what's in SESSIONS, but listing
# them here documents the choice for future contributors.
DROPPED_SESSIONS: set[str] = {
    "f88ae1d2",  # 12 KB, only /clear + caveats
    "3622fa61",  # the meta session that built transcripts/ itself; recursion is awkward
}


# ---------------------------------------------------------------------------
# Redaction
# ---------------------------------------------------------------------------


_PEON_PING_PATTERNS = [
    re.compile(r"^peon-ping[^\n]*$", re.MULTILINE),
    re.compile(r"^peon:[^\n]*$", re.MULTILINE),
]
_ANSI_CSI = re.compile(r"\x1b\[[0-9;?]*[a-zA-Z]")
_OSC_TERMINAL_TITLE = re.compile(r"\x1b\][0-9]*;.*?(?:\x07|\x1b\\)")
_PATH_REPO_AND_SUBDIRS = re.compile(
    r"/Users/knrz/Git/CyrusNuevoDia/(geparesearch|gepa-research)(?:/(autoresearch|evo|gepa))?/"
)
_PATH_HOME = re.compile(r"/Users/knrz(?=[^A-Za-z0-9_]|$)")
# Generic email matcher. Local part must start AND end on [A-Za-z0-9_] so things
# like `603-@app.command` (a Python decorator on line 603) don't match.
_EMAIL_ANY = re.compile(
    r"\b[A-Za-z0-9_](?:[A-Za-z0-9._%+-]*[A-Za-z0-9_])?@[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?\.[A-Za-z]{2,}\b"
)
# Bot accounts in commit Co-Authored-By lines — preserve verbatim.
_PRESERVED_EMAIL_DOMAINS = {
    "anthropic.com",
    "github.com",
    "users.noreply.github.com",
}
# macOS Claude Code temp paths: /private/tmp/claude-501/-Users-knrz-Git-...
# The whole path leaks the user's encoded cwd, so we collapse the entire prefix.
_CLAUDE_TMP = re.compile(r"/private/tmp/claude-\d+(?:/[^\s\"<>`)\]]*)?")
_VAR_FOLDERS = re.compile(r"/var/folders/[A-Za-z0-9_+/=-]+")
# Inner <system-reminder>...</system-reminder> block (run multiple passes for nested).
_SYSTEM_REMINDER = re.compile(r"<system-reminder>.*?</system-reminder>", re.DOTALL)


def _redact_email(match: re.Match[str]) -> str:
    addr = match.group(0)
    if addr.lower() == "knouroozi@gmail.com":
        return "<user-email>"
    local, _, domain = addr.partition("@")
    if local.lower() == "noreply" and domain.lower() in _PRESERVED_EMAIL_DOMAINS:
        return addr
    return "<contributor-email>"

# Secrets — defensive, even though sweep showed only AWS Bedrock leaked in this batch.
_SECRET_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # AWS Bedrock long-lived key (the one we found leaked in a probe command).
    (re.compile(r"\bABSK[A-Za-z0-9+/=]{20,}"), "<aws-bedrock-key-redacted>"),
    # Generic env-var assignments to obvious secrets, e.g. FOO_TOKEN='...', BAR_KEY="..."
    (
        re.compile(
            r"((?:AWS_BEARER_TOKEN_BEDROCK|ANTHROPIC_API_KEY|OPENAI_API_KEY|GOOGLE_API_KEY|GEMINI_API_KEY|HF_TOKEN|HUGGINGFACE_TOKEN|GITHUB_TOKEN|NPM_TOKEN)=)(['\"]?)([^'\"\s]+)(['\"]?)"
        ),
        r"\1\2<redacted>\4",
    ),
    # Anthropic, OpenAI, GitHub, Slack token shapes (defensive).
    (re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}"), "<anthropic-key-redacted>"),
    (re.compile(r"\bsk-[A-Za-z0-9_-]{40,}"), "<openai-key-redacted>"),
    (re.compile(r"\bghp_[A-Za-z0-9]{30,}"), "<github-pat-redacted>"),
    (re.compile(r"\bghs_[A-Za-z0-9]{30,}"), "<github-server-token-redacted>"),
    (re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{20,}"), "<slack-token-redacted>"),
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"), "<private-key-redacted>"),
]


def redact(text: str) -> str:
    if not text:
        return text
    out = text
    for _ in range(5):  # crude nested-tag handler
        new = _SYSTEM_REMINDER.sub("", out)
        if new == out:
            break
        out = new
    out = _OSC_TERMINAL_TITLE.sub("", out)
    out = _ANSI_CSI.sub("", out)
    for pat in _PEON_PING_PATTERNS:
        out = pat.sub("", out)
    for pat, repl in _SECRET_PATTERNS:
        out = pat.sub(repl, out)
    out = _CLAUDE_TMP.sub("<claude-tmp>", out)
    out = _VAR_FOLDERS.sub("<tmp>", out)
    out = _PATH_REPO_AND_SUBDIRS.sub(r"~/<repo>/", out)
    out = _PATH_HOME.sub("~", out)
    out = _EMAIL_ANY.sub(_redact_email, out)
    # Collapse `~//` (artifact of substituting `/Users/knrz/` -> `~/`).
    out = out.replace("~//", "~/")
    return out


# ---------------------------------------------------------------------------
# JSONL loading and noise filter
# ---------------------------------------------------------------------------


_NOISE_TYPES = {
    "file-history-snapshot",
    "permission-mode",
    "last-prompt",
    "agent-name",
    "custom-title",
    "system",
    "attachment",
}
_BARE_COMMAND_PATTERN = re.compile(
    r"^\s*<command-name>/(?:clear|compact|model|fast|status|peon-ping-toggle|loop|cost|help|init)</command-name>",
    re.IGNORECASE,
)
_LOCAL_COMMAND_STDOUT = re.compile(r"^\s*<local-command-stdout>.*?</local-command-stdout>\s*$", re.DOTALL)
_LOCAL_COMMAND_CAVEAT = re.compile(r"^\s*<local-command-caveat>.*?</local-command-caveat>\s*$", re.DOTALL)


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return records


def is_noise_record(rec: dict[str, Any]) -> bool:
    rtype = rec.get("type")
    if rtype in _NOISE_TYPES:
        return True
    if rtype == "user":
        msg = rec.get("message", {})
        content = msg.get("content")
        if isinstance(content, str):
            stripped = content.strip()
            if not stripped:
                return True
            if _LOCAL_COMMAND_CAVEAT.match(stripped):
                return True
            if _LOCAL_COMMAND_STDOUT.match(stripped):
                return True
            if _BARE_COMMAND_PATTERN.match(stripped):
                return True
            # The "Tool loaded." messages that follow ToolSearch are pure UI.
            if stripped == "Tool loaded.":
                return True
        # isMeta caveat (already covered by content match above for the common case)
        if rec.get("isMeta") and isinstance(content, str) and "<local-command-caveat>" in content:
            return True
    return False


# ---------------------------------------------------------------------------
# Turn grouping and rendering
# ---------------------------------------------------------------------------


@dataclass
class ToolCall:
    name: str
    input: dict[str, Any]
    tool_use_id: str
    result: str = ""
    is_error: bool = False


@dataclass
class Turn:
    kind: str  # "user" | "assistant" | "summary" | "system_note"
    text_blocks: list[str] = field(default_factory=list)
    thinking_blocks: list[str] = field(default_factory=list)
    tool_calls: list[ToolCall] = field(default_factory=list)


def _user_text_from_content(content: Any) -> tuple[str, dict[str, str]]:
    """Return (rendered_user_text, tool_results_by_id)."""
    if isinstance(content, str):
        return content, {}
    if isinstance(content, list):
        text_parts: list[str] = []
        tool_results: dict[str, str] = {}
        for block in content:
            btype = block.get("type")
            if btype == "text":
                text_parts.append(block.get("text", ""))
            elif btype == "image":
                text_parts.append("_[image elided]_")
            elif btype == "tool_result":
                tool_use_id = block.get("tool_use_id", "")
                inner = block.get("content", "")
                if isinstance(inner, list):
                    inner_text = "\n".join(
                        b.get("text", "") for b in inner if b.get("type") == "text"
                    )
                else:
                    inner_text = str(inner)
                tool_results[tool_use_id] = inner_text
        return "\n".join(text_parts).strip(), tool_results
    return "", {}


def _is_session_continuation_summary(text: str) -> bool:
    return text.startswith("This session is being continued from a previous conversation")


def iter_turns(records: list[dict[str, Any]]) -> Iterator[Turn]:
    """Yield logical turns. Tool results from user records are folded into the
    most recent assistant turn that contains the matching tool_use_id."""
    pending_tool_results: dict[str, str] = {}
    assistant_turns_by_tool_id: dict[str, Turn] = {}

    for rec in records:
        if is_noise_record(rec):
            continue
        rtype = rec.get("type")
        msg = rec.get("message", {})

        if rtype == "user":
            content = msg.get("content")
            user_text, tool_results = _user_text_from_content(content)

            # Fold tool results into the assistant turn that produced them.
            for tool_id, result_text in tool_results.items():
                if tool_id in assistant_turns_by_tool_id:
                    for tc in assistant_turns_by_tool_id[tool_id].tool_calls:
                        if tc.tool_use_id == tool_id:
                            tc.result = result_text
                            break
                else:
                    pending_tool_results[tool_id] = result_text

            user_text = user_text.strip()
            if not user_text:
                continue

            kind = "summary" if _is_session_continuation_summary(user_text) else "user"
            yield Turn(kind=kind, text_blocks=[user_text])

        elif rtype == "assistant":
            content = msg.get("content", [])
            if not isinstance(content, list):
                continue
            turn = Turn(kind="assistant")
            for block in content:
                btype = block.get("type")
                if btype == "text":
                    text = block.get("text", "")
                    if text.strip():
                        turn.text_blocks.append(text)
                elif btype == "thinking":
                    text = block.get("thinking", "")
                    if text.strip():
                        turn.thinking_blocks.append(text)
                elif btype == "tool_use":
                    tc = ToolCall(
                        name=block.get("name", "?"),
                        input=block.get("input", {}) or {},
                        tool_use_id=block.get("id", ""),
                    )
                    if tc.tool_use_id in pending_tool_results:
                        tc.result = pending_tool_results.pop(tc.tool_use_id)
                    turn.tool_calls.append(tc)
                    assistant_turns_by_tool_id[tc.tool_use_id] = turn
            if turn.text_blocks or turn.thinking_blocks or turn.tool_calls:
                yield turn


# ---------------------------------------------------------------------------
# Markdown rendering
# ---------------------------------------------------------------------------


def _elide_lines(text: str, *, head: int, max_lines: int) -> str:
    lines = text.splitlines()
    if len(lines) <= max_lines:
        return text
    elided = len(lines) - head
    return "\n".join(lines[:head]) + f"\n[…{elided} lines elided…]"


def _elide_chars(text: str, *, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + f"\n[…{len(text) - max_chars} characters elided…]"


def _elide_result(result: str) -> str:
    if not result:
        return ""
    line_count = result.count("\n") + 1
    if line_count >= 50:
        head = 20 if line_count <= 500 else 10
        return _elide_lines(result, head=head, max_lines=50)
    return _elide_chars(result, max_chars=4000)


def _format_tool_input(tool: ToolCall) -> str:
    """One-line summary of the tool input. Specialized for common tools."""
    inp = tool.input
    if tool.name == "Bash":
        cmd = inp.get("command", "")
        return f"`{_elide_chars(cmd, max_chars=200)}`"
    if tool.name == "Read":
        return f"`{inp.get('file_path', '')}`" + (
            f" (lines {inp.get('offset')}–{inp.get('offset', 0) + inp.get('limit', 0)})"
            if inp.get("limit")
            else ""
        )
    if tool.name in {"Edit", "Write"}:
        return f"`{inp.get('file_path', '')}`"
    if tool.name == "Grep":
        return f"`{inp.get('pattern', '')}` in `{inp.get('path', '.')}`"
    if tool.name == "Glob":
        return f"`{inp.get('pattern', '')}`"
    if tool.name == "Agent":
        desc = inp.get("description", "")
        sub = inp.get("subagent_type", "general-purpose")
        return f"`{desc}` (`{sub}`)"
    if tool.name in {"TaskCreate", "TaskUpdate"}:
        return inp.get("subject") or inp.get("taskId") or ""
    if tool.name == "WebFetch":
        return f"`{inp.get('url', '')}`"
    if tool.name == "ToolSearch":
        return f"`{inp.get('query', '')}`"
    # Fallback: dump short JSON
    return f"`{_elide_chars(json.dumps(inp, ensure_ascii=False), max_chars=160)}`"


def _format_tool_call(tool: ToolCall) -> str:
    head = f"**{tool.name}** — {_format_tool_input(tool)}"
    if tool.name == "Edit":
        old = tool.input.get("old_string", "")
        new = tool.input.get("new_string", "")
        if old or new:
            old_e = _elide_lines(old, head=8, max_lines=12)
            new_e = _elide_lines(new, head=8, max_lines=12)
            head += f"\n\n```diff\n- {old_e.replace(chr(10), chr(10) + '- ')}\n+ {new_e.replace(chr(10), chr(10) + '+ ')}\n```"
    elif tool.name == "Write":
        body = tool.input.get("content", "")
        head += f"\n\n```\n{_elide_lines(body, head=20, max_lines=50)}\n```"
    elif tool.name == "Agent":
        prompt = tool.input.get("prompt", "")
        if prompt:
            head += f"\n\n> _spawn prompt:_\n>\n> {_elide_lines(prompt, head=12, max_lines=30).replace(chr(10), chr(10) + '> ')}"
    elif tool.name == "AskUserQuestion":
        questions = tool.input.get("questions", [])
        if questions:
            head += "\n"
            for q in questions:
                head += f"\n_Q:_ {q.get('question', '')}\n"
                for opt in q.get("options", []):
                    head += f"  - **{opt.get('label', '')}** — {opt.get('description', '')}\n"

    if tool.result:
        result = _elide_result(tool.result)
        head += f"\n\n```\n{result}\n```"
    elif tool.is_error:
        head += "\n\n_(error — no result captured)_"
    return head


def render_turn(turn: Turn) -> str:
    if turn.kind == "summary":
        return f"## Session continuation summary\n\n> _Claude Code summarized the previous (overflowed) context. Kept for narrative continuity._\n\n<details><summary>Previous-context summary</summary>\n\n{redact(turn.text_blocks[0])}\n\n</details>\n"

    if turn.kind == "user":
        body = redact(turn.text_blocks[0])
        return f"## User\n\n{body}\n"

    # assistant
    parts: list[str] = ["## Claude\n"]
    if turn.thinking_blocks:
        thinking = "\n\n".join(turn.thinking_blocks)
        thinking = redact(thinking)
        thinking = _elide_lines(thinking, head=20, max_lines=30)
        # Indent for blockquote
        quoted = "\n".join(f"> {line}" if line else ">" for line in thinking.splitlines())
        parts.append(f"<details><summary>thinking</summary>\n\n{quoted}\n\n</details>\n")
    for text in turn.text_blocks:
        parts.append(redact(text) + "\n")
    if turn.tool_calls:
        n = len(turn.tool_calls)
        plural = "" if n == 1 else "s"
        parts.append(f"<details><summary>{n} tool call{plural}</summary>\n")
        for tc in turn.tool_calls:
            tc_redacted = ToolCall(
                name=tc.name,
                input=tc.input,
                tool_use_id=tc.tool_use_id,
                result=redact(tc.result),
                is_error=tc.is_error,
            )
            tc_redacted.input = _redact_tool_input(tc.input)
            parts.append("\n" + _format_tool_call(tc_redacted) + "\n")
        parts.append("\n</details>\n")
    return "\n".join(parts)


def _redact_tool_input(inp: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in inp.items():
        if isinstance(v, str):
            out[k] = redact(v)
        elif isinstance(v, list):
            out[k] = [redact(x) if isinstance(x, str) else x for x in v]
        else:
            out[k] = v
    return out


# ---------------------------------------------------------------------------
# Session rendering
# ---------------------------------------------------------------------------


def _slugify(text: str) -> str:
    text = re.sub(r"[^\w\s-]", "", text.lower())
    text = re.sub(r"[\s_]+", "-", text).strip("-")
    return text[:60]


def render_session_file(spec: SessionSpec, source_root: Path, output_root: Path) -> Path:
    src = source_root / spec.workspace_dir / f"{spec.session_id}.jsonl"
    if not src.exists():
        raise FileNotFoundError(src)
    records = load_jsonl(src)
    turns = list(iter_turns(records))

    out = output_root / spec.output_relpath
    out.parent.mkdir(parents=True, exist_ok=True)

    frontmatter = {
        "session": spec.session_id[:8],
        "date": spec.date,
        "workspace": spec.workspace,
        "summary": spec.summary,
    }
    body_parts: list[str] = []
    body_parts.append("---")
    body_parts.append(yaml.safe_dump(frontmatter, sort_keys=False).strip())
    body_parts.append("---\n")
    body_parts.append(f"# {spec.title}\n")
    body_parts.append(f"_{spec.summary}_\n")
    for turn in turns:
        body_parts.append(render_turn(turn))
    out.write_text("\n".join(body_parts), encoding="utf-8")

    # Subagents
    subagent_dir_src = source_root / spec.workspace_dir / spec.session_id / "subagents"
    if subagent_dir_src.exists():
        subagent_out_dir = out.with_suffix("")
        subagent_out_dir.mkdir(parents=True, exist_ok=True)
        # Pair .jsonl with .meta.json
        agent_files = sorted(subagent_dir_src.glob("agent-*.jsonl"))
        for idx, agent_jsonl in enumerate(agent_files, start=1):
            meta_path = agent_jsonl.with_suffix(".meta.json")
            description = ""
            agent_type = ""
            if meta_path.exists():
                try:
                    meta = json.loads(meta_path.read_text())
                    description = meta.get("description", "")
                    agent_type = meta.get("agentType", "")
                except json.JSONDecodeError:
                    pass
            slug = _slugify(description or agent_jsonl.stem)
            sub_out = subagent_out_dir / f"{idx:02d}-{slug}.md"
            _render_subagent(agent_jsonl, sub_out, description, agent_type, spec.date)

    return out


def _render_subagent(
    src: Path, out: Path, description: str, agent_type: str, date: str
) -> None:
    records = load_jsonl(src)
    turns = list(iter_turns(records))
    fm = {
        "subagent_of": out.parent.name,
        "agent_type": agent_type or "unknown",
        "description": description,
        "date": date,
    }
    parts: list[str] = []
    parts.append("---")
    parts.append(yaml.safe_dump(fm, sort_keys=False).strip())
    parts.append("---\n")
    parts.append(f"# Subagent: {description or src.stem}\n")
    parts.append(
        f"_Spawned by the parent session as a `{agent_type or 'subagent'}` to do focused work._\n"
    )
    for turn in turns:
        parts.append(render_turn(turn))
    out.write_text("\n".join(parts), encoding="utf-8")


# ---------------------------------------------------------------------------
# Methodology copy
# ---------------------------------------------------------------------------


METHODOLOGY_FILES = [
    ("make", "Orchestrator: Claude thinks, Codex builds"),
    ("build", "Question-driven implementation guard"),
    ("shaping", "Collaborative problem definition"),
]


def copy_methodology(skills_root: Path, output_root: Path) -> list[Path]:
    out_dir = output_root / "methodology"
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for name, summary in METHODOLOGY_FILES:
        src = skills_root / name / "SKILL.md"
        if not src.exists():
            typer.echo(f"  skip methodology/{name}.md (not found at {src})")
            continue
        body = redact(src.read_text(encoding="utf-8"))
        fm = {"skill": name, "summary": summary}
        out = out_dir / f"{name}.md"
        out.write_text(
            "---\n" + yaml.safe_dump(fm, sort_keys=False).strip() + "\n---\n\n" + body,
            encoding="utf-8",
        )
        written.append(out)
    return written


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


@app.command()
def render(
    source_root: Path = typer.Option(DEFAULT_SOURCE_ROOT, help="~/.claude/projects"),
    output_root: Path = typer.Option(DEFAULT_OUTPUT_ROOT, help="repo transcripts/ dir"),
    skills_root: Path = typer.Option(DEFAULT_SKILLS_ROOT, help="~/.claude/skills"),
    clean: bool = typer.Option(False, help="Remove output_root/sessions and methodology before rendering"),
):
    """Render every curated session + methodology files."""
    if clean:
        for sub in ("sessions", "methodology"):
            target = output_root / sub
            if target.exists():
                shutil.rmtree(target)
    output_root.mkdir(parents=True, exist_ok=True)
    typer.echo(f"Source: {source_root}\nOutput: {output_root}")
    typer.echo("---")
    written = copy_methodology(skills_root, output_root)
    for p in written:
        typer.echo(f"  methodology/{p.name}")
    for spec in SESSIONS:
        out = render_session_file(spec, source_root, output_root)
        typer.echo(f"  {out.relative_to(output_root)}")
    typer.echo("---")
    typer.echo(f"Rendered {len(SESSIONS)} sessions + {len(written)} methodology files")


@app.command("render-one")
def render_one(
    session_prefix: str,
    source_root: Path = typer.Option(DEFAULT_SOURCE_ROOT),
    output_root: Path = typer.Option(DEFAULT_OUTPUT_ROOT),
):
    """Re-render just one session by id prefix (handy when iterating on redaction)."""
    matches = [s for s in SESSIONS if s.session_id.startswith(session_prefix)]
    if not matches:
        typer.echo(f"No session with prefix {session_prefix!r}")
        raise typer.Exit(1)
    if len(matches) > 1:
        typer.echo(f"Ambiguous prefix: {[m.session_id[:12] for m in matches]}")
        raise typer.Exit(1)
    out = render_session_file(matches[0], source_root, output_root)
    typer.echo(f"Wrote {out}")


if __name__ == "__main__":
    app()
