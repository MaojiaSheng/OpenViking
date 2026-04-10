# OpenViking Parse 模块插件化重构方案

## 一、现状分析

### 1.1 当前架构

```
openviking/parse/
├── __init__.py           # 导出所有 parser
├── base.py               # ParseResult, ResourceNode 等数据结构
├── registry.py           # ParserRegistry (硬编码注册所有 parser)
├── parsers/
│   ├── base_parser.py    # BaseParser ABC
│   ├── markdown.py       # MarkdownParser
│   ├── pdf.py            # PDFParser
│   ├── html.py           # HTMLParser
│   ├── text.py           # TextParser
│   ├── code/             # CodeRepositoryParser
│   ├── media/            # Image/Audio/VideoParser
│   └── ...               # 其他 10+ 个 parsers
```

### 1.2 存在的问题

| 问题 | 影响 |
|------|------|
| **硬编码注册** | `registry.py` 手动 import 并注册每个 parser |
| **可选依赖处理混乱** | FeishuParser 等用 try-except ImportError 包装 |
| **难以扩展** | 添加新 parser 需要修改核心代码 |
| **难以测试** | 核心代码耦合太多 parser 实现 |
| **版本管理困难** | 各 parser 版本绑定在一起 |

---

## 二、重构目标

1. **向后兼容** - 保持现有 API 不变
2. **渐进迁移** - 可以分批迁移 parsers
3. **灵活扩展** - 第三方可独立开发 parser 插件
4. **依赖隔离** - 可选依赖真正可选

---

## 三、新架构设计

### 3.1 目录结构

```
openviking/
├── parse/
│   ├── __init__.py
│   ├── base.py                    # 保持不变
│   ├── registry.py                # 重构为 PluginRegistry
│   ├── plugin_base.py             # [新] ParserProvider ABC
│   ├── plugin_manager.py          # [新] PluginManager
│   └── parsers/                   # 内置 parsers（可逐步迁移）
│       ├── base_parser.py
│       ├── markdown.py
│       └── ...
└── plugins/                       # [新] 插件目录
    ├── __init__.py
    └── parser/
        ├── builtin/               # 内置 parsers 迁移到这里
        │   ├── markdown/
        │   │   ├── __init__.py
        │   │   └── plugin.yaml
        │   ├── pdf/
        │   └── ...
        └── feishu/                # 可选 parser 作为独立插件
            ├── __init__.py
            ├── plugin.yaml
            └── requirements.txt
```

### 3.2 核心类设计

```python
# openviking/parse/plugin_base.py

from abc import ABC, abstractmethod
from pathlib import Path
from typing import List, Optional, Union, Dict, Any

from openviking.parse.base import ParseResult
from openviking.parse.parsers.base_parser import BaseParser


class ParserProvider(ABC):
    """Parser 插件提供者抽象基类"""

    @property
    @abstractmethod
    def name(self) -> str:
        """Parser 唯一标识"""

    @abstractmethod
    def is_available(self) -> bool:
        """检查依赖是否满足，不做网络调用"""

    @abstractmethod
    def create_parser(self, **kwargs) -> BaseParser:
        """创建 Parser 实例"""

    def get_config_schema(self) -> List[Dict[str, Any]]:
        """返回配置字段定义"""
        return []

    @property
    def supported_extensions(self) -> List[str]:
        """支持的文件扩展名"""
        return []

    def can_handle(self, path: Union[str, Path]) -> bool:
        """检查是否能处理该文件"""
        path = Path(path)
        return path.suffix.lower() in self.supported_extensions
```

---

## 四、迁移策略

### 4.1 阶段一：基础设施（兼容层）

保持 `ParserRegistry` API 不变，内部使用新的插件系统：

```python
# openviking/parse/registry.py (重构后)

from openviking.parse.plugin_manager import ParserPluginManager

# 全局插件管理器
_plugin_manager: Optional[ParserPluginManager] = None


class ParserRegistry:
    """保持原有接口，内部委托给 PluginManager"""

    def __init__(self, register_optional: bool = True):
        self._manager = get_plugin_manager()

        # 兼容：仍然支持旧的 register 方法
        self._parsers: Dict[str, BaseParser] = {}
        self._extension_map: Dict[str, str] = {}

        # 加载内置 parsers（兼容旧代码）
        self._load_builtin_parsers()

        # 加载插件 parsers
        self._load_plugin_parsers()

    def register(self, name: str, parser: BaseParser) -> None:
        """保持向后兼容"""
        self._parsers[name] = parser
        for ext in parser.supported_extensions:
            self._extension_map[ext.lower()] = name

    async def parse(self, source: Union[str, Path], **kwargs) -> ParseResult:
        """保持原有 API，优先尝试插件 parser"""
        # 先尝试插件系统
        plugin_parser = self._manager.get_parser_for_file(source)
        if plugin_parser:
            return await plugin_parser.parse(source, **kwargs)

        # 回退到旧系统
        # ... 原有逻辑 ...
```

### 4.2 阶段二：迁移内置 Parsers

以 MarkdownParser 为例，迁移为插件：

```python
# plugins/parser/markdown/__init__.py

from openviking.parse.plugin_base import ParserProvider
from openviking.parse.parsers.markdown import MarkdownParser


class MarkdownParserProvider(ParserProvider):

    @property
    def name(self) -> str:
        return "markdown"

    def is_available(self) -> bool:
        # MarkdownParser 无外部依赖
        return True

    def create_parser(self, **kwargs) -> BaseParser:
        return MarkdownParser(**kwargs)

    @property
    def supported_extensions(self) -> List[str]:
        return [".md", ".markdown", ".mdown", ".mkd"]


def register(ctx):
    ctx.register_parser_provider(MarkdownParserProvider())
```

```yaml
# plugins/parser/markdown/plugin.yaml
name: markdown
version: "1.0.0"
description: "Markdown document parser"
category: "parser"
```

### 4.3 阶段三：可选 Parser 独立化

FeishuParser 作为可选插件示例：

```python
# plugins/parser/feishu/__init__.py

from openviking.parse.plugin_base import ParserProvider


class FeishuParserProvider(ParserProvider):

    @property
    def name(self) -> str:
        return "feishu"

    def is_available(self) -> bool:
        try:
            import lark_oapi
            return True
        except ImportError:
            return False

    def create_parser(self, **kwargs) -> BaseParser:
        from openviking.parse.parsers.feishu import FeishuParser
        return FeishuParser(**kwargs)

    def get_config_schema(self) -> List[Dict[str, Any]]:
        return [
            {
                "key": "app_id",
                "description": "Feishu App ID",
                "secret": True,
                "env_var": "FEISHU_APP_ID",
            },
            {
                "key": "app_secret",
                "description": "Feishu App Secret",
                "secret": True,
                "env_var": "FEISHU_APP_SECRET",
            },
        ]


def register(ctx):
    ctx.register_parser_provider(FeishuParserProvider())
```

```yaml
# plugins/parser/feishu/plugin.yaml
name: feishu
version: "1.0.0"
description: "Feishu/Lark document parser"
category: "parser"
pip_dependencies:
  - lark_oapi>=1.0.0
```

---

## 五、PluginManager 实现

```python
# openviking/parse/plugin_manager.py

import importlib
import yaml
import logging
from pathlib import Path
from typing import Dict, List, Optional, Union

from openviking.parse.plugin_base import ParserProvider
from openviking.parse.parsers.base_parser import BaseParser

logger = logging.getLogger(__name__)


class ParserPluginContext:
    """插件注册上下文"""

    def __init__(self):
        self._providers: Dict[str, ParserProvider] = {}

    def register_parser_provider(self, provider: ParserProvider):
        """注册一个 parser provider"""
        self._providers[provider.name] = provider
        logger.info(f"Registered parser provider: {provider.name}")


class ParserPluginManager:
    """Parser 插件管理器"""

    def __init__(self, plugins_dir: Optional[Union[str, Path]] = None):
        self.plugins_dir = Path(plugins_dir) if plugins_dir else self._default_plugins_dir()
        self.context = ParserPluginContext()
        self._parser_cache: Dict[str, BaseParser] = {}
        self._extension_map: Dict[str, str] = {}

    def _default_plugins_dir(self) -> Path:
        """获取默认插件目录"""
        import openviking
        return Path(openviking.__file__).parent.parent / "plugins" / "parser"

    def discover_plugins(self) -> List[Path]:
        """发现所有可用的 parser 插件"""
        if not self.plugins_dir.exists():
            return []

        plugins = []
        for plugin_dir in self.plugins_dir.iterdir():
            if plugin_dir.is_dir() and (plugin_dir / "plugin.yaml").exists():
                plugins.append(plugin_dir)
        return plugins

    def load_plugin(self, plugin_dir: Union[str, Path]) -> bool:
        """加载单个插件"""
        plugin_dir = Path(plugin_dir)
        meta_file = plugin_dir / "plugin.yaml"

        if not meta_file.exists():
            return False

        # 加载元数据
        try:
            with open(meta_file) as f:
                metadata = yaml.safe_load(f)
        except Exception as e:
            logger.warning(f"Failed to load plugin metadata {plugin_dir}: {e}")
            return False

        # 导入并注册
        try:
            # 假设插件在 Python path 中
            module_name = f"plugins.parser.{plugin_dir.name}"
            module = importlib.import_module(module_name)
            if hasattr(module, "register"):
                module.register(self.context)

            # 构建扩展名映射
            for name, provider in self.context._providers.items():
                if provider.is_available():
                    for ext in provider.supported_extensions:
                        self._extension_map[ext.lower()] = name

            logger.info(f"Loaded parser plugin: {metadata.get('name', plugin_dir.name)}")
            return True
        except Exception as e:
            logger.error(f"Failed to load plugin {plugin_dir}: {e}")
            return False

    def load_all(self):
        """加载所有插件"""
        for plugin_dir in self.discover_plugins():
            self.load_plugin(plugin_dir)

    def get_available_providers(self) -> List[ParserProvider]:
        """获取所有可用的 providers"""
        return [
            p for p in self.context._providers.values()
            if p.is_available()
        ]

    def get_parser(self, name: str, **kwargs) -> Optional[BaseParser]:
        """获取 parser 实例（带缓存）"""
        if name in self._parser_cache:
            return self._parser_cache[name]

        provider = self.context._providers.get(name)
        if provider and provider.is_available():
            parser = provider.create_parser(**kwargs)
            self._parser_cache[name] = parser
            return parser
        return None

    def get_parser_for_file(self, path: Union[str, Path]) -> Optional[BaseParser]:
        """获取适合该文件的 parser"""
        path = Path(path)
        ext = path.suffix.lower()
        parser_name = self._extension_map.get(ext)
        if parser_name:
            return self.get_parser(parser_name)
        return None


# 全局实例
_default_manager: Optional[ParserPluginManager] = None


def get_plugin_manager() -> ParserPluginManager:
    """获取全局插件管理器"""
    global _default_manager
    if _default_manager is None:
        _default_manager = ParserPluginManager()
        _default_manager.load_all()
    return _default_manager
```

---

## 六、迁移检查清单

### 基础设施层
- [ ] 创建 `plugin_base.py`
- [ ] 创建 `plugin_manager.py`
- [ ] 重构 `registry.py` 为兼容层
- [ ] 编写单元测试

### 内置 Parsers 迁移（按优先级）
- [ ] markdown
- [ ] text
- [ ] html
- [ ] pdf
- [ ] code
- [ ] directory
- [ ] zip
- [ ] media (image/audio/video)
- [ ] office (word/excel/powerpoint)
- [ ] epub
- [ ] legacy_doc

### 可选 Parsers 独立化
- [ ] feishu
- [ ] 其他未来的可选 parser

### 文档和示例
- [ ] 更新 `CONTRIBUTING.md`
- [ ] 编写插件开发指南
- [ ] 创建示例插件模板

---

## 七、向后兼容保证

1. **API 不变** - `ParserRegistry` 类接口保持完全一致
2. **导入路径不变** - `from openviking.parse import parse, get_registry` 继续工作
3. **渐进迁移** - 旧的 `parsers/` 目录保留，新系统优先用插件
4. **回退机制** - 插件加载失败时回退到旧实现

---

## 八、收益

| 收益 | 说明 |
|------|------|
| **更清晰的依赖** | 可选依赖真正可选，不需要 try-except 包装 |
| **更容易扩展** | 第三方可以独立开发 parser 插件 |
| **更易测试** | 可以 mock 任意 parser |
| **更灵活的发布** | parser 可以独立版本发布 |
| **更小的核心包** | 可选 parser 可以单独安装 |

# Parser 插件系统快速开始指南

## 概述

OpenViking 的 parse 模块支持插件系统，允许：
- 独立开发自定义 parser
- 可选依赖隔离
- 通过 `plugins.{name}` 配置插件

## 目录结构

```
OpenViking/
├── plugins/
│   ├── __init__.py
│   └── parser/
│       ├── __init__.py
│       └── feishu/              # 示例插件
│           ├── __init__.py
│           ├── plugin.yaml
│           ├── feishu.py
│           └── README.md
└── openviking/
    └── parse/
        ├── plugin_base.py        # ParserProvider 抽象基类
        ├── plugin_manager.py     # ParserPluginManager
        └── registry.py           # 兼容层 + 插件集成
```

## 快速使用

### 方式一：继续使用旧 API（完全兼容）

```python
from openviking.parse import parse, get_registry

# 和以前一样使用
result = await parse("document.md")

registry = get_registry()
parser = registry.get_parser("markdown")
```

### 方式二：使用新的插件 API

```python
from openviking.parse import get_plugin_manager

# 直接使用 PluginManager
manager = get_plugin_manager()

# 获取所有可用的 providers
providers = manager.get_available_providers()
print(f"Available parsers: {[p.name for p in providers]}")

# 获取 parser
parser = manager.get_parser("markdown")
if parser:
    result = await parser.parse("document.md")
```

## 开发自定义 Parser 插件

### 示例：创建一个自定义 JSON Parser 插件

```
plugins/parser/json_parser/
├── __init__.py
├── plugin.yaml
├── json_parser.py
└── README.md
```

**plugin.yaml**
```yaml
name: json_parser
version: "1.0.0"
description: "JSON document parser"
category: "parser"
```

**json_parser.py**
```python
from openviking.parse.parsers.base_parser import BaseParser
from openviking.parse.base import (
    ParseResult,
    ResourceNode,
    NodeType,
    create_parse_result,
)
from pathlib import Path
from typing import List, Union
import json


class JSONParser(BaseParser):
    """Simple JSON parser that pretty-prints JSON."""

    @property
    def supported_extensions(self) -> List[str]:
        return [".json"]

    async def parse(self, source: Union[str, Path], instruction: str = "", **kwargs) -> ParseResult:
        path = Path(source)
        if path.exists():
            content = self._read_file(path)
        else:
            content = str(source)
        return await self.parse_content(content, source_path=str(source) if path.exists() else None)

    async def parse_content(self, content: str, source_path: str = None, instruction: str = "", **kwargs) -> ParseResult:
        # Parse and pretty-print
        data = json.loads(content)
        pretty_content = json.dumps(data, indent=2, ensure_ascii=False)

        root = ResourceNode(
            type=NodeType.ROOT,
            title="JSON Document",
            level=0,
        )

        return create_parse_result(
            root=root,
            source_path=source_path,
            source_format="json",
            parser_name="JSONParser",
        )
```

**__init__.py**
```python
from openviking.parse.plugin_base import ParserProvider, ParserPluginContext
from openviking.parse.parsers.base_parser import BaseParser
from typing import List
from .json_parser import JSONParser


class JSONParserProvider(ParserProvider):

    @property
    def name(self) -> str:
        return "json_parser"

    def is_available(self) -> bool:
        # No extra dependencies needed
        return True

    def create_parser(self, **kwargs) -> BaseParser:
        return JSONParser(**kwargs)

    @property
    def supported_extensions(self) -> List[str]:
        return [".json"]


def register(ctx: ParserPluginContext):
    ctx.register_parser_provider(JSONParserProvider())
```

## 插件配置

插件配置通过 `ov.conf` 中的 `plugins` 字段进行：

```json
{
  "plugins": {
    "feishu": {
      "app_id": "your_app_id",
      "app_secret": "your_app_secret",
      "domain": "https://open.feishu.cn"
    }
  }
}
```

在插件中读取配置：

```python
from openviking_cli.utils.config import get_openviking_config
from openviking_cli.utils.config.parser_config import FeishuConfig

config = get_openviking_config()
plugin_config = config.plugins.get("feishu", {})
feishu_config = FeishuConfig.from_dict(plugin_config)
```

## 架构说明

### 关键类

| 类 | 说明 |
|---|---|
| `ParserProvider` | 插件提供者 ABC，用于创建新 parser 插件 |
| `ParserPluginContext` | 插件注册上下文 |
| `ParserPluginManager` | 插件管理器，负责发现、加载插件 |
| `BuiltinParserProvider` | 包装现有 parser 为插件的适配器 |
| `ParserRegistry` | 保持兼容，内部使用 PluginManager |

### 扩展注册规则

- 后注册的 parser 会覆盖先注册的 parser 的相同扩展名
- 这与旧的 `ParserRegistry` 行为保持一致

## 参考实现

完整的插件实现示例请参考 `plugins/parser/feishu/` 目录。
