"""Tests for hotline.summarize (deterministic rules + LLM fallback)."""

from __future__ import annotations

from hotline.config import Config
from hotline.detect import detect
from hotline.summarize import Summary, summarize


def test_summarize_rules_extracts_number_action_and_prize(read_fixture) -> None:
    transcript = read_fixture("callout_transcript.txt")
    detection = detect(transcript, source="audio")
    assert detection is not None  # fixture must make detect() fire

    summary = summarize(transcript, detection)

    assert isinstance(summary, Summary)
    # Number extracted (SG 8-digit grouped as "6123 4567").
    assert "6123 4567" in summary.action
    # Call terms present -> "Call ... now".
    assert summary.action.startswith("Call ")
    assert summary.action.endswith("now")
    # Prize folded into the headline.
    assert "Coldplay" in summary.headline
    # Headline formatting: emoji + station + number + prize.
    assert summary.headline.startswith("\U0001f4de 987FM giveaway")
    assert "6123 4567" in summary.headline
    assert transcript.strip() in summary.details


def test_summarize_text_in_uses_text_action() -> None:
    transcript = "Text in WHATSAPP 8111 2222 to win a staycation, text in now!"
    detection = detect(transcript, source="audio")
    assert detection is not None

    summary = summarize(transcript, detection)
    assert summary.action.startswith("Text/WhatsApp")
    assert "8111 2222" in summary.action


def test_summarize_llm_mode_uses_injected_sender(read_fixture, make_sender) -> None:
    transcript = read_fixture("callout_transcript.txt")
    detection = detect(transcript, source="audio")
    assert detection is not None
    config = Config(
        summary_mode="llm",
        summary_api_base="https://llm.test/v1",
        summary_model="test-model",
        summary_api_key="sk-test",
    )

    calls: list[tuple[str, dict, dict]] = []

    def sender(url: str, payload: dict, headers: dict) -> dict:
        calls.append((url, payload, headers))
        return {"choices": [{"message": {"content": "LLM headline\nDo the thing"}}]}

    summary = summarize(transcript, detection, config, sender=sender)

    assert summary.headline == "LLM headline"
    assert summary.action == "Do the thing"
    assert calls[0][0] == "https://llm.test/v1/chat/completions"
    assert calls[0][2]["Authorization"] == "Bearer sk-test"


def test_summarize_llm_falls_back_to_rules_on_error(read_fixture) -> None:
    transcript = read_fixture("callout_transcript.txt")
    detection = detect(transcript, source="audio")
    assert detection is not None
    config = Config(
        summary_mode="llm",
        summary_api_base="https://llm.test/v1",
        summary_model="test-model",
        summary_api_key="sk-test",
    )

    def boom(url: str, payload: dict, headers: dict) -> dict:
        raise RuntimeError("endpoint down")

    summary = summarize(transcript, detection, config, sender=boom)

    # Fell back to the deterministic rules summary.
    assert "6123 4567" in summary.action
    assert summary.headline.startswith("\U0001f4de 987FM giveaway")
