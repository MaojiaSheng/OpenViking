# Copyright (c) 2026 Beijing Volcano Engine Technology Co., Ltd.
# SPDX-License-Identifier: AGPL-3.0
"""
Parser Plugin Manager - Loads and manages parser plugins.

This module provides the PluginManager that discovers, loads, and manages
parser plugins. It maintains backward compatibility with existing parsers
while enabling new plugin-based extensions.
"""

from __future__ import annotations

import importlib
import logging
from pathlib import Path
from typing import Dict, List, Optional, Union

from openviking.parse.parsers.base_parser import BaseParser
from openviking.parse.plugin_base import (
    BuiltinParserProvider,
    ParserPluginContext,
    ParserProvider,
)

logger = logging.getLogger(__name__)


class ParserPluginManager:
    """
    Manages parser plugins and built-in parsers.

    Features:
    - Discovers and loads external parser plugins
    - Wraps built-in parsers as plugin providers
    - Caches parser instances
    - Maps file extensions to parsers
    - Maintains backward compatibility

    Example:
        manager = ParserPluginManager()
        manager.load_all()

        # Get a parser for a file
        parser = manager.get_parser_for_file("document.md")
        if parser:
            result = await parser.parse("document.md")
    """

    def __init__(self, plugins_dir: Optional[Union[str, Path]] = None):
        """
        Initialize the plugin manager.

        Args:
            plugins_dir: Directory to search for plugins. If None, uses
                        the default plugins/parser directory relative to
                        the openviking package.
        """
        self.plugins_dir = Path(plugins_dir) if plugins_dir else self._default_plugins_dir()
        self.context = ParserPluginContext()

        # Parser instance cache
        self._parser_cache: Dict[str, BaseParser] = {}

        # Extension map (ext -> provider_name)
        self._extension_map: Dict[str, str] = {}

        # Metadata for loaded plugins
        self._plugin_metadata: Dict[str, dict] = {}

        # Flag indicating if built-in parsers have been registered
        self._builtins_registered = False

    def _default_plugins_dir(self) -> Path:
        """
        Get the default plugins directory.

        Returns:
            Path to the default plugins/parser directory
        """
        try:
            import openviking

            # Try <project_root>/plugins/parser
            package_dir = Path(openviking.__file__).parent.parent
            plugins_dir = package_dir / "plugins" / "parser"
            if plugins_dir.exists():
                return plugins_dir

            # Fallback: try openviking/plugins/parser
            return Path(openviking.__file__).parent / "plugins" / "parser"
        except (ImportError, AttributeError):
            # If we can't find the package, return a reasonable default
            return Path("plugins") / "parser"

    def register_builtin_provider(
        self,
        name: str,
        parser_class: type,
        supported_extensions: List[str],
    ) -> None:
        """
        Register a built-in parser as a plugin provider.

        This allows existing parsers to participate in the plugin system
        without modification.

        Args:
            name: Parser name identifier
            parser_class: The parser class
            supported_extensions: List of supported file extensions
        """
        provider = BuiltinParserProvider(name, parser_class, supported_extensions)
        self.context.register_parser_provider(provider)

        # Update extension map (later registrations overwrite earlier ones,
        # matching the legacy ParserRegistry behavior)
        for ext in supported_extensions:
            ext_lower = ext.lower()
            if ext_lower in self._extension_map:
                logger.debug(
                    f"Extension {ext_lower} already mapped to {self._extension_map[ext_lower]}, "
                    f"overwriting with {name}"
                )
            self._extension_map[ext_lower] = name

    def discover_plugins(self) -> List[Path]:
        """
        Discover available parser plugins.

        Returns:
            List of plugin directories that contain a plugin.yaml file
        """
        if not self.plugins_dir.exists():
            logger.debug(f"Plugins directory not found: {self.plugins_dir}")
            return []

        plugins = []
        for plugin_dir in self.plugins_dir.iterdir():
            if plugin_dir.is_dir() and (plugin_dir / "plugin.yaml").exists():
                plugins.append(plugin_dir)

        logger.debug(f"Discovered {len(plugins)} parser plugins in {self.plugins_dir}")
        return plugins

    def load_plugin(self, plugin_dir: Union[str, Path]) -> bool:
        """
        Load a single parser plugin.

        Args:
            plugin_dir: Path to the plugin directory

        Returns:
            True if the plugin was loaded successfully, False otherwise
        """
        plugin_dir = Path(plugin_dir)
        plugin_name = plugin_dir.name
        meta_file = plugin_dir / "plugin.yaml"

        if not meta_file.exists():
            logger.warning(f"Plugin metadata not found: {meta_file}")
            return False

        # Load metadata
        try:
            import yaml

            with open(meta_file, encoding="utf-8") as f:
                metadata = yaml.safe_load(f) or {}
            self._plugin_metadata[plugin_name] = metadata
            logger.debug(f"Loaded metadata for plugin: {plugin_name}")
        except ImportError:
            logger.debug("PyYAML not available, skipping plugin metadata loading")
            metadata = {}
        except Exception as e:
            logger.warning(f"Failed to load plugin metadata {plugin_dir}: {e}")
            return False

        # Import and register the plugin
        try:
            # Add the plugin directory to the path temporarily if needed
            # Try importing with various module name patterns
            import_success = False
            module = None

            # Pattern 1: plugins.parser.<name>
            try:
                module_name = f"plugins.parser.{plugin_name}"
                module = importlib.import_module(module_name)
                import_success = True
            except ImportError:
                pass

            # Pattern 2: openviking.plugins.parser.<name>
            if not import_success:
                try:
                    module_name = f"openviking.plugins.parser.{plugin_name}"
                    module = importlib.import_module(module_name)
                    import_success = True
                except ImportError:
                    pass

            if not module:
                logger.debug(f"Could not import plugin module: {plugin_name}")
                return False

            # Call register function if present
            if hasattr(module, "register"):
                module.register(self.context)
                logger.debug(f"Called register() for plugin: {plugin_name}")

            # Update extension map for newly registered providers
            self._update_extension_map()

            plugin_display_name = metadata.get("name", plugin_name)
            logger.info(f"Loaded parser plugin: {plugin_display_name}")
            return True

        except Exception as e:
            logger.error(f"Failed to load plugin {plugin_dir}: {e}", exc_info=True)
            return False

    def _update_extension_map(self) -> None:
        """Update the extension map from registered providers."""
        for provider in self.context.list_providers():
            if provider.is_available():
                for ext in provider.supported_extensions:
                    ext_lower = ext.lower()
                    # Only set if not already set (preserves priority)
                    if ext_lower not in self._extension_map:
                        self._extension_map[ext_lower] = provider.name

    def load_all(self) -> None:
        """Load all available parser plugins."""
        for plugin_dir in self.discover_plugins():
            self.load_plugin(plugin_dir)

    def get_available_providers(self) -> List[ParserProvider]:
        """
        Get all available parser providers.

        Returns:
            List of ParserProvider instances where is_available() is True
        """
        return self.context.get_available_providers()

    def get_all_providers(self) -> List[ParserProvider]:
        """
        Get all registered parser providers (including unavailable ones).

        Returns:
            List of all registered ParserProvider instances
        """
        return self.context.list_providers()

    def get_provider(self, name: str) -> Optional[ParserProvider]:
        """
        Get a provider by name.

        Args:
            name: Provider name

        Returns:
            ParserProvider instance or None if not found
        """
        return self.context.get_provider(name)

    def get_parser(
        self,
        name: str,
        force_new: bool = False,
        **kwargs,
    ) -> Optional[BaseParser]:
        """
        Get a parser instance by name.

        Instances are cached by default. Use force_new=True to bypass the cache.

        Args:
            name: Parser name
            force_new: If True, create a new instance even if cached
            **kwargs: Configuration options passed to create_parser()

        Returns:
            BaseParser instance or None if not found or unavailable
        """
        cache_key = (name, tuple(sorted(kwargs.items())))

        if not force_new and cache_key in self._parser_cache:
            return self._parser_cache[cache_key]

        provider = self.context.get_provider(name)
        if provider and provider.is_available():
            parser = provider.create_parser(**kwargs)
            self._parser_cache[cache_key] = parser
            return parser

        return None

    def get_parser_for_file(
        self,
        path: Union[str, Path],
        **kwargs,
    ) -> Optional[BaseParser]:
        """
        Get an appropriate parser for a file.

        Args:
            path: File path
            **kwargs: Configuration options passed to create_parser()

        Returns:
            BaseParser instance or None if no suitable parser found
        """
        path = Path(path)
        ext = path.suffix.lower()
        parser_name = self._extension_map.get(ext)

        if parser_name:
            return self.get_parser(parser_name, **kwargs)

        return None

    def list_supported_extensions(self) -> List[str]:
        """
        List all supported file extensions.

        Returns:
            List of supported extensions (including the dot)
        """
        return list(self._extension_map.keys())

    def list_parsers(self) -> List[str]:
        """
        List all registered parser names.

        Returns:
            List of parser names
        """
        return [p.name for p in self.context.list_providers()]

    def clear_cache(self) -> None:
        """Clear the parser instance cache."""
        self._parser_cache.clear()
        logger.debug("Cleared parser cache")

    def get_metadata(self, plugin_name: str) -> Optional[dict]:
        """
        Get metadata for a loaded plugin.

        Args:
            plugin_name: Plugin name

        Returns:
            Plugin metadata dict or None if not found
        """
        return self._plugin_metadata.get(plugin_name)


# ============================================================================
# Global Manager Instance
# ============================================================================

_default_manager: Optional[ParserPluginManager] = None


def get_plugin_manager(
    plugins_dir: Optional[Union[str, Path]] = None,
    reload: bool = False,
) -> ParserPluginManager:
    """
    Get the global parser plugin manager.

    Args:
        plugins_dir: Optional plugins directory (only used on first call)
        reload: If True, create a new manager instance even if one exists

    Returns:
        The global ParserPluginManager instance
    """
    global _default_manager

    if reload or _default_manager is None:
        _default_manager = ParserPluginManager(plugins_dir=plugins_dir)

    return _default_manager
