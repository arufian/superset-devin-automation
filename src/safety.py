from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class SafetyFinding:
    category: str
    severity: str
    rule: str
    file_path: str
    line_number: int | None
    excerpt: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SafetyScan:
    blocked: bool
    prompt_injection_count: int
    malicious_code_count: int
    findings: list[SafetyFinding]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


PROMPT_INJECTION_RULES: tuple[tuple[str, str], ...] = (
    ("ignore_prior_instructions", r"\b(ignore|disregard|forget)\b.{0,60}\b(previous|prior|above|system|developer)\b.{0,40}\binstructions?\b"),
    ("reveal_hidden_prompt", r"\b(reveal|print|show|dump)\b.{0,50}\b(system prompt|hidden instructions|developer message|secret instructions)\b"),
    ("agent_manipulation", r"\b(ci bot|reviewer|agent|assistant|devin)\b.{0,80}\b(must|should|will)\b.{0,80}\b(skip|approve|merge|ignore)\b"),
    ("prompt_role_override", r"\b(system prompt|you are now|act as|role: system)\b"),
)

MALICIOUS_CODE_RULES: tuple[tuple[str, str, str], ...] = (
    ("hardcoded_github_token", "high", r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b"),
    ("hardcoded_cloud_secret", "high", r"\b(AKIA[0-9A-Z]{16}|AIza[0-9A-Za-z_-]{20,})\b"),
    ("private_key_material", "high", r"-----BEGIN (RSA |OPENSSH |EC |DSA )?PRIVATE KEY-----"),
    ("eval_exec", "medium", r"\b(eval|exec)\s*\("),
    ("shell_true", "medium", r"subprocess\.[A-Za-z_]+\(.{0,120}\bshell\s*=\s*True"),
    ("curl_pipe_shell", "high", r"\b(curl|wget)\b.{0,120}\|\s*(sh|bash|zsh)\b"),
    ("env_exfiltration", "high", r"\b(os\.environ|process\.env|printenv|env)\b.{0,160}\b(requests\.post|httpx\.post|fetch|curl|wget)\b"),
    ("dangerous_remove", "medium", r"\brm\s+-rf\s+(/|\$HOME|~|\*)"),
    ("workflow_privilege_escalation", "high", r"\b(contents:\s*write|pull-requests:\s*write|id-token:\s*write|pull_request_target)\b"),
    ("base64_payload_execution", "high", r"\bbase64\s+(-d|--decode)\b.{0,120}\|\s*(sh|bash|zsh|python|node)\b"),
)


def scan_diff(diff_text: str) -> SafetyScan:
    findings: list[SafetyFinding] = []
    current_file = ""
    new_line: int | None = None

    for raw_line in diff_text.splitlines():
        if raw_line.startswith("diff --git "):
            current_file = _extract_file_path(raw_line)
            new_line = None
            continue
        if raw_line.startswith("@@"):
            new_line = _extract_new_line_number(raw_line)
            continue
        if raw_line.startswith("+++"):
            continue
        if raw_line.startswith("+"):
            added = raw_line[1:]
            findings.extend(_scan_added_line(added, current_file, new_line))
            if new_line is not None:
                new_line += 1
            continue
        if raw_line.startswith("-"):
            continue
        if new_line is not None:
            new_line += 1

    prompt_count = sum(1 for finding in findings if finding.category == "prompt_injection")
    malicious_count = sum(1 for finding in findings if finding.category == "malicious_code")

    return SafetyScan(
        blocked=bool(findings),
        prompt_injection_count=prompt_count,
        malicious_code_count=malicious_count,
        findings=findings,
    )


def _scan_added_line(line: str, file_path: str, line_number: int | None) -> list[SafetyFinding]:
    findings: list[SafetyFinding] = []
    searchable = line.strip()
    if not searchable:
        return findings

    for rule, pattern in PROMPT_INJECTION_RULES:
        if re.search(pattern, searchable, flags=re.IGNORECASE):
            findings.append(
                SafetyFinding(
                    category="prompt_injection",
                    severity="high",
                    rule=rule,
                    file_path=file_path,
                    line_number=line_number,
                    excerpt=_redact(searchable),
                )
            )

    for rule, severity, pattern in MALICIOUS_CODE_RULES:
        if re.search(pattern, searchable, flags=re.IGNORECASE):
            findings.append(
                SafetyFinding(
                    category="malicious_code",
                    severity=severity,
                    rule=rule,
                    file_path=file_path,
                    line_number=line_number,
                    excerpt=_redact(searchable),
                )
            )

    return findings


def _extract_file_path(diff_header: str) -> str:
    parts = diff_header.split()
    if len(parts) >= 4:
        return parts[3].removeprefix("b/")
    return ""


def _extract_new_line_number(hunk_header: str) -> int | None:
    match = re.search(r"\+(\d+)", hunk_header)
    if not match:
        return None
    return int(match.group(1))


def _redact(text: str) -> str:
    redacted = re.sub(r"\bgh[pousr]_[A-Za-z0-9_]{8,}\b", "<redacted-github-token>", text)
    redacted = re.sub(r"\bAKIA[0-9A-Z]{16}\b", "<redacted-aws-key>", redacted)
    redacted = re.sub(r"\bAIza[0-9A-Za-z_-]{20,}\b", "<redacted-google-key>", redacted)
    if len(redacted) > 240:
        return f"{redacted[:237]}..."
    return redacted
