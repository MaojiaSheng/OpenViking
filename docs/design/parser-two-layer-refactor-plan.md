# OpenViking 解析器两层架构重构计划

| 项目 | 信息 |
|-----|------|
| 状态 | `规划中` |
| 创建日期 | 2026-04-13 |
| 目标版本 | v6.0 |

---

## 一、问题分析

### 当前架构的问题

1. **平铺式注册**：所有 Parser 在同一层级，职责不清晰
2. **后缀冲突**：`.zip` 可被 `CodeRepositoryParser` 和 `ZipParser` 同时处理
3. **URL 处理逻辑分散**：`UnifiedResourceProcessor._process_url()` 和 `ParserRegistry.parse()` 都有 URL 检测
4. **职责混合**：部分 Parser 既负责下载又负责解析（如 `CodeRepositoryParser`, `HTMLParser`, `FeishuParser`）

---

## 二、新架构设计

### 核心概念

| 层级 | 抽象接口 | 职责 | 示例 |
|-----|---------|------|------|
| **L1** | `DataAccessor` | 获取数据：将远程 URL / 特殊路径 → 本地文件/目录 | GitAccessor, HTTPAccessor, FeishuAccessor |
| **L2** | `DataParser` | 解析数据：本地文件/目录 → `ParseResult` | MarkdownParser, PDFParser, DirectoryParser |
| **混合** | `HybridParser` | 同时实现两个接口（简化插件开发） | （按需使用） |

### 新的调用流程

```
add_resource(path)
    ↓
ResourceProcessor.process_resource()
    ↓
UnifiedResourceProcessor.process()  [重构]
    ↓
【第一阶段：数据访问】
AccessorRegistry.route(source)
    ├─→ 是 URL/远程资源?
    │     ├─→ GitAccessor (git@, git://, github.com, ...)
    │     ├─→ FeishuAccessor (.feishu.cn, .larksuite.com)
    │     ├─→ HTTPAccessor (http://, https://)
    │     └─→ 其他 → 下一步
    └─→ 返回: LocalResource (本地路径 + 元数据)
           ↓
【第二阶段：数据解析】
ParserRegistry.route(local_resource)
    ├─→ 是目录? → DirectoryParser
    ├─→ 是文件? → 按扩展名匹配
    │     ├─→ .md → MarkdownParser
    │     ├─→ .pdf → PDFParser
    │     ├─→ .zip → ZipParser
    │     └─→ ...
    └─→ 返回: ParseResult
           ↓
TreeBuilder + SemanticQueue (保持不变)
```

---

## 三、详细设计

### 3.1 核心抽象接口

#### 文件 1: `openviking/parse/accessors/base.py`

```python
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional, Dict, Any, Union
from dataclasses import dataclass

@dataclass
class LocalResource:
    """数据访问层的输出：表示可访问的本地资源"""
    path: Path                    # 本地文件/目录路径
    source_type: str              # 原始来源类型: "git", "http", "feishu", "local", ...
    original_source: str           # 原始 source 字符串
    meta: Dict[str, Any]          # 元数据（repo_name, branch, 等）
    is_temporary: bool = True      # 是否为临时文件，解析后可清理

class DataAccessor(ABC):
    """数据访问器：负责获取数据到本地"""

    @abstractmethod
    def can_handle(self, source: Union[str, Path]) -> bool:
        """判断是否能处理该来源"""
        pass

    @abstractmethod
    async def access(self, source: Union[str, Path], **kwargs) -> LocalResource:
        """
        获取数据到本地

        返回: LocalResource，包含本地路径和元数据
        """
        pass

    @property
    @abstractmethod
    def priority(self) -> int:
        """
        优先级，数字越大优先级越高
        用于解决冲突：多个 Accessor 都 can_handle 时，选优先级高的
        """
        pass

    def cleanup(self, resource: LocalResource) -> None:
        """
        清理临时资源（可选）
        默认：如果是临时资源，删除本地文件/目录
        """
        if resource.is_temporary:
            # 实现清理逻辑
            pass
```

#### 文件 2: `openviking/parse/parsers/base_parser.py` (重构)

```python
# 保持现有 BaseParser 接口，但明确其职责为 DataParser
# 可以考虑重命名为 DataParser 或保留 BaseParser 作为别名
```

#### 文件 3: `openviking/parse/accessors/registry.py`

```python
from typing import Union, Path, Optional, List
from .base import DataAccessor, LocalResource

class AccessorRegistry:
    """数据访问器注册表"""

    def __init__(self):
        self._accessors: List[DataAccessor] = []

    def register(self, accessor: DataAccessor) -> None:
        """注册访问器（按优先级插入）"""
        # 按 priority 降序插入
        idx = 0
        for i, a in enumerate(self._accessors):
            if accessor.priority > a.priority:
                idx = i
                break
        else:
            idx = len(self._accessors)
        self._accessors.insert(idx, accessor)

    def get_accessor(self, source: Union[str, Path]) -> Optional[DataAccessor]:
        """获取能处理该 source 的访问器（按优先级）"""
        for accessor in self._accessors:
            if accessor.can_handle(source):
                return accessor
        return None

    async def access(self, source: Union[str, Path], **kwargs) -> LocalResource:
        """
        路由到合适的访问器获取数据

        如果没有访问器能处理，视为本地文件返回
        """
        accessor = self.get_accessor(source)
        if accessor:
            return await accessor.access(source, **kwargs)

        # 默认：视为本地文件
        path = Path(source)
        return LocalResource(
            path=path,
            source_type="local",
            original_source=str(source),
            meta={},
            is_temporary=False
        )
```

### 3.2 现有 Parser 拆分方案

| 当前 Parser | 拆分后 | 说明 |
|-----------|--------|------|
| `CodeRepositoryParser` | `GitAccessor` + `DirectoryParser` | Git clone 逻辑移到 Accessor |
| `HTMLParser` | `HTTPAccessor` + `HTMLParser` | HTTP 下载移到 Accessor |
| `FeishuParser` | `FeishuAccessor` + (新) `FeishuDocumentParser` | 飞书 API 调用移到 Accessor |
| `ZipParser` | 保持为 `DataParser` | 只处理本地 .zip 文件 |
| `DirectoryParser` | 保持为 `DataParser` | 只处理本地目录 |
| 其他 (Markdown, PDF, ...) | 保持为 `DataParser` | 无需变动 |

### 3.3 Accessor 实现示例

#### `GitAccessor` (`openviking/parse/accessors/git.py`)

```python
# 从 CodeRepositoryParser 提取 git clone / GitHub ZIP 下载逻辑
```

#### `HTTPAccessor` (`openviking/parse/accessors/http.py`)

```python
# 从 HTMLParser 提取下载逻辑
# 支持内容类型检测，下载到临时文件
```

#### `FeishuAccessor` (`openviking/parse/accessors/feishu.py`)

```python
# 从 FeishuParser 提取 API 调用逻辑
```

### 3.4 HybridParser（简化插件开发）

对于简单的插件，允许同时实现两个接口：

```python
class HybridParser(DataAccessor, DataParser):
    """
    混合解析器：同时实现访问和解析
    适用于简单的自定义解析器，不需要拆分
    """
    # 同时实现 DataAccessor 和 DataParser 的接口
    pass
```

---

## 四、实施步骤

### Phase 1: 基础设施（核心接口）

**目标**：建立新架构的基础框架，不影响现有功能

- [ ] 创建 `openviking/parse/accessors/` 目录结构
- [ ] 实现 `DataAccessor` 抽象基类和 `LocalResource` 数据类
- [ ] 实现 `AccessorRegistry`
- [ ] 编写单元测试
- [ ] 更新 `ParserRegistry`，保持向后兼容

### Phase 2: 重构 CodeRepositoryParser

**目标**：将 CodeRepositoryParser 拆分为 GitAccessor + DirectoryParser

- [ ] 实现 `GitAccessor`（从 `CodeRepositoryParser` 提取 clone/download 逻辑）
- [ ] 更新 `CodeRepositoryParser` 为混合模式（向后兼容）或标记为 deprecated
- [ ] 在 `AccessorRegistry` 中注册 `GitAccessor`
- [ ] 更新 `UnifiedResourceProcessor.process()` 使用新流程
- [ ] 测试：Git URL, GitHub URL, 本地 .zip 等场景

### Phase 3: 重构 HTMLParser 和 FeishuParser

- [ ] 实现 `HTTPAccessor`
- [ ] 实现 `FeishuAccessor`
- [ ] 重构 `HTMLParser` 只负责解析本地 HTML 文件
- [ ] 重构 `FeishuParser` 只负责解析下载后的内容

### Phase 4: 重构 UnifiedResourceProcessor

**目标**：简化 `UnifiedResourceProcessor`，使用新的两层架构

- [ ] 重构 `UnifiedResourceProcessor.process()`：
  ```python
  async def process(self, source, ...):
      # 第一阶段：获取数据
      local_resource = await accessor_registry.access(source, **kwargs)

      # 第二阶段：解析数据
      parse_result = await parser_registry.parse(local_resource, **kwargs)

      # 清理（如果需要）
      # ...

      return parse_result
  ```
- [ ] 移除 `_process_url()`, `_process_file()`, `_process_directory()` 中的重复逻辑

### Phase 5: 扩展和优化

- [ ] 实现优先级机制解决冲突
- [ ] 添加 `HybridParser` 支持
- [ ] 编写迁移文档
- [ ] 性能优化和测试覆盖

---

## 五、兼容性策略

### 5.1 向后兼容

1. **保持现有 API 不变**：
   - `ParserRegistry` 接口保持不变
   - `registry.parse()` 仍然可以工作
   - 自定义 Parser 注册方式不变

2. **渐进式迁移**：
   - 现有 Parser 可以继续使用
   - 新 Parser 鼓励使用新架构
   - 提供迁移指南

### 5.2 废弃策略

- 标记旧的 `CodeRepositoryParser` 等为 `@deprecated`
- 在 v6.0 或未来版本移除

---

## 六、文件结构变更

```
openviking/parse/
├── accessors/              [新增]
│   ├── __init__.py
│   ├── base.py            # DataAccessor, LocalResource
│   ├── registry.py        # AccessorRegistry
│   ├── git.py             # GitAccessor
│   ├── http.py            # HTTPAccessor
│   └── feishu.py          # FeishuAccessor
├── parsers/
│   ├── base_parser.py     # 明确为 DataParser
│   ├── code/              # 保留但简化
│   ├── markdown.py
│   ├── pdf.py
│   └── ...
├── registry.py            # ParserRegistry (重构)
└── ...
```

---

## 七、测试计划

| 测试类型 | 测试内容 |
|---------|---------|
| 单元测试 | AccessorRegistry, 各 Accessor, 各 Parser |
| 集成测试 | 完整流程：add_resource → Accessor → Parser → TreeBuilder |
| 回归测试 | 确保现有功能不被破坏 |
| 冲突测试 | 测试优先级机制解决 .zip, URL 等冲突场景 |

---

## 八、风险与应对

| 风险 | 影响 | 概率 | 应对措施 |
|-----|------|------|---------|
| 重构范围过大 | 高 | 中 | 分阶段实施，每阶段可独立发布 |
| 性能回退 | 中 | 低 | 保持缓存机制，性能基准测试 |
| 自定义插件受影响 | 高 | 低 | 保持向后兼容，提供迁移工具 |

---

## 九、相关文档

- [解析系统 README](../../openviking/parse/parsers/README.md)
- [OpenViking 整体架构](../zh/concepts/01-architecture.md)
