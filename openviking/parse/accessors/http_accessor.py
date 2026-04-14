# Copyright (c) 2026 Beijing Volcano Engine Technology Co., Ltd.
# SPDX-License-Identifier: AGPL-3.0
"""
HTTP URL Accessor.

Fetches HTTP/HTTPS URLs and makes them available as local files.
This is the DataAccessor layer extracted from HTMLParser.
"""

import tempfile
from pathlib import Path
from typing import Optional, Union
from urllib.parse import unquote, urlparse

from openviking.parse.base import lazy_import
from openviking.utils.network_guard import build_httpx_request_validation_hooks
from openviking_cli.utils.logger import get_logger

from .base import DataAccessor, LocalResource, SourceType

logger = get_logger(__name__)


class HTTPAccessor(DataAccessor):
    """
    Accessor for HTTP/HTTPS URLs.

    Features:
    - Downloads web pages to local HTML files
    - Downloads files (PDF, Markdown, etc.) to local files
    - Supports GitHub/GitLab blob to raw URL conversion
    - Follows redirects
    - Network guard integration
    - Detailed error classification (network, timeout, auth, etc.)
    """

    PRIORITY = 50  # Lower than GitAccessor, higher than fallback

    DEFAULT_USER_AGENT = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )

    def __init__(
        self,
        timeout: float = 30.0,
        user_agent: Optional[str] = None,
    ):
        """Initialize HTTP accessor."""
        self.timeout = timeout
        self.user_agent = user_agent or self.DEFAULT_USER_AGENT

    @property
    def priority(self) -> int:
        return self.PRIORITY

    def can_handle(self, source: Union[str, Path]) -> bool:
        """
        Check if this accessor can handle the source.

        Handles any HTTP/HTTPS URL.
        NOTE: GitAccessor and FeishuAccessor have higher priority
        and will be checked first for their specific URL types.
        """
        source_str = str(source)

        # Only handle http/https URLs
        return source_str.startswith(("http://", "https://"))

    async def access(self, source: Union[str, Path], **kwargs) -> LocalResource:
        """
        Fetch the HTTP URL to a local file.

        Args:
            source: HTTP/HTTPS URL
            **kwargs: Additional arguments (request_validator, etc.)

        Returns:
            LocalResource pointing to the downloaded file
        """
        source_str = str(source)
        request_validator = kwargs.get("request_validator")

        # Download the URL
        temp_path = await self._download_url(
            source_str,
            request_validator=request_validator,
        )

        # Build metadata
        meta = {
            "url": source_str,
            "downloaded": True,
        }

        return LocalResource(
            path=Path(temp_path),
            source_type=SourceType.HTTP,
            original_source=source_str,
            meta=meta,
            is_temporary=True,
        )

    @staticmethod
    def _extract_filename_from_url(url: str) -> str:
        """
        Extract and URL-decode the original filename from a URL.

        Args:
            url: URL to extract filename from

        Returns:
            Decoded filename (e.g., "schemas.py" from ".../schemas.py")
            Falls back to "download" if no filename can be extracted.
        """
        parsed = urlparse(url)
        # URL-decode path to handle encoded characters (e.g., %E7%99%BE -> Chinese chars)
        decoded_path = unquote(parsed.path)
        basename = Path(decoded_path).name
        return basename if basename else "download"

    async def _download_url(
        self,
        url: str,
        request_validator=None,
    ) -> str:
        """
        Download URL content to a temporary file.

        Args:
            url: URL to download
            request_validator: Optional network request validator

        Returns:
            Path to the temporary file
        """
        httpx = lazy_import("httpx")

        # Convert GitHub/GitLab blob URLs to raw
        url = self._convert_to_raw_url(url)

        # Determine file extension from URL (decode first to handle encoded paths)
        parsed = urlparse(url)
        decoded_path = unquote(parsed.path)
        ext = Path(decoded_path).suffix or ".html"

        # Create temp file
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=ext)
        temp_path = temp_file.name
        temp_file.close()

        try:
            # Download content
            client_kwargs = {
                "timeout": self.timeout,
                "follow_redirects": True,
            }
            event_hooks = build_httpx_request_validation_hooks(request_validator)
            if event_hooks:
                client_kwargs["event_hooks"] = event_hooks
                client_kwargs["trust_env"] = False

            async with httpx.AsyncClient(**client_kwargs) as client:
                headers = {"User-Agent": self.user_agent}
                try:
                    response = await client.get(url, headers=headers)
                    response.raise_for_status()
                except httpx.ConnectError as e:
                    user_msg = "HTTP request failed: could not connect to server. Check the URL or your network."
                    raise RuntimeError(f"{user_msg} URL: {url}. Details: {e}") from e
                except httpx.TimeoutException as e:
                    user_msg = "HTTP request failed: timeout. The server took too long to respond."
                    raise RuntimeError(f"{user_msg} URL: {url}. Details: {e}") from e
                except httpx.HTTPStatusError as e:
                    status_code = e.response.status_code if e.response else "unknown"
                    if status_code == 401 or status_code == 403:
                        user_msg = f"HTTP request failed: authentication error ({status_code}). Check your credentials or permissions."
                    elif status_code == 404:
                        user_msg = f"HTTP request failed: not found ({status_code}). The URL may be invalid or the resource was removed."
                    elif 500 <= status_code < 600:
                        user_msg = f"HTTP request failed: server error ({status_code}). The server encountered an error."
                    else:
                        user_msg = f"HTTP request failed: status code {status_code}."
                    raise RuntimeError(f"{user_msg} URL: {url}. Details: {e}") from e
                except Exception as e:
                    user_msg = "HTTP request failed: unexpected error."
                    raise RuntimeError(f"{user_msg} URL: {url}. Details: {e}") from e

                # Write to temp file
                Path(temp_path).write_bytes(response.content)

            return temp_path
        except Exception:
            # Clean up on error
            try:
                p = Path(temp_path)
                if p.exists():
                    p.unlink(missing_ok=True)
            except Exception:
                pass
            raise

    def _convert_to_raw_url(self, url: str) -> str:
        """Convert GitHub/GitLab blob URL to raw URL."""
        parsed = urlparse(url)
        try:
            from openviking_cli.utils.config import get_openviking_config

            config = get_openviking_config()
            github_domains = config.html.github_domains
            gitlab_domains = config.html.gitlab_domains
            github_raw_domain = config.code.github_raw_domain

            if parsed.netloc in github_domains:
                path_parts = parsed.path.strip("/").split("/")
                if len(path_parts) >= 4 and path_parts[2] == "blob":
                    # Remove 'blob'
                    new_path = "/".join(path_parts[:2] + path_parts[3:])
                    return f"https://{github_raw_domain}/{new_path}"

            if parsed.netloc in gitlab_domains and "/blob/" in parsed.path:
                return url.replace("/blob/", "/raw/")

        except Exception:
            pass

        return url
