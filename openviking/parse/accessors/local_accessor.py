# Copyright (c) 2026 Beijing Volcano Engine Technology Co., Ltd.
# SPDX-License-Identifier: AGPL-3.0
"""
Local file system accessor for OpenViking.

Provides a DataAccessor implementation for local files and directories.
This is the lowest-priority accessor that handles any path-like source
that isn't handled by other accessors.
"""

from pathlib import Path
from typing import Union

from .base import DataAccessor, LocalResource, SourceType


class LocalAccessor(DataAccessor):
    """
    Local file system accessor.

    This accessor handles local files and directories. It should be
    registered with the lowest priority so that it only handles sources
    that aren't picked up by other accessors (Git, HTTP, Feishu, etc.).

    Features:
    - Handles any existing local path (file or directory)
    - Marks resources as non-temporary (since they're already local)
    - Provides clear local source type metadata
    """

    def can_handle(self, source: Union[str, Path]) -> bool:
        """
        Check if this accessor can handle the source.

        LocalAccessor accepts any source that:
        1. Is a Path object, OR
        2. Is a string that looks like a local path and exists, OR
        3. Is a string that doesn't look like a URL (for fallback)

        Since this is a fallback accessor, it returns True for most sources.
        The priority system ensures other accessors get a chance first.

        Args:
            source: Source string or Path object

        Returns:
            True - this is a fallback accessor that can handle any source
        """
        # As the fallback accessor, we can handle anything
        # The registry will try higher-priority accessors first
        return True

    async def access(self, source: Union[str, Path], **kwargs) -> LocalResource:
        """
        Access a local file or directory.

        Simply wraps the local path in a LocalResource without any
        fetching or copying (since it's already local).

        Args:
            source: Local file path or Path object
            **kwargs: Additional arguments (unused for local accessor)

        Returns:
            LocalResource pointing to the local path
        """
        path = Path(source)

        return LocalResource(
            path=path,
            source_type=SourceType.LOCAL,
            original_source=str(source),
            meta={
                "filename": path.name,
                "suffix": path.suffix.lower() if path.suffix else None,
                "is_dir": path.is_dir() if path.exists() else None,
            },
            is_temporary=False,
        )

    @property
    def priority(self) -> int:
        """
        Priority of this accessor.

        Returns 1 - the lowest priority, ensuring this accessor is only
        used when no other accessor can handle the source.

        Standard priority levels:
        - 100: Specific service (Feishu, etc.)
        - 80: Version control (Git, etc.)
        - 50: Generic protocols (HTTP, etc.)
        - 10: Fallback accessors
        - 1: Local file system (this one)

        Returns:
            Priority level 1
        """
        return 1
