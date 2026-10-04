"""No personal data in the repository — the datasets above all (SECURITY.md §6).

Every dataset here is synthetic or self-authored (DATASET.md), and this keeps it so: a recording
transcript, a copied chat log or a real test account would carry exactly these shapes. It scans
every tracked text file, so a dataset added later is covered the day it is committed. What it
looks for is what would identify a student in India: an email address outside the reserved
example domains, a mobile number, an Aadhaar or a PAN.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]

# RFC 2606 / 6761 reserved names: an address there cannot belong to anyone.
RESERVED_DOMAIN = re.compile(r"(^|\.)(example(\.(com|org|net))?|invalid|test|localhost)$")
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@((?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,})")
PATTERNS = {
    # A ten-digit Indian mobile number, with or without +91, whole or split 5 + 5.
    "mobile number": re.compile(
        r"(?<![\w+-])(?<!\d\.)(?:\+91[\s-]?)?[6-9]\d{4}[\s-]?\d{5}(?![\w-]|\.\d)"
    ),
    # Twelve digits, whole or in groups of four; not a fragment of a UUID or a longer number.
    "Aadhaar": re.compile(r"(?<![\w-])[2-9]\d{3}( ?)\d{4}\1\d{4}(?![\w-])"),
    # Five letters (the fourth names the holder's kind), four digits, a letter.
    "PAN": re.compile(r"\b[A-Z]{3}[ABCFGHJLPT][A-Z]\d{4}[A-Z]\b"),
}
BINARY = {".wav", ".png", ".jpg", ".jpeg", ".ico", ".onnx", ".pdf", ".woff", ".woff2", ".db"}


def _tracked_text_files() -> list[Path]:
    listed = subprocess.run(
        ["git", "ls-files", "-z"],  # noqa: S607 - git from PATH, as CI's checkout provides
        cwd=REPO,
        capture_output=True,
        check=True,
    ).stdout.decode()
    paths = [REPO / name for name in listed.split("\0") if name]
    return [p for p in paths if p.suffix.lower() not in BINARY and p.is_file()]


def _findings() -> list[str]:
    found = []
    for path in _tracked_text_files():
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        where = path.relative_to(REPO)
        for match in EMAIL.finditer(text):
            if not RESERVED_DOMAIN.search(match.group(1).lower()):
                found.append(f"{where}: email {match.group(0)}")
        for kind, pattern in PATTERNS.items():
            found += [f"{where}: {kind} {m.group(0)}" for m in pattern.finditer(text)]
    return found


def test_the_repository_holds_no_personal_data() -> None:
    assert _findings() == []


def test_the_scan_would_notice_each_kind() -> None:
    """The patterns themselves: an empty result means nothing was there, not a blind scanner."""
    # Built from pieces, so that this file does not itself hold what it scans for.
    samples = {
        "email": "someone" + "@" + "gmail.com",
        "mobile number": "+91 98765" + " 43210",
        "Aadhaar": "2345 6789" + " 0123",
        "PAN": "ABCPE" + "1234F",
    }
    for kind, sample in samples.items():
        pattern = EMAIL if kind == "email" else PATTERNS[kind]
        assert pattern.search(f"said: {sample}."), kind
    assert not RESERVED_DOMAIN.search("gmail.com")
    for reserved in ("example.com", "school.example", "nobody.invalid", "localhost"):
        assert RESERVED_DOMAIN.search(reserved), reserved
    # Not personal: a UUID's groups, a timestamp, a long id.
    for innocent in ("22222222-2222-2222-2222-222222222222", "1727654321000", "req-9876543210-x"):
        assert not any(p.search(innocent) for p in PATTERNS.values()), innocent
