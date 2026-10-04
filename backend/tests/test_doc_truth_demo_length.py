"""The demo-length guard: the main demo is held to its canonical length and the separate
real-user rescue example to its own, per claim — a mention of one never loosens the other."""
from __future__ import annotations

import doc_truth as dt

EVIDENCE = {"version": "1.3.1", "demo": {"seconds": 66}}
MAIN = "https://example.test/docs/media/snapmaker-studio-demo.mp4"
RESCUE = "https://example.test/docs/media/snapmaker-studio-rescue-demo.mp4"


def offenders(text: str) -> list[str]:
    return dt.demo_offenders(text, EVIDENCE, name="doc")


def test_main_demo_at_its_canonical_length_passes():
    assert offenders(f"### [Watch it work — 66 seconds]({MAIN})\n") == []


def test_main_demo_with_the_wrong_length_fails():
    assert offenders(f"### [Watch it work — 65 seconds]({MAIN})\n")


def test_rescue_example_at_its_own_length_passes():
    assert offenders(f"**[Real-user rescue example — 65 seconds]({RESCUE})** — a recording.\n") == []


def test_rescue_example_with_the_main_demo_length_fails():
    assert offenders(f"**[Real-user rescue example — 66 seconds]({RESCUE})** — a recording.\n")


def test_a_wrong_main_demo_length_next_to_the_word_rescue_still_fails():
    # the number comes BEFORE any rescue reference, so it is the main demo's claim
    assert offenders("Main demo — 65 seconds; rescue details follow.\n")


def test_a_block_with_both_correct_lengths_passes():
    assert offenders(f"Watch it work — 66 seconds. The [real-user rescue example — 65 seconds]({RESCUE}).\n") == []


def test_a_block_with_both_lengths_swapped_fails():
    got = offenders(f"Watch it work — 65 seconds. The [real-user rescue example — 66 seconds]({RESCUE}).\n")
    assert len(got) == 2


def test_a_main_demo_cue_after_rescue_returns_the_claim_to_the_main_demo():
    assert offenders("The rescue example is separate; the main demo is 65 seconds.\n")
