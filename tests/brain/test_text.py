"""Tests for mico/brain/text.py — the shared word-count utility (PRD §2.2)."""

from __future__ import annotations

from mico.brain.text import (
    HARD_WORD_LIMIT,
    SOFT_WORD_LIMIT,
    count_words,
    strip_frontmatter,
)

FRONTMATTER = """---
track_slug: architecture-migration
revision: 47
generated_at: 2026-09-02T10:15:00Z
---
"""


def test_counts_plain_body() -> None:
    body = "## Ground Truth\nThe v2 endpoint is unblocked pending SecOps sign-off.\n"
    assert count_words(body) == 11


def test_strips_frontmatter_from_full_file() -> None:
    body = "## Ground Truth\nThe v2 endpoint is unblocked.\n"
    full_file = FRONTMATTER + body

    assert count_words(full_file) == count_words(body)
    assert strip_frontmatter(full_file).strip() == body.strip()


def test_body_without_frontmatter_is_unchanged() -> None:
    body = "## Notes\nNo frontmatter here.\n"
    assert strip_frontmatter(body) == body


def test_strips_evidence_pointers_without_undercounting_prose() -> None:
    with_pointer = "SecOps sign-off received[^ev:abc123] and the v2 endpoint is unblocked."
    without_pointer = "SecOps sign-off received and the v2 endpoint is unblocked."

    assert count_words(with_pointer) == count_words(without_pointer)


def test_evidence_pointer_removal_does_not_fuse_adjacent_words() -> None:
    # Pointer sits directly against the following word with no space.
    glued = "Blocked on SecOps.[^ev:abc]Escalated yesterday."
    assert count_words(glued) == count_words("Blocked on SecOps. Escalated yesterday.")


def test_multiple_evidence_pointers_in_one_body() -> None:
    body = "Ground truth one[^ev:a1] and ground truth two[^ev:b2] both hold."
    assert count_words(body) == 9


def test_empty_body_counts_zero() -> None:
    assert count_words("") == 0
    assert count_words(FRONTMATTER) == 0


def test_threshold_constants_match_prd() -> None:
    assert SOFT_WORD_LIMIT == 500
    assert HARD_WORD_LIMIT == 750
