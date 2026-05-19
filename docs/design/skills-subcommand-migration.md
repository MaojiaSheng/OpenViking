# OpenViking Skill 子命令改造方案：对齐 Vercel Labs Skills CLI 风格

## 1. 背景与动机

### 1.1 行业趋势

Agent Skills 已成为 AI Agent 生态的开放标准（[agentskills.io](https://agentskills.io)），由 Anthropic 首创并已被 50+ Agent 产品采纳（Claude Code、Cursor、VS Code Copilot、Gemini CLI、Codex、Roo Code、Junie、Goose 等）。Vercel Labs 推出的 [skills CLI](https://github.com/vercel-labs/skills) 提供了跨 Agent 的技能管理工具链，形成了技能发现、安装、分发的事实标准。

### 1.2 OpenViking 现状

OpenViking 当前将 Skill 视为一种特殊的资源类型，管理能力分散在通用文件系统命令中：

| 操作 | 当前方式 | 问题 |
|------|---------|------|
| 添加技能 | `ov add-skill` | 仅支持添加，无来源概念 |
| 列出技能 | `ov ls viking://agent/skills/` | 使用通用 ls，无技能专属信息 |
| 搜索技能 | `ov find "query" --uri viking://agent/skills/` | 使用通用 find，非技能语义 |
| 读取技能 | `ov read viking://agent/skills/xxx/SKILL.md` | 需要手动拼 URI |
| 删除技能 | `ov rm viking://agent/skills/xxx/ --recursive` | 使用通用 rm，无安全确认 |
| 更新技能 | 无 | 不支持 |
| 初始化技能 | 无 | 不支持 |
| 发现技能 | 无 | 不支持 |

核心痛点：技能管理能力碎片化、缺乏技能生命周期管理、与 Agent Skills 生态不互通。

### 1.3 改造目标

将 OpenViking 所有 Skill 相关能力改造为 `ov skills` 子命令风格，对标 Vercel Labs Skills CLI，同时保留 OpenViking 的差异化优势（服务端知识库、语义搜索、MCP 转换、渐进式摘要）。

---

## 2. Agent Skills 规范摘要

### 2.1 SKILL.md 格式

```markdown
---
name: skill-name
description: What this skill does and when to use it
license: Apache-2.0
compatibility: Requires Python 3.14+ and uv
metadata:
  author: example-org
  version: "1.0"
  internal: true
allowed-tools: Bash(git:*) Bash(jq:*) Read
---

# Skill Name

Instructions for the agent...
```

**Frontmatter 字段规范：**

| 字段 | 必填 | 约束 |
|------|------|------|
| `name` | 是 | 最大 64 字符，小写字母+数字+连字符，不能以连字符开头/结尾，不能连续连字符，必须匹配父目录名 |
| `description` | 是 | 最大 1024 字符，描述技能功能和触发场景 |
| `license` | 否 | 许可证名称或许可文件引用 |
| `compatibility` | 否 | 最大 500 字符，环境要求说明 |
| `metadata` | 否 | 任意键值对，用于扩展元数据 |
| `allowed-tools` | 否 | 空格分隔的预授权工具列表（实验性） |

### 2.2 技能目录结构

```
skill-name/
├── SKILL.md          # 必需：元数据 + 指令
├── scripts/          # 可选：可执行代码
├── references/       # 可选：参考文档
├── assets/           # 可选：模板、资源
└── ...               # 其他辅助文件
```

### 2.3 渐进式披露（Progressive Disclosure）

| 层级 | 加载内容 | 时机 | Token 开销 |
|------|---------|------|-----------|
| Tier 1：目录 | name + description | 会话启动 | ~50-100 tokens/技能 |
| Tier 2：指令 | 完整 SKILL.md body | 技能被激活时 | <5000 tokens（推荐） |
| Tier 3：资源 | scripts/, references/, assets/ | 指令引用时按需加载 | 不定 |

### 2.4 技能发现路径

行业标准发现路径（按优先级）：

| 范围 | 路径 | 用途 |
|------|------|------|
| 用户级 | `~/.agents/skills/` | 跨 Agent 全局路径 |
| 用户级 | `~/.claude/skills/` | Claude Code 全局路径 |

> **注意**：Vercel Labs Skills CLI 还扫描项目级目录（`<project>/.agents/skills/` 等），但 OpenViking 服务端不设"项目级"技能存储，仅区分全局共享和用户私有两类（见 §5）。

### 2.5 Plugin Manifest 发现

如果存在 `.claude-plugin/marketplace.json` 或 `.claude-plugin/plugin.json`，其中声明的技能也会被发现：

```json
{
  "metadata": { "pluginRoot": "./plugins" },
  "plugins": [
    {
      "name": "my-plugin",
      "source": "my-plugin",
      "skills": ["./skills/review", "./skills/test"]
    }
  ]
}
```

---

## 3. 命令设计

### 3.1 总览

将现有的分散式技能操作统一到 `ov skills` 子命令下：

```
ov skills <subcommand> [options]

子命令：
  add       从来源安装技能
  list      列出已安装的技能
  find      搜索技能
  update    更新已安装的技能
  init      创建新技能模板
  remove    移除已安装的技能
  show      查看技能详情（OpenViking 增强）
  validate  验证 SKILL.md 格式（OpenViking 增强）
```

### 3.2 技能可见性模型

依据 OpenViking 多租户架构（参见 [多租户文档](../concepts/11-multi-tenant.md)），技能在服务端只有两类存储位置：

| 可见性 | URI 模式 | 说明 |
|--------|---------|------|
| **全局共享** | `viking://agent/skills/<name>/` | account 内所有用户可见，类似公共工具箱 |
| **用户私有** | `viking://user/{user_space}/skills/<name>/` | 仅当前用户可见，类似个人工具箱 |

所有 `ov skills` 子命令通过 `--user` 参数区分两类：

- **不加 `--user`**（默认）：操作全局共享空间
- **加 `--user`**：操作当前用户私有空间

这对应 OpenViking 多租户中 `resources`（account 内共享）和 `user`（用户隔离）的既有边界。检索层也会自动按当前身份过滤——全局技能对 account 内所有用户可见，用户私有技能仅对拥有者可见。

### 3.3 `ov skills add` — 安装技能

从来源安装技能到 OpenViking 知识库。

```bash
ov skills add <source> [options]
```

**参数：**

| 参数 | 短选项 | 说明 |
|------|--------|------|
| `<source>` | — | 技能来源（见下方来源格式） |
| `--skill <names...>` | `-s` | 指定安装的技能名（`*` 表示全部） |
| `--user` | `-u` | 安装到用户私有空间而非全局共享空间 |
| `--list` | `-l` | 仅列出可用技能，不安装 |
| `--wait` | `-w` | 等待语义处理完成 |
| `--yes` | `-y` | 跳过确认提示 |

**来源格式：**

| 格式 | 示例 |
|------|------|
| GitHub 简写 | `owner/repo` |
| GitHub 完整 URL | `https://github.com/owner/repo` |
| 仓库内子目录 | `.../tree/main/skills/my-skill` |
| Git URL | `git@github.com:owner/repo.git` |
| 本地路径 | `./my-skills` 或 `./my-skill/SKILL.md` |
| OpenViking URI | `viking://agent/skills/my-skill` |
| MCP Tool 定义 | `mcp://server/tool-name`（实验性） |

**行为说明：**

1. **默认（无 `--user`）**：技能存入全局共享空间 `viking://agent/skills/<name>/`，account 内所有用户可见
2. **加 `--user`**：技能存入当前用户私有空间 `viking://user/{user_space}/skills/<name>/`，仅当前用户可见
3. **来源为 MCP Tool**：自动检测 `inputSchema` 并转换为 SKILL.md 格式（保留现有 MCP 转换能力）
4. **来源为 OpenViking URI**：从知识库中复制技能到目标空间

**示例：**

```bash
# 从 GitHub 仓库安装技能到全局共享空间
ov skills add vercel-labs/agent-skills

# 安装到用户私有空间（仅自己可见）
ov skills add ./skills/my-skill/ --user

# 列出仓库中的可用技能
ov skills add vercel-labs/agent-skills --list

# 安装指定技能
ov skills add vercel-labs/agent-skills -s frontend-design

# 从本地目录安装
ov skills add ./skills/my-skill/

# MCP Tool 转换安装
ov skills add mcp://web-server/search-web

# 等待语义处理完成
ov skills add ./skills/my-skill/ --wait

# 非交互式全量安装
ov skills add vercel-labs/agent-skills --all
```

**与现有 `ov add-skill` 的关系：**

- `ov add-skill <path>` → `ov skills add <path>`（旧命令保留为别名，标记为 deprecated）
- 新增来源格式支持（GitHub、Git URL、OpenViking URI、MCP）
- 新增 `--user` 参数区分全局/用户私有空间
- 新增 `--skill` 筛选指定技能

### 3.4 `ov skills list`（别名 `ls`）— 列出技能

列出 OpenViking 知识库中的技能。

```bash
ov skills list [options]
```

**参数：**

| 参数 | 短选项 | 说明 |
|------|--------|------|
| `--user` | `-u` | 仅显示用户私有空间技能 |
| `--format <fmt>` | `-o` | 输出格式：`table`（默认）、`json`、`simple` |

**示例：**

```bash
# 列出全局共享技能（默认）
ov skills list

# 列出当前用户私有空间的技能
ov skills list --user

# 同时列出全局和用户私有技能
ov skills list && ov skills list --user

# JSON 格式输出
ov skills list -o json
```

**与现有方式的对比：**

| 现有 | 改造后 |
|------|--------|
| `ov ls viking://agent/skills/` | `ov skills list` |
| `ov ls viking://agent/skills/ --simple` | `ov skills list -o simple` |
| `ov ls viking://user/{user_space}/skills/` | `ov skills list --user` |

### 3.5 `ov skills find` — 搜索技能

搜索技能（语义搜索 + 关键词匹配）。

```bash
ov skills find [query] [options]
```

**参数：**

| 参数 | 短选项 | 说明 |
|------|--------|------|
| `[query]` | — | 搜索关键词（省略则交互式搜索） |
| `--user` | `-u` | 搜索范围限定为用户私有空间 |
| `--limit <n>` | `-n` | 结果数量限制（默认 10） |
| `--threshold <f>` | `-t` | 语义相关性阈值（默认 0.3） |
| `--format <fmt>` | `-o` | 输出格式 |

**示例：**

```bash
# 语义搜索全局技能
ov skills find "search the internet"

# 搜索用户私有技能
ov skills find "my tool" --user

# 交互式搜索
ov skills find

# 限制结果数
ov skills find "code review" -n 5
```

**与现有方式的对比：**

| 现有 | 改造后 |
|------|--------|
| `ov find "search the internet" --uri viking://agent/skills/` | `ov skills find "search the internet"` |

### 3.6 `ov skills update` — 更新技能

更新已安装的技能到最新版本。

```bash
ov skills update [skills...] [options]
```

**参数：**

| 参数 | 短选项 | 说明 |
|------|--------|------|
| `[skills...]` | — | 指定更新的技能名（空则更新全部） |
| `--user` | `-u` | 仅更新用户私有空间技能 |
| `--yes` | `-y` | 跳过确认提示 |
| `--wait` | `-w` | 等待语义处理完成 |

**示例：**

```bash
# 更新所有全局技能
ov skills update

# 更新指定技能
ov skills update search-web code-review

# 仅更新用户私有空间的技能
ov skills update --user

# 非交互式更新
ov skills update -y
```

**实现说明：**

对于从 Git 来源安装的技能，`update` 会拉取最新版本并重新处理。对于从本地上传的技能，`update` 会重新扫描源路径（如果仍存在）或提示用户指定新来源。OpenViking 的 `watch_interval` 机制作为自动更新的补充。

### 3.7 `ov skills init` — 初始化技能

创建新的 SKILL.md 模板。

```bash
ov skills init [name] [options]
```

**参数：**

| 参数 | 短选项 | 说明 |
|------|--------|------|
| `[name]` | — | 技能名称（在当前目录或子目录创建） |
| `--user` | `-u` | 创建到用户私有空间并添加到知识库 |

**示例：**

```bash
# 在当前目录创建 SKILL.md
ov skills init

# 创建名为 my-skill 的技能（含子目录）
ov skills init my-skill

# 创建到用户私有空间并添加到知识库
ov skills init my-skill --user

# 创建到全局共享空间并添加到知识库
ov skills init my-skill && ov skills add ./my-skill/
```

**生成的模板：**

```markdown
---
name: my-skill
description: Brief description of what this skill does and when to use it
---

# My Skill

Instructions for the agent to follow when this skill is activated.

## When to Use

Describe the scenarios where this skill should be used.

## Steps

1. First, do this
2. Then, do that

## Examples

Concrete examples of skill invocation.
```

### 3.8 `ov skills remove`（别名 `rm`）— 移除技能

移除已安装的技能。

```bash
ov skills remove [skills...] [options]
```

**参数：**

| 参数 | 短选项 | 说明 |
|------|--------|------|
| `[skills...]` | — | 要移除的技能名 |
| `--user` | `-u` | 从用户私有空间移除 |
| `--yes` | `-y` | 跳过确认提示 |
| `--all` | — | 移除所有技能 |

**示例：**

```bash
# 交互式选择移除
ov skills remove

# 从全局共享空间移除指定技能
ov skills remove search-web

# 从用户私有空间移除
ov skills remove search-web --user

# 移除所有全局技能
ov skills remove --all
```

**与现有方式的对比：**

| 现有 | 改造后 |
|------|--------|
| `ov rm viking://agent/skills/old-skill/ --recursive` | `ov skills remove old-skill` |
| `ov rm viking://user/alice/skills/old-skill/ --recursive` | `ov skills remove old-skill --user` |

### 3.9 `ov skills show` — 查看技能详情（OpenViking 增强）

展示技能的完整信息，包括元数据、分层摘要和辅助文件。

```bash
ov skills show <skill-name> [options]
```

**参数：**

| 参数 | 短选项 | 说明 |
|------|--------|------|
| `<skill-name>` | — | 技能名称 |
| `--user` | `-u` | 从用户私有空间查找 |
| `--level <L>` | `-L` | 内容层级：`0`(摘要)、`1`(概述)、`2`(完整，默认) |
| `--format <fmt>` | `-o` | 输出格式 |
| `--files` | `-f` | 列出辅助文件 |
| `--source` | — | 显示来源信息（安装源、版本、更新时间） |

**示例：**

```bash
# 查看全局技能完整内容
ov skills show search-web

# 查看用户私有技能
ov skills show search-web --user

# 仅查看摘要（L0，最省 Token）
ov skills show search-web -L 0

# 列出辅助文件
ov skills show search-web --files

# 查看来源信息
ov skills show search-web --source
```

这是 OpenViking 的差异化命令，利用 L0/L1/L2 分层摘要能力，在 Agent 上下文中实现更精细的渐进式披露。

### 3.10 `ov skills validate` — 验证技能格式（OpenViking 增强）

验证 SKILL.md 是否符合 Agent Skills 规范。

```bash
ov skills validate <path>
```

**参数：**

| 参数 | 短选项 | 说明 |
|------|--------|------|
| `<path>` | — | SKILL.md 文件或技能目录路径 |
| `--strict` | — | 严格模式（名称必须匹配目录名等） |

**示例：**

```bash
# 验证技能格式
ov skills validate ./skills/my-skill/

# 严格验证
ov skills validate ./skills/my-skill/ --strict
```

**验证规则：**

| 规则 | 严格模式 | 宽松模式 |
|------|---------|---------|
| name 必填 | 报错 | 报错 |
| description 必填 | 报错 | 报错 |
| name 匹配目录名 | 报错 | 警告 |
| name 超过 64 字符 | 报错 | 警告 |
| name 包含非法字符 | 报错 | 警告 |
| description 超过 1024 字符 | 报错 | 警告 |
| YAML 格式错误 | 报错 | 报错 |
| SKILL.md body 超过 500 行 | 警告 | — |

---

## 4. SKILL.md 格式扩展

### 4.1 兼容 Agent Skills 规范

OpenViking 的 SKILL.md 格式需完全兼容 [agentskills.io 规范](https://agentskills.io/specification)，同时保留现有扩展字段：

```yaml
---
# Agent Skills 规范字段（兼容）
name: search-web                     # 必填
description: Search the web...        # 必填
license: Apache-2.0                   # 可选
compatibility: Requires internet      # 可选
metadata:                             # 可选
  author: openviking-team
  version: "1.0"
  internal: false                     # 内部技能标记
allowed-tools: Bash(curl:*) Read      # 可选（实验性）

# OpenViking 扩展字段
tags:                                 # 可选，分类标签
  - web
  - search
source: github.com/openviking/skills  # 可选，安装来源
source_ref: v1.2.0                    # 可选，来源版本引用
watch_interval: 60                    # 可选，自动更新间隔（分钟）
---
```

### 4.2 字段对照表

| Agent Skills 规范 | OpenViking 现有 | 改造后 | 说明 |
|-------------------|----------------|--------|------|
| `name` | `name` | `name` | 无变化 |
| `description` | `description` | `description` | 无变化 |
| `license` | — | `license` | 新增 |
| `compatibility` | — | `compatibility` | 新增 |
| `metadata` | — | `metadata` | 新增，包含 `internal`、`author`、`version` 等 |
| `allowed-tools` | `allowed_tools` | `allowed-tools` | 连字符风格，对齐规范 |
| — | `tags` | `tags` | 保留为 OpenViking 扩展 |
| — | — | `source` | 新增，记录安装来源 |
| — | — | `source_ref` | 新增，记录来源版本 |
| — | — | `watch_interval` | 保留，从 API 参数移至 frontmatter |

### 4.3 VikingBot 元数据扩展

OpenViking 已有的 VikingBot Agent 系统在 `metadata` 字段内使用 `vikingbot` 子键承载 Agent 运行时信息，改造后保留并规范化：

```yaml
metadata:
  vikingbot:
    emoji: "🔍"                           # 技能显示图标
    requires:
      bins: ["gh"]                         # 依赖的 CLI 二进制
      env: ["GITHUB_TOKEN"]                # 依赖的环境变量
    install:                               # 安装指引
      - "brew install gh"
    always: false                          # 是否始终注入上下文（不等待触发）
```

**字段说明：**

| 字段 | 类型 | 说明 |
|------|------|------|
| `vikingbot.emoji` | string | Agent UI 中的技能图标 |
| `vikingbot.requires.bins` | string[] | 运行所需的 CLI 工具（如 `gh`, `curl`, `jq`） |
| `vikingbot.requires.env` | string[] | 运行所需的环境变量 |
| `vikingbot.install` | string[] | 依赖工具的安装命令 |
| `vikingbot.always` | bool | 若为 true，技能始终注入上下文（跳过触发判断） |

`requires` 机制与 Agent Skills 规范的 `compatibility` 字段互补：`compatibility` 是供人类阅读的文本描述，而 `requires` 是供程序检查的结构化声明。`ov skills add` 在安装时可自动校验 `requires.bins` 和 `requires.env` 是否满足。

### 4.4 技能隐私系统

OpenViking 具有独特的技能隐私保护机制，改造后完整保留并集成到 `ov skills` 子命令中。

**处理流程：**

```
SKILL.md 原文 → LLM 检测敏感值 → 替换为占位符 → 存入知识库
                                                        ↓
Agent 读取 ← 隐私服务还原占位符 ← 从隐私配置服务读取真实值
```

**占位符格式：** `{{ov_privacy:skill:<NAME>:<FIELD>}}`

例如，技能中包含 API Key 时：

```markdown
# 原文
Set environment variable API_KEY=sk-abc123def456

# 隐私处理后
Set environment variable API_KEY={{ov_privacy:skill:search-web:api_key}}
```

**与 `ov skills` 命令的集成：**

| 命令 | 隐私行为 |
|------|---------|
| `ov skills add` | 自动执行隐私提取，敏感值存入隐私配置服务 |
| `ov skills show` | 读取时自动还原占位符（需有权限） |
| `ov skills list` | 仅显示 name/description，不涉及隐私内容 |
| `ov skills validate` | 检测占位符格式是否合法，不还原值 |

隐私系统是 OpenViking 相对于 Vercel Labs Skills CLI 的重要安全差异化能力。

### 4.5 MCP 格式自动转换（保留）

MCP Tool 格式自动检测和转换能力保留，纳入 `ov skills add mcp://...` 路径。转换规则不变：

- `inputSchema` 检测 → kebab-case 命名 → 参数提取 → Markdown 生成
- 转换后的 SKILL.md 完全符合 Agent Skills 规范

### 4.6 技能模糊匹配

OpenViking 现有 `calibrate_skill_name()` 机制支持技能名称模糊匹配，改造后应用于所有接受技能名称的子命令：

```python
# 现有实现：使用 SequenceMatcher，80% 相似度阈值
calibrate_skill_name(candidate="search_web", available=["search-web", "code-review"])
# → 匹配到 "search-web"（下划线/连字符容错）
```

**应用场景：**

| 命令 | 模糊匹配行为 |
|------|------------|
| `ov skills show search_web` | 自动匹配到 `search-web`，输出提示 |
| `ov skills remove search-web` | 精确匹配优先，模糊匹配需确认 |
| `ov skills update searchweb` | 模糊匹配 + 确认提示 |

---

## 5. 技能存储架构

### 5.1 双空间存储模型

OpenViking 技能在服务端知识库中按可见性分为全局共享和用户私有两个空间：

```
┌─────────────────────────────────────────────────────────┐
│                  OpenViking 知识库 (AGFS)                 │
│                                                          │
│  全局共享空间：viking://agent/skills/                     │
│  ├── search-web/                                         │
│  │   ├── SKILL.md                                        │
│  │   ├── .abstract.md    (L0 摘要)                       │
│  │   ├── .overview.md    (L1 概述)                       │
│  │   └── scripts/                                        │
│  │       └── search.py                                   │
│  ├── code-review/                                        │
│  │   └── SKILL.md                                        │
│  └── ...                                                 │
│  可见性：account 内所有用户                                │
│                                                          │
│  ──────────────── 租户边界 ────────────────              │
│                                                          │
│  用户私有空间：viking://user/{user_space}/skills/         │
│  ├── my-tool/                                            │
│  │   └── SKILL.md                                        │
│  └── ...                                                 │
│  可见性：仅当前用户                                       │
│                                                          │
│  特性：语义索引、向量化、分层摘要、增量更新                 │
│  检索约束：全局技能对 account 内可见，私有技能仅拥有者可见  │
└─────────────────────────────────────────────────────────┘
```

**与多租户边界的对齐：**

| 数据类型 | 跨 account 共享 | account 内共享 | 默认隔离边界 |
|----------|----------------|---------------|-------------|
| 全局技能（`viking://agent/skills/`） | 否 | 是 | account |
| 用户私有技能（`viking://user/.../skills/`） | 否 | 否 | user |

这与 OpenViking 现有多租户架构完全一致：`resources` 在 account 内共享，`user` 空间按用户隔离，检索层按身份自动过滤。

### 5.2 安装来源追踪

每个安装的技能记录来源信息，以支持 `update` 和溯源：

```yaml
# 存储在 OpenViking 内部元数据中，不写入 SKILL.md
_source:
  type: github          # github | git | local | mcp | openviking
  origin: vercel-labs/agent-skills
  ref: main
  installed_at: "2026-05-18T12:00:00Z"
  installed_by: user@example.com
  scope: global         # global | user
```

### 5.3 冲突与优先级

当同名技能出现在全局和用户私有空间时，遵循以下优先级：

1. **用户私有空间**（`viking://user/{user_space}/skills/<name>/`）— 高优先级
2. **全局共享空间**（`viking://agent/skills/<name>/`）— 低优先级

用户私有技能可以覆盖同名全局技能，实现个人定制。冲突时记录警告日志。

### 5.4 OVPack 技能导入导出

OVPack 是 OpenViking 现有的 ZIP 包格式，用于内容树的迁移和备份。改造后，`ov skills add/remove` 与 OVPack 深度集成：

**现有 OVPack 命令保留，同时新增便捷路径：**

| 现有命令 | 便捷替代 |
|---------|---------|
| `ov export viking://agent/skills/my-skill ./export.ovpack` | `ov skills show my-skill --export ./export.ovpack` |
| `ov import ./export.ovpack viking://agent/skills/` | `ov skills add ./export.ovpack` |
| `ov export viking://user/alice/skills/my-skill ./export.ovpack` | `ov skills show my-skill --user --export ./export.ovpack` |
| `ov import ./export.ovpack viking://user/alice/skills/` | `ov skills add ./export.ovpack --user` |

**`ov skills add` 自动识别 OVPack 格式：**

```bash
# 从 OVPack 包安装到全局空间
ov skills add ./my-skill.ovpack

# 从 OVPack 包安装到用户私有空间
ov skills add ./my-skill.ovpack --user
```

**OVPack 内部结构（技能）：**

```
my-skill/
  files/
    SKILL.md
    scripts/
      extract.py
  _ovpack/
    manifest.json           # 包含 checksum、scope、root URI
    index_records.jsonl     # 向量索引记录
    dense.f32               # 向量快照（可选）
```

OVPack 的 `scope` 机制确保技能包只能导入到对应的命名空间下，防止误操作。

### 5.5 VikingBot SkillsLoader 对齐

OpenViking 现有两套技能系统：服务端 VikingFS 存储和 VikingBot 本地文件系统加载。改造后统一入口，但保留两种加载模式：

**现状：**

| 组件 | 位置 | 加载方式 |
|------|------|---------|
| VikingBot SkillsLoader | `bot/vikingbot/agent/skills.py` | 本地目录扫描 `bot/workspace/skills/` |
| 服务端 SkillProcessor | `openviking/utils/skill_processor.py` | 通过 API 上传到 VikingFS |

**改造后：**

VikingBot SkillsLoader 扩展为同时扫描本地目录和 OpenViking 知识库，实现统一的技能发现：

```python
# 改造前：仅扫描本地
skills = loader.list_skills()  # 扫描 workspace/skills/

# 改造后：扫描本地 + 远程（全局 + 用户私有）
skills = loader.list_skills()                        # 本地
global_skills = loader.list_remote_skills()           # viking://agent/skills/（通过 API）
user_skills = loader.list_remote_skills(user=True)    # viking://user/.../skills/（通过 API）
all_skills = {**global_skills, **user_skills, **skills}  # 用户私有覆盖全局覆盖本地
```

**`always` 技能保留：** VikingBot 的 `metadata.vikingbot.always: true` 机制保留，标记为 always 的技能始终注入 Agent 上下文（跳过触发判断），适用于系统级技能。

**需求检查保留：** `requires.bins` 和 `requires.env` 的运行时检查保留，在 `list_skills()` 时过滤掉不满足要求的技能。

---

## 6. 与 Agent Skills 生态的互通

### 6.1 Plugin Manifest 兼容

支持 `.claude-plugin/marketplace.json` 和 `.claude-plugin/plugin.json` 中的技能声明，与 Claude Code 插件市场生态互通。

### 6.2 远程仓库发现（未来扩展）

`ov skills find --remote` 将支持从 [skills.sh](https://skills.sh) 等技能发现 Hub 搜索远程仓库中的技能，并直接通过 `ov skills add` 安装。此能力留待 Phase 3 实现。

---

## 7. 渐进式披露：OpenViking 增强方案

### 7.1 标准 Agent Skills 三层 + OpenViking L0/L1/L2

OpenViking 的分层摘要系统天然与 Agent Skills 的渐进式披露对齐，且提供了更精细的粒度：

| Agent Skills 层级 | OpenViking 层级 | 内容 | Token 估算 |
|-------------------|----------------|------|-----------|
| Tier 1：目录 | — | `name` + `description` | ~50-100 |
| Tier 2：指令 (部分) | L0 摘要 | `.abstract.md` 简要描述 | ~100-200 |
| Tier 2：指令 (部分) | L1 概述 | `.overview.md` 参数和用例 | ~300-500 |
| Tier 2：指令 (完整) | L2 详细 | `SKILL.md` 完整文档 | ~1000-5000 |
| Tier 3：资源 | — | `scripts/`, `references/`, `assets/` | 按需 |

### 7.2 Agent 集成时的披露策略

通过 OpenViking API 集成的 Agent 可通过 `ov skills show <name> -L <level>` 按需获取不同粒度的内容，避免一次加载过多 Token。

### 7.3 内部技能（Internal Skills）

支持 `metadata.internal: true` 标记的内部技能，默认在发现和列表中隐藏，仅当环境变量 `INSTALL_INTERNAL_SKILLS=1` 时可见。适用于：

- 实验性技能
- 内部工具链专用技能
- 不面向终端用户的系统技能

---

## 8. 命令速查表

### 8.1 旧命令 → 新命令映射

| 旧命令 | 新命令 | 说明 |
|--------|--------|------|
| `ov add-skill ./skill/` | `ov skills add ./skill/` | 添加技能（全局） |
| `ov add-skill ./skill/ --wait` | `ov skills add ./skill/ --wait` | 等待处理 |
| `ov ls viking://agent/skills/` | `ov skills list` | 列出全局技能 |
| `ov ls viking://user/*/skills/` | `ov skills list --user` | 列出用户私有技能 |
| `ov ls viking://agent/skills/ --simple` | `ov skills list -o simple` | 简洁列表 |
| `ov find "query" --uri viking://agent/skills/` | `ov skills find "query"` | 搜索技能 |
| `ov read viking://agent/skills/x/SKILL.md` | `ov skills show x` | 查看技能 |
| `ov abstract viking://agent/skills/x/` | `ov skills show x -L 0` | 查看摘要 |
| `ov overview viking://agent/skills/x/` | `ov skills show x -L 1` | 查看概述 |
| `ov rm viking://agent/skills/x/ -r` | `ov skills remove x` | 删除全局技能 |
| `ov rm viking://user/alice/skills/x/ -r` | `ov skills remove x --user` | 删除用户私有技能 |
| — | `ov skills add owner/repo` | 从 GitHub 安装 |
| — | `ov skills add ... --user` | 安装到用户私有空间 |
| — | `ov skills update` | 更新技能 |
| — | `ov skills init my-skill` | 创建技能模板 |
| — | `ov skills validate ./skill/` | 验证技能格式 |

### 8.2 与 Vercel Labs Skills CLI 的对应关系

| Vercel Labs | OpenViking | 差异 |
|-------------|-----------|------|
| `npx skills add <source>` | `ov skills add <source>` | OV 额外支持 URI 和 MCP 来源；用 `--user` 替代 `-g` |
| `npx skills list` | `ov skills list` | OV 默认查服务端知识库，用 `--user` 查用户私有 |
| `npx skills find [query]` | `ov skills find [query]` | OV 额外支持语义搜索 |
| `npx skills update` | `ov skills update` | OV 额外支持 `--wait` 语义处理 |
| `npx skills init [name]` | `ov skills init [name]` | OV 用 `--user` 替代 `-g` |
| `npx skills remove [skills]` | `ov skills remove [skills]` | OV 用 `--user` 替代 `-g` |
| — | `ov skills show <name>` | OV 独有，L0/L1/L2 分层查看 |
| — | `ov skills validate <path>` | OV 独有，格式验证 |

---

## 9. API 层改造

### 9.1 HTTP API

现有 `POST /api/v1/skills` 保持向后兼容，新增以下接口：

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/v1/skills` | 列出技能（`?scope=global|user` 过滤） |
| `GET` | `/api/v1/skills/:name` | 获取技能详情（含分层摘要，`?scope=global|user`） |
| `POST` | `/api/v1/skills` | 添加技能（现有，扩展 `scope` 参数） |
| `PUT` | `/api/v1/skills/:name` | 更新技能（`?scope=global|user`） |
| `DELETE` | `/api/v1/skills/:name` | 删除技能（`?scope=global|user`） |
| `POST` | `/api/v1/skills/find` | 语义搜索技能（`?scope=global|user`） |
| `POST` | `/api/v1/skills/validate` | 验证技能格式 |

**`scope` 参数说明：**

| 值 | 对应存储路径 | 说明 |
|---|------------|------|
| `global`（默认） | `viking://agent/skills/` | 全局共享空间 |
| `user` | `viking://user/{user_space}/skills/` | 用户私有空间 |

`scope=user` 时，服务端从请求身份（API key 或 trusted header）自动解析 `user_space`，调用方无需手动拼接用户路径。

### 9.2 Python SDK

```python
import openviking as ov

client = ov.SyncHTTPClient(url="http://localhost:1933", api_key="your-key")
client.initialize()

# 添加技能到全局共享空间（兼容现有）
client.add_skill("./skills/my-skill/")

# 添加技能到用户私有空间
client.add_skill("./skills/my-skill/", scope="user")

# 新增：从 GitHub 安装
client.skills.add("vercel-labs/agent-skills", skill=["frontend-design"])

# 新增：列出全局技能
client.skills.list()

# 新增：列出用户私有技能
client.skills.list(scope="user")

# 新增：搜索技能
client.skills.find("search the internet")

# 新增：查看技能
client.skills.show("search-web", level=0)  # L0 摘要

# 新增：更新技能
client.skills.update("search-web")

# 新增：移除技能
client.skills.remove("search-web")
client.skills.remove("search-web", scope="user")

# 新增：初始化技能
client.skills.init("my-new-skill")

# 新增：验证技能
client.skills.validate("./skills/my-skill/")
```

### 9.3 CLI 命令注册

在 `crates/ov_cli/src/main.rs` 中注册 `SkillsCommands` 子命令：

```rust
#[derive(Subcommand)]
enum SkillsCommands {
    /// Install skills from a source
    Add {
        /// Skill source (GitHub, local path, URI, MCP)
        source: String,
        /// Install specific skills by name
        #[arg(short, long)]
        skill: Option<Vec<String>>,
        /// Install to user private space
        #[arg(short, long)]
        user: bool,
        /// List available skills without installing
        #[arg(short, long)]
        list: bool,
        /// Wait for semantic processing
        #[arg(short, long)]
        wait: bool,
        /// Skip confirmation prompts
        #[arg(short, long)]
        yes: bool,
        /// Install all skills
        #[arg(long)]
        all: bool,
    },
    /// List installed skills (alias: ls)
    #[command(alias = "ls")]
    List {
        /// List user private skills only
        #[arg(short, long)]
        user: bool,
        /// Output format
        #[arg(short, long, default_value = "table")]
        format: String,
    },
    /// Search for skills
    Find {
        /// Search query
        query: Option<String>,
        /// Search user private skills only
        #[arg(short, long)]
        user: bool,
        /// Result limit
        #[arg(short, long, default_value = "10")]
        limit: i32,
        /// Relevance threshold
        #[arg(short, long)]
        threshold: Option<f64>,
        /// Output format
        #[arg(short, long, default_value = "table")]
        format: String,
    },
    /// Update installed skills
    Update {
        /// Skills to update (empty = all)
        skills: Vec<String>,
        /// Update user private skills only
        #[arg(short, long)]
        user: bool,
        /// Skip confirmation
        #[arg(short, long)]
        yes: bool,
        /// Wait for semantic processing
        #[arg(short, long)]
        wait: bool,
    },
    /// Create a new skill template
    Init {
        /// Skill name
        name: Option<String>,
        /// Create and add to user private space
        #[arg(short, long)]
        user: bool,
    },
    /// Remove installed skills (alias: rm)
    #[command(alias = "rm")]
    Remove {
        /// Skills to remove
        skills: Vec<String>,
        /// Remove from user private space
        #[arg(short, long)]
        user: bool,
        /// Skip confirmation
        #[arg(short, long)]
        yes: bool,
        /// Remove all skills
        #[arg(long)]
        all: bool,
    },
    /// Show skill details
    Show {
        /// Skill name
        name: String,
        /// Look up in user private space
        #[arg(short, long)]
        user: bool,
        /// Content level (0=abstract, 1=overview, 2=full)
        #[arg(short = 'L', long, default_value = "2")]
        level: i32,
        /// List auxiliary files
        #[arg(short, long)]
        files: bool,
        /// Show source information
        #[arg(long)]
        source: bool,
        /// Output format
        #[arg(short, long, default_value = "table")]
        format: String,
    },
    /// Validate SKILL.md format
    Validate {
        /// Path to skill directory or SKILL.md
        path: String,
        /// Strict validation mode
        #[arg(long)]
        strict: bool,
    },
}
```

---

## 10. 迁移与兼容策略

### 10.1 向后兼容

| 策略 | 说明 |
|------|------|
| 旧命令别名 | `ov add-skill` 保留为 `ov skills add` 的别名，输出 deprecation 警告 |
| API 向后兼容 | `POST /api/v1/skills` 参数不变，新增 `scope` 字段可选（默认 `global`） |
| SKILL.md 格式 | 现有 `allowed_tools` 自动映射为 `allowed-tools`，两者均接受 |
| 存储路径 | `viking://agent/skills/` 路径不变，新增 `viking://user/.../skills/` 用户私有空间 |
| 旧版 ls/rm | 通用 `ov ls` / `ov rm` 对技能路径仍可用 |

### 10.2 迁移步骤

1. **Phase 1**：新增 `ov skills` 子命令框架，实现 `add`、`list`、`find`、`remove`、`show`，底层复用现有服务；实现 `--user` 参数支持用户私有空间
2. **Phase 2**：新增 `update`、`init`、`validate` 子命令
3. **Phase 3**：实现 GitHub/Git 来源拉取、远程仓库搜索（`find --remote`）；接入 skills.sh 发现 Hub
4. **Phase 4**：标记 `ov add-skill` 为 deprecated；新增专用 HTTP API 端点

### 10.3 Deprecation 时间线

| 版本 | 动作 |
|------|------|
| vN.0 | 新增 `ov skills` 子命令，`ov add-skill` 仍为主命令 |
| vN+1 | `ov skills` 成为主推荐方式，`ov add-skill` 输出 deprecation 警告 |
| vN+2 | `ov add-skill` 变为隐藏别名，文档移除 |

---

## 11. OpenViking 差异化优势

与 Vercel Labs Skills CLI 相比，OpenViking 的差异化定位：

| 维度 | Vercel Labs Skills CLI | OpenViking |
|------|----------------------|-----------|
| 技能存储 | 仅本地文件系统 | 服务端知识库（全局共享 + 用户私有） |
| 可见性模型 | 项目级 / 用户级 | 全局共享（account 内） / 用户私有（user 隔离） |
| 搜索 | 关键词匹配 | 语义搜索 + 关键词匹配 |
| 摘要 | 无 | L0/L1/L2 分层摘要，精细 Token 控制 |
| MCP 兼容 | 不支持 | 自动检测 MCP Tool 并转换 |
| 向量化 | 无 | 自动向量化索引，支持语义检索 |
| 增量更新 | 手动 `update` | 手动 + 自动（`watch_interval`） |
| 来源格式 | GitHub/Git/Local | GitHub/Git/Local + URI + MCP + OVPack |
| 多租户 | 不支持 | 支持（account / user / agent 三层隔离） |
| 资源关联 | 不支持 | 技能与资源的语义关联 |
| 隐私保护 | 不支持 | 敏感值自动提取与占位符替换 |
| 使用统计 | 不支持 | 会话级技能调用统计与成功率追踪 |
| 离线打包 | 不支持 | OVPack 格式导入/导出 |
| 模糊匹配 | 不支持 | 名称相似度容错（80% 阈值） |

---

## 12. 技能使用统计

OpenViking 现有会话级技能调用统计机制，改造后集成到 `ov skills show` 中。

**现有实现**（`openviking/session/tool_skill_utils.py`）：

| 函数 | 功能 |
|------|------|
| `extract_skill_name_from_uri()` | 从 `viking://agent/skills/NAME/SKILL.md` 解析技能名 |
| `calibrate_skill_name()` | 模糊匹配候选名与实际技能名（80% 相似度） |
| `collect_skill_stats()` | 聚合每个技能的调用次数、成功时间等 |

**改造后集成方式：**

```bash
# 查看技能使用统计
ov skills show search-web --source
```

输出中包含统计信息：

```
name: search-web
description: Search the web...
scope: global
installed_from: vercel-labs/agent-skills (main, 2026-05-18)
stats:
  total_calls: 42
  success_rate: 95%
  last_used: 2026-05-18T10:30:00Z
```

---

## 13. 参考资料

- [Agent Skills 规范](https://agentskills.io/specification) — SKILL.md 格式、frontmatter 字段、目录约定
- [Agent Skills 快速入门](https://agentskills.io/skill-creation/quickstart) — 创建第一个技能
- [Agent Skills 最佳实践](https://agentskills.io/skill-creation/best-practices) — 技能编写指南
- [Agent Skills 客户端集成](https://agentskills.io/client-implementation/adding-skills-support) — 如何为 Agent 添加 Skills 支持
- [Vercel Labs Skills CLI](https://github.com/vercel-labs/skills) — 跨 Agent 技能管理工具
- [skills.sh](https://skills.sh) — 技能发现 Hub
- [OpenViking 多租户](../concepts/11-multi-tenant.md) — 多租户架构与身份隔离
- [OpenViking 技能文档](../api/04-skills.md) — 现有技能 API
- [OpenViking 资源文档](../api/02-resources.md) — 现有资源管理 API
