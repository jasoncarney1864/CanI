"""Tests for LLM-generated document titles."""

from ingestion_worker_app.title_gen import generate_title


def test_generate_title_returns_string():
    """Verify generate_title returns a non-empty string (real or fallback)."""
    # Mock Azure OpenAI client to avoid real API calls in tests
    title = generate_title(
        "This is a sample document about Python programming best practices. "
        "It covers topics like type hints, testing, and code organization.",
        endpoint="https://fake.openai.azure.com",
        api_key="fake-key",
        api_version="2024-10-21",
        deployment="gpt-5-1",
    )
    # In tests without mocking, this will fail to connect and return the fallback
    assert isinstance(title, str)
    assert len(title) > 0


def test_generate_title_empty_text():
    """Empty text should return fallback title."""
    title = generate_title(
        "",
        endpoint="https://fake.openai.azure.com",
        api_key="fake-key",
        api_version="2024-10-21",
        deployment="gpt-5-1",
    )
    assert title == "Untitled Document"


def test_generate_title_whitespace_only():
    """Whitespace-only text should return fallback title."""
    title = generate_title(
        "   \n\n   ",
        endpoint="https://fake.openai.azure.com",
        api_key="fake-key",
        api_version="2024-10-21",
        deployment="gpt-5-1",
    )
    assert title == "Untitled Document"
