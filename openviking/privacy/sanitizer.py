# Copyright (c) 2026 Beijing Volcano Engine Technology Co., Ltd.
# SPDX-License-Identifier: AGPL-3.0
"""Deterministic replacement of registered secrets with owner-bound references."""

from __future__ import annotations

import asyncio
import time
from collections import deque
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Callable

from openviking.privacy.reference import build_privacy_field_reference
from openviking.server.identity import RequestContext

if TYPE_CHECKING:
    from openviking.privacy.service import UserPrivacyConfigService

_AMBIGUOUS_PLACEHOLDER = "{{ov_privacy:ambiguous}}"
MIN_PROTECTED_VALUE_CHARS = 6
DEFAULT_MATCHER_CACHE_TTL_SECONDS = 3600.0


@dataclass(frozen=True)
class PrivacyReplacement:
    start: int
    end: int
    reference: str


@dataclass(frozen=True)
class PrivacySanitizationResult:
    content: str
    replacements: tuple[PrivacyReplacement, ...] = ()
    ambiguous_references: tuple[tuple[str, ...], ...] = ()

    @property
    def changed(self) -> bool:
        return bool(self.replacements)


@dataclass
class _AutomatonNode:
    transitions: dict[str, int] = field(default_factory=dict)
    failure: int = 0
    outputs: list[str] = field(default_factory=list)


class _SecretMatcher:
    """Small pure-Python Aho-Corasick matcher built once per catalog revision."""

    def __init__(self, references_by_secret: dict[str, str | tuple[str, ...]]):
        self._references_by_secret = references_by_secret
        self._nodes = [_AutomatonNode()]
        for secret in references_by_secret:
            state = 0
            for char in secret:
                state = self._nodes[state].transitions.setdefault(char, len(self._nodes))
                if state == len(self._nodes):
                    self._nodes.append(_AutomatonNode())
            self._nodes[state].outputs.append(secret)
        self._build_failures()

    def _build_failures(self) -> None:
        pending: deque[int] = deque()
        for state in self._nodes[0].transitions.values():
            pending.append(state)
        while pending:
            state = pending.popleft()
            for char, next_state in self._nodes[state].transitions.items():
                pending.append(next_state)
                fallback = self._nodes[state].failure
                while fallback and char not in self._nodes[fallback].transitions:
                    fallback = self._nodes[fallback].failure
                self._nodes[next_state].failure = self._nodes[fallback].transitions.get(char, 0)
                self._nodes[next_state].outputs.extend(
                    self._nodes[self._nodes[next_state].failure].outputs
                )

    def replacements(
        self, content: str
    ) -> tuple[list[PrivacyReplacement], list[tuple[str, ...]]]:
        matches: list[tuple[int, int, str]] = []
        state = 0
        for index, char in enumerate(content):
            while state and char not in self._nodes[state].transitions:
                state = self._nodes[state].failure
            state = self._nodes[state].transitions.get(char, 0)
            for secret in self._nodes[state].outputs:
                matches.append((index + 1 - len(secret), index + 1, secret))

        # Prefer the longest match at the same position and discard overlaps.
        matches.sort(key=lambda item: (item[0], -(item[1] - item[0]), item[1]))
        selected: list[PrivacyReplacement] = []
        ambiguous: list[tuple[str, ...]] = []
        cursor = 0
        for start, end, secret in matches:
            if start < cursor:
                continue
            target = self._references_by_secret[secret]
            if isinstance(target, tuple):
                ambiguous.append(target)
                selected.append(PrivacyReplacement(start, end, _AMBIGUOUS_PLACEHOLDER))
            else:
                selected.append(PrivacyReplacement(start, end, target))
            cursor = end
        return selected, ambiguous


class PrivacySanitizer:
    """Sanitize text with the active sensitive values owned by the current user."""

    def __init__(
        self,
        privacy: "UserPrivacyConfigService",
        *,
        cache_ttl_seconds: float = DEFAULT_MATCHER_CACHE_TTL_SECONDS,
        monotonic_clock: Callable[[], float] = time.monotonic,
    ):
        if cache_ttl_seconds <= 0:
            raise ValueError("cache_ttl_seconds must be positive")
        self._privacy = privacy
        self._cache_ttl_seconds = float(cache_ttl_seconds)
        self._monotonic_clock = monotonic_clock
        self._cache: dict[tuple[str, str, int], tuple[float, _SecretMatcher]] = {}
        self._cache_lock = asyncio.Lock()

    async def sanitize(
        self,
        content: str,
        *,
        ctx: RequestContext,
        uri: str = "",
    ) -> PrivacySanitizationResult:
        if not content or self._is_privacy_storage_uri(uri, ctx):
            return PrivacySanitizationResult(content=content)
        matcher = await self._matcher(ctx)
        replacements, ambiguous = matcher.replacements(content)
        if not replacements:
            return PrivacySanitizationResult(
                content=content,
                ambiguous_references=tuple(ambiguous),
            )
        parts: list[str] = []
        cursor = 0
        for replacement in replacements:
            parts.append(content[cursor : replacement.start])
            parts.append(replacement.reference)
            cursor = replacement.end
        parts.append(content[cursor:])
        return PrivacySanitizationResult(
            content="".join(parts),
            replacements=tuple(replacements),
            ambiguous_references=tuple(ambiguous),
        )

    async def _matcher(self, ctx: RequestContext) -> _SecretMatcher:
        revision = self._privacy.catalog_revision(ctx)
        cache_key = (ctx.account_id, ctx.user.user_id, revision)
        now = self._monotonic_clock()
        cached = self._cache.get(cache_key)
        if cached is not None and now - cached[0] < self._cache_ttl_seconds:
            return cached[1]
        async with self._cache_lock:
            now = self._monotonic_clock()
            cached = self._cache.get(cache_key)
            if cached is not None and now - cached[0] < self._cache_ttl_seconds:
                return cached[1]
            matcher = await self._build_matcher(ctx)
            owner_key = cache_key[:2]
            self._cache = {
                key: item for key, item in self._cache.items() if key[:2] != owner_key
            }
            self._cache[cache_key] = (now, matcher)
            return matcher

    async def _build_matcher(self, ctx: RequestContext) -> _SecretMatcher:
        references: dict[str, list[str]] = {}
        for category in await self._privacy.list_categories(ctx):
            for target_key in await self._privacy.list_targets(ctx, category):
                current = await self._privacy.get_current(ctx, category, target_key)
                if current is None:
                    continue
                for field_name, value in current.values.items():
                    # Privacy is the explicit protection boundary. Do not infer
                    # sensitivity from field names. Very short values are not
                    # safe for global substring replacement because ordinary
                    # prose would produce excessive false positives.
                    if (
                        not isinstance(value, str)
                        or len(value) < MIN_PROTECTED_VALUE_CHARS
                    ):
                        continue
                    reference = build_privacy_field_reference(
                        ctx.user.user_id,
                        category,
                        target_key,
                        field_name,
                    )
                    references.setdefault(value, []).append(reference)

        targets: dict[str, str | tuple[str, ...]] = {}
        for secret, candidates in references.items():
            unique = tuple(sorted(set(candidates)))
            if len(unique) == 1:
                targets[secret] = unique[0]
            else:
                targets[secret] = unique
        return _SecretMatcher(targets)

    @staticmethod
    def _is_privacy_storage_uri(uri: str, ctx: RequestContext) -> bool:
        root = f"viking://user/{ctx.user.user_id}/privacy"
        return uri.rstrip("/") == root or uri.startswith(f"{root}/")
