# Copyright (c) 2026 Beijing Volcano Engine Technology Co., Ltd.
# SPDX-License-Identifier: AGPL-3.0
"""
Parser Plugin Base - Abstract base class for parser plugins.

This module defines the PluginProvider interface for extending OpenViking
with custom parsers without modifying core code.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from openviking.parse.parsers.base_parser import BaseParser

logger = logging.getLogger(__name__)


class ParserProvider(ABC):
    """
    Abstract base class for parser plugin providers.

    Parser providers are responsible for:
    - Declaring availability (checking dependencies)
    - Creating parser instances
    - Declaring supported file extensions
    - Declaring configuration schema (optional)

    Example:
        class MyParserProvider(ParserProvider):
            @property
            def name(self) -> str:
                return "my_parser"

            def is_available(self) -> bool:
                try:
                    import my_dependency
                    return True
                except ImportError:
                    return False

            def create_parser(self, **kwargs) -> BaseParser:
                return MyParser(**kwargs)

            @property
            def supported_extensions(self) -> List[str]:
                return [".myext"]
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """
        Unique identifier for this parser provider.

        Returns:
            Short string identifier (e.g., "markdown", "pdf", "feishu")
        """

    @abstractmethod
    def is_available(self) -> bool:
        """
        Check if this parser is available for use.

        This method should:
        - Check if required dependencies are installed
        - Check if required configuration is present
        - NOT make any network calls
        - NOT perform expensive operations

        Returns:
            True if the parser can be used, False otherwise
        """

    @abstractmethod
    def create_parser(self, **kwargs) -> BaseParser:
        """
        Create a new parser instance.

        Args:
            **kwargs: Configuration options for the parser

        Returns:
            A configured BaseParser instance
        """

    def get_config_schema(self) -> List[Dict[str, Any]]:
        """
        Return configuration schema for this parser.

        Each field is a dict with:
            key: Config key name (e.g., "api_key", "mode")
            description: Human-readable description
            secret: True if this should go to .env (default: False)
            required: True if required (default: False)
            default: Default value (optional)
            choices: List of valid values (optional)
            url: URL where user can get this credential (optional)
            env_var: Explicit env var name for secrets (optional)

        Returns:
            List of config field definitions, empty list if no config needed
        """
        return []

    @property
    def supported_extensions(self) -> List[str]:
        """
        List of file extensions supported by this parser.

        Returns:
            List of extensions including the dot (e.g., [".md", ".markdown"])
        """
        return []

    def can_handle(self, path: Union[str, Path]) -> bool:
        """
        Check if this parser can handle the given file.

        Args:
            path: File path to check

        Returns:
            True if this parser can handle the file
        """
        path = Path(path)
        return path.suffix.lower() in self.supported_extensions


# ============================================================================
# Built-in Parser Provider Wrapper
# ============================================================================


class BuiltinParserProvider(ParserProvider):
    """
    Wrapper to adapt existing built-in parsers to the plugin provider interface.

    This allows seamless integration of existing parsers into the plugin system
    without modifying their implementation.
    """

    def __init__(self, name: str, parser_class: type, supported_extensions: List[str]):
        """
        Initialize a built-in parser provider wrapper.

        Args:
            name: Parser name identifier
            parser_class: The parser class to wrap
            supported_extensions: List of supported file extensions
        """
        self._name = name
        self._parser_class = parser_class
        self._supported_extensions = supported_extensions

    @property
    def name(self) -> str:
        return self._name

    def is_available(self) -> bool:
        """Built-in parsers are always available."""
        return True

    def create_parser(self, **kwargs) -> BaseParser:
        return self._parser_class(**kwargs)

    @property
    def supported_extensions(self) -> List[str]:
        return self._supported_extensions


# ============================================================================
# Plugin Context
# ============================================================================


class ParserPluginContext:
    """
    Context object passed to plugin register functions.

    Provides methods for plugins to register themselves with the system.
    """

    def __init__(self):
        self._providers: Dict[str, ParserProvider] = {}

    def register_parser_provider(self, provider: ParserProvider) -> None:
        """
        Register a parser provider.

        Args:
            provider: The ParserProvider instance to register
        """
        self._providers[provider.name] = provider
        logger.debug(f"Registered parser provider: {provider.name}")

    def get_provider(self, name: str) -> Optional[ParserProvider]:
        """
        Get a registered provider by name.

        Args:
            name: Provider name

        Returns:
            ParserProvider instance or None if not found
        """
        return self._providers.get(name)

    def list_providers(self) -> List[ParserProvider]:
        """
        List all registered providers.

        Returns:
            List of ParserProvider instances
        """
        return list(self._providers.values())

    def get_available_providers(self) -> List[ParserProvider]:
        """
        List all available providers (filtered by is_available()).

        Returns:
            List of available ParserProvider instances
        """
        return [p for p in self._providers.values() if p.is_available()]
