"""Log hygiene (SECURITY.md §5): secrets must never serialise, transcripts are hashed."""

from app.core.logging import _redact, _transcript_policy, hash_text


def test_secret_keys_are_redacted() -> None:
    event = {
        "event": "auth.login",
        "password": "correct-horse-battery-staple",
        "refresh_token": "rt_abc123",
        "Authorization": "Bearer eyJ...",
        "api_key": "fake-provider-key-for-redaction-test",
        "user_id": "u-1",
    }
    cleaned = _redact(None, "info", dict(event))
    for key in ("password", "refresh_token", "Authorization", "api_key"):
        assert cleaned[key] == "[redacted]"
        assert event[key] not in str(cleaned)
    assert cleaned["user_id"] == "u-1", "non-secret fields must survive"


def test_transcripts_are_hashed_by_default() -> None:
    policy = _transcript_policy(log_transcripts=False)
    cleaned = policy(None, "info", {"transcript": "Kirchhoff ka voltage law samjhao"})
    assert cleaned["transcript"].startswith("sha256:")
    assert "Kirchhoff" not in cleaned["transcript"]
    assert cleaned["transcript_chars"] > 0


def test_transcripts_pass_through_when_explicitly_enabled() -> None:
    policy = _transcript_policy(log_transcripts=True)
    cleaned = policy(None, "info", {"transcript": "hello"})
    assert cleaned["transcript"] == "hello"


def test_hash_is_stable_and_truncated() -> None:
    assert hash_text("same") == hash_text("same")
    assert hash_text("same") != hash_text("different")
    assert len(hash_text("x")) == len("sha256:") + 16
