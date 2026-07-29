"""Deterministic token estimator.

This is intentionally a frozen, pure heuristic (characters / 4, floor 1)
rather than a model-specific tokenizer, so the same input always yields the
same estimate on every machine (plan.md determinism guarantee D6). It is the
same order-of-magnitude heuristic AgentEval documents as its fallback
estimator (~15% error vs. real tokenizers).
"""
from __future__ import annotations

_CHARS_PER_TOKEN = 4


def estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, len(text) // _CHARS_PER_TOKEN)
