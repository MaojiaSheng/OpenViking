# Copyright (c) 2026 Beijing Volcano Engine Technology Co., Ltd.
# SPDX-License-Identifier: AGPL-3.0
"""
Compatibility shim for FeishuParser.

FeishuParser has been moved to plugins/parser/feishu/.
This module provides backward compatibility.
"""

try:
    from plugins.parser.feishu.feishu import FeishuParser
except ImportError:
    # If the plugin can't be imported (e.g., not in Python path),
    # provide a class that will raise an informative error
    class FeishuParser:
        def __init__(self, *args, **kwargs):
            raise ImportError(
                "FeishuParser has been moved to a plugin. "
                "Please ensure the plugins directory is in your Python path, "
                "or import from plugins.parser.feishu.feishu directly."
            )
