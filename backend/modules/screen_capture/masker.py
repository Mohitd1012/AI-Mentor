"""
Sensitive data masker.

Detects and redacts passwords, API keys, tokens, and other secrets
from OCR text before it is sent to any AI provider.
"""

import re
from dataclasses import dataclass

# Each pattern: (label, compiled_regex, replacement)
@dataclass
class _Rule:
    label: str
    pattern: re.Pattern
    replacement: str


_RULES: list[_Rule] = [
    # Generic high-entropy secrets: 32+ hex chars
    _Rule(
        "hex_secret",
        re.compile(r'\b[0-9a-fA-F]{32,}\b'),
        "[HEX_SECRET]",
    ),
    # OpenAI keys
    _Rule(
        "openai_key",
        re.compile(r'sk-[A-Za-z0-9]{32,}'),
        "[OPENAI_KEY]",
    ),
    # Anthropic keys
    _Rule(
        "anthropic_key",
        re.compile(r'sk-ant-[A-Za-z0-9\-_]{32,}'),
        "[ANTHROPIC_KEY]",
    ),
    # AWS access key IDs
    _Rule(
        "aws_key_id",
        re.compile(r'\b(AKIA|ASIA|AROA)[A-Z0-9]{16}\b'),
        "[AWS_KEY_ID]",
    ),
    # AWS secret access keys
    _Rule(
        "aws_secret",
        re.compile(r'(?i)aws.{0,20}secret.{0,20}[=:]\s*[A-Za-z0-9/+=]{40}'),
        "[AWS_SECRET]",
    ),
    # GitHub tokens
    _Rule(
        "github_token",
        re.compile(r'gh[pousr]_[A-Za-z0-9]{36,}'),
        "[GITHUB_TOKEN]",
    ),
    # Generic Bearer tokens
    _Rule(
        "bearer_token",
        re.compile(r'(?i)bearer\s+[A-Za-z0-9\-._~+/]+=*'),
        "Bearer [TOKEN]",
    ),
    # Passwords in key=value style
    _Rule(
        "password_kv",
        re.compile(r'(?i)(password|passwd|pwd)\s*[=:]\s*\S+'),
        r'\1=[REDACTED]',
    ),
    # Private key headers
    _Rule(
        "private_key",
        re.compile(r'-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----'),
        "[PRIVATE_KEY_BLOCK]",
    ),
    # Credit card numbers (simple Luhn-like pattern)
    _Rule(
        "credit_card",
        re.compile(r'\b(?:\d[ -]?){13,16}\b'),
        "[CARD_NUMBER]",
    ),
    # SSN
    _Rule(
        "ssn",
        re.compile(r'\b\d{3}-\d{2}-\d{4}\b'),
        "[SSN]",
    ),
]


def mask(text: str) -> str:
    """Returns text with all sensitive patterns replaced."""
    for rule in _RULES:
        text = rule.pattern.sub(rule.replacement, text)
    return text


def scan_for_secrets(text: str) -> list[str]:
    """Returns labels of secret types found (without exposing values)."""
    found = []
    for rule in _RULES:
        if rule.pattern.search(text):
            found.append(rule.label)
    return found
