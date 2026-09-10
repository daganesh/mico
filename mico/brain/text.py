"""Shared word-count utility for State Briefs (PRD §2.2).

The PRD requires *one* implementation of word counting, used identically by
prompt assembly, Stage 1 validation, and the health audit — divergent
counting between those components is called out explicitly as a latent bug
class. Everything that needs to measure a brief against the soft/hard word
limits must go through :func:`count_words` and the constants below, not
re-implement splitting logic locally.
"""

from __future__ import annotations

import re

#: Soft limit (PRD §2.2): above this, the health audit flags the brief for
#: condensation. Not enforced at write time.
SOFT_WORD_LIMIT = 500

#: Hard limit (PRD §2.2): Stage 1 rejects a proposal at or above this count,
#: before any LLM call is made.
HARD_WORD_LIMIT = 750

# Frontmatter is the `---`-delimited YAML block at the very start of a full
# brief file. Matches only when it opens the string; a body-only string (no
# frontmatter) is left untouched.
_FRONTMATTER_RE = re.compile(r"\A---\n.*?\n---\n?", re.DOTALL)

# Evidence pointer syntax (PRD §2.4): `[^ev:<short_id>]`. Replaced with a
# single space rather than dropped outright, so removing a pointer wedged
# between two words without surrounding whitespace can't fuse them together.
_EVIDENCE_POINTER_RE = re.compile(r"\[\^ev:[^\]]*\]")


def strip_frontmatter(text: str) -> str:
    """Remove a leading YAML frontmatter block, if present.

    Safe to call on either a full brief file (frontmatter + body) or a bare
    body — a string that doesn't open with a frontmatter block is returned
    unchanged.
    """
    return _FRONTMATTER_RE.sub("", text, count=1)


def count_words(markdown_body: str) -> int:
    """Count words in a State Brief's body text.

    Excludes YAML frontmatter (if present) and evidence pointer syntax
    (`[^ev:<short_id>]`, PRD §2.4). Word-splitting is deliberately simple
    (whitespace-based) and deterministic — this doesn't need to be
    linguistically sophisticated, just consistent across every caller.
    """
    body = strip_frontmatter(markdown_body)
    body = _EVIDENCE_POINTER_RE.sub(" ", body)
    return len(body.split())
