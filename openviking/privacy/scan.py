# Copyright (c) 2026 Beijing Volcano Engine Technology Co., Ltd.
# SPDX-License-Identifier: AGPL-3.0
"""Explicit scan and repair workflow for already persisted Privacy values."""

from __future__ import annotations

from typing import Any, Iterable

from openviking.core.namespace import canonical_user_root, classify_uri, resolve_request_uri
from openviking.privacy.sanitizer import PrivacySanitizer
from openviking.server.identity import RequestContext
from openviking_cli.exceptions import InvalidArgumentError, NotFoundError

_SCOPES = frozenset({"resources", "skills", "memories"})
_SKIP_NAMES = frozenset(
    {
        ".abstract.md",
        ".overview.md",
        ".relations.json",
        ".source.json",
        ".image_mappings.json",
        ".artifact_manifest.json",
    }
)


def default_privacy_scan_roots(ctx: RequestContext, scopes: Iterable[str]) -> list[str]:
    user_root = canonical_user_root(ctx)
    roots: list[str] = []
    for scope in scopes:
        if scope not in _SCOPES:
            raise InvalidArgumentError(
                f"unsupported privacy scan scope: {scope}",
                details={"scope": scope, "allowed": sorted(_SCOPES)},
            )
        if scope == "resources":
            roots.extend([f"{user_root}/resources", "viking://resources"])
        elif scope == "skills":
            roots.extend([f"{user_root}/skills", "viking://agent/skills"])
        else:
            roots.append(f"{user_root}/memories")
    return list(dict.fromkeys(roots))


async def scan_privacy_content(
    *,
    service: Any,
    ctx: RequestContext,
    sanitizer: PrivacySanitizer,
    scopes: list[str],
    target_uri: str = "",
    fix: bool = False,
    wait: bool = False,
    node_limit: int = 10000,
) -> dict[str, Any]:
    """Scan readable text and optionally rewrite unambiguous matches."""
    if target_uri and scopes:
        raise InvalidArgumentError("pass either target_uri or scopes, not both")
    roots = (
        [resolve_request_uri(target_uri, ctx)]
        if target_uri
        else default_privacy_scan_roots(ctx, scopes or sorted(_SCOPES))
    )
    files: list[str] = []
    truncated = False
    for root in roots:
        try:
            stat = await service.viking_fs.stat(root, ctx=ctx, skip_count=True)
        except (NotFoundError, FileNotFoundError):
            continue
        if stat.get("isDir", stat.get("is_dir", False)):
            entries = await service.viking_fs.tree(
                root,
                output="original",
                show_all_hidden=True,
                node_limit=node_limit,
                level_limit=None,
                ctx=ctx,
            )
            if len(entries) >= node_limit:
                truncated = True
            files.extend(
                str(entry.get("uri") or "")
                for entry in entries
                if not entry.get("isDir") and entry.get("uri")
            )
        else:
            files.append(root)

    matches: list[dict[str, Any]] = []
    repaired = 0
    reindex_roots: set[str] = set()
    for uri in dict.fromkeys(files):
        if uri.rstrip("/").rsplit("/", 1)[-1] in _SKIP_NAMES:
            continue
        try:
            raw = await service.viking_fs.read_file_bytes(uri, ctx=ctx)
            content = raw.decode("utf-8")
        except UnicodeDecodeError:
            continue
        except (NotFoundError, FileNotFoundError):
            continue
        result = await sanitizer.sanitize(content, ctx=ctx, uri=uri)
        if not result.replacements and not result.ambiguous_references:
            continue
        item = {
            "uri": uri,
            "occurrences": len(result.replacements),
            "references": sorted({replacement.reference for replacement in result.replacements}),
            "ambiguous": [list(candidates) for candidates in result.ambiguous_references],
            "fixable": not result.ambiguous_references,
            "fixed": False,
        }
        if fix and item["fixable"]:
            classification = classify_uri(uri)
            if classification.is_skill:
                path = service.viking_fs._uri_to_path(uri, ctx=ctx)
                lease = await service.viking_fs._async_agfs.pathlock_acquire_exact(path)
                try:
                    await service.viking_fs.write_file(
                        uri, result.content, ctx=ctx, lease_ref=lease
                    )
                finally:
                    await service.viking_fs._async_agfs.pathlock_release(lease)
                parts = uri.split("/skills/", 1)
                skill_name = parts[1].split("/", 1)[0] if len(parts) == 2 else ""
                if skill_name:
                    reindex_roots.add(f"{parts[0]}/skills/{skill_name}")
            else:
                await service.fs.write(uri, result.content, ctx=ctx, wait=wait)
            item["fixed"] = True
            repaired += 1
        matches.append(item)

    reindex_tasks: list[dict[str, Any]] = []
    if fix:
        for root in sorted(reindex_roots):
            reindex_tasks.append(
                await service.reindex(
                    uri=root,
                    mode="semantic_and_vectors",
                    wait=wait,
                    force=True,
                    ctx=ctx,
                )
            )
    return {
        "roots": roots,
        "scanned_files": len(dict.fromkeys(files)),
        "matched_files": len(matches),
        "repaired_files": repaired,
        "dry_run": not fix,
        "truncated": truncated,
        "matches": matches,
        "reindex": reindex_tasks,
    }
