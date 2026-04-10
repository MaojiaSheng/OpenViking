# Copyright (c) 2026 Beijing Volcano Engine Technology Co., Ltd.
# SPDX-License-Identifier: AGPL-3.0
"""
Feishu/Lark Parser Plugin

This plugin provides parsing for Feishu/Lark cloud documents:
- Documents: https://*.feishu.cn/docx/{document_id}
- Wiki pages: https://*.feishu.cn/wiki/{token}
- Spreadsheets: https://*.feishu.cn/sheets/{token}
- Bitable: https://*.feishu.cn/base/{app_token}
"""

from __future__ import annotations

from typing import List

from openviking.parse import BaseParser, ParserProvider

from .feishu import FeishuParser


class FeishuParserProvider(ParserProvider):
    """Parser provider for Feishu/Lark cloud documents."""

    @property
    def name(self) -> str:
        return "feishu"

    def is_available(self) -> bool:
        """Check if lark-oapi dependency is available."""
        try:
            import lark_oapi  # noqa: F401

            return True
        except ImportError:
            return False

    def create_parser(self, **kwargs) -> BaseParser:
        """Create a FeishuParser instance."""
        return FeishuParser(**kwargs)

    def get_config_schema(self) -> List[dict]:
        """Return configuration schema for Feishu."""
        return [
            {
                "key": "app_id",
                "description": "Feishu App ID",
                "secret": True,
                "required": True,
                "env_var": "FEISHU_APP_ID",
                "url": "https://open.feishu.cn",
            },
            {
                "key": "app_secret",
                "description": "Feishu App Secret",
                "secret": True,
                "required": True,
                "env_var": "FEISHU_APP_SECRET",
                "url": "https://open.feishu.cn",
            },
            {
                "key": "domain",
                "description": "Feishu API domain",
                "default": "https://open.feishu.cn",
                "choices": [
                    "https://open.feishu.cn",
                    "https://open.larksuite.com",
                ],
            },
        ]

    @property
    def supported_extensions(self) -> List[str]:
        """Feishu is URL-based, no file extensions."""
        return []

    def can_handle(self, path) -> bool:
        """Check if the source is a Feishu URL."""
        path_str = str(path)
        return "feishu.cn" in path_str or "larksuite.com" in path_str


def register(ctx):
    """Register the Feishu parser provider."""
    ctx.register_parser_provider(FeishuParserProvider())
