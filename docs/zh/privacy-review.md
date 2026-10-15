# OpenViking Privacy 审查简报

审查日期：2026-10-15；代码基线：`9baf83f0`。依据：[Privacy API](api/10-privacy.md)、[Privacy 概念](concepts/13-privacy.md)，并核对当前实现、Agent 接入、测试和 CI。Agent 审查重点为仓库内 MCP、SDK/CLI、Codex/通用 hook 共享采集代码与 OpenClaw 使用指导。本文是审查结果及建议方案，不涉及功能修改。

## 结论

**Privacy 已具备用户范围的敏感配置分离、版本保存和读取还原能力，但当前不能保证 Agent 接入后会主动、妥善地用它保存外部系统账号密钥，也不能依据现有测试通过就认定敏感信息不会泄漏。**

主要原因是：Agent 缺少直接的 Privacy 管理工具与完整操作指导；自动保护集中于技能正文，依赖模型识别及有限的文本替换；还原后的真实值可以进入模型上下文及会话采集；版本写入的故障一致性存在可复现问题。现有测试能验证若干功能和并发行为，对这些安全边界的保障不足。

两份参考文档已经如实说明“抽取不能保证全面”“附件不一定处理”“读取返回真实值”“不等于加密”。这些限制应成为 Agent 接入和测试设计的约束，不能只靠文档提示来落实。

## 1. 当前机制及适用边界

| 能力 | 当前实现与含义 |
|---|---|
| 配置组织 | 按调用者的 `viking://user/{user_id}/privacy/{category}/{target_key}` 保存。API 的 `category` 不限于 `skill`，所以可以人工保存任意系统的账号、密码、密钥；自动提取和还原使用 `category=skill`、技能名作为目标。 |
| 版本管理 | `current.json`、`history/version_001.json` 等保存完整 `values`；`.meta.json` 保存当前/最新版本及作者等。相同值不新增版本；不同值完整替换并激活；回滚后再次写入按最新版本递增。 |
| 技能写入 | `SkillProcessor` 在准备阶段调用账户配置的 VLM，识别正文中的配置，再对成功匹配的片段占位符化，保存 Privacy 后写入技能。更新与训练产生技能的相关路径也使用隐私处理。 |
| 技能读取 | `FSService.read` 识别 `/skills/{name}/SKILL.md`，按**当前调用者**的配置还原占位符。Privacy API、CLI 和技能详情也能返回真实值。共享技能的密钥仍按用户保存；同一用户的同名技能共用同一个 Privacy 目标。 |
| 权限与加密 | Privacy 复用请求身份和 VikingFS 命名空间/ACL，具有用户空间隔离；ROOT 可跨用户访问。它没有独立的“仅执行可用、不可读取”密钥权限。存储加密是另一项配置，默认关闭。 |
| 生命周期 | `DELETE /api/v1/skills/{name}` / `ov skills remove` 删除相应 Privacy；通用 `forget` / `ov rm` 删除技能目录会留下配置。API 未提供通用 Privacy 删除或单个历史版本销毁端点。激活版本不会轮换或撤销第三方密钥。 |

实现依据：[配置服务](../../openviking/privacy/service.py)、[技能处理](../../openviking/utils/skill_processor.py)、[读取服务](../../openviking/service/fs_service.py)、[访问判断](../../openviking/core/namespace.py)、[存储加密](concepts/10-encryption.md)。

## 2. 建议落地方案

本阶段先解决一个确定性场景：当 `resources`、`skills`、`memories` 的待写入正文中出现**当前写入用户已登记在 Privacy 中的密钥**时，在落盘及派生处理之前强制识别并替换为统一引用。Privacy 新增后的存量反向扫描不默认自动运行，而由显式 CLI 命令触发。

当前工作分支已经完成第一轮落地：`ov privacy reference` 默认只返回 owner 绑定引用；`ov privacy resolve` 可以通过三段参数、owner-bound reference 或字段 URI 显式读取单个字段；`ov privacy delete` 可以删除整个 target，也可以让当前 active 配置中的单个字段不可用：仍有其他字段时内部发布新快照并保留历史，删除最后一个字段时删除整个 target 及其历史；PrivacySanitizer 不按字段名猜测，对当前 active Privacy 中字符数不少于 6 的字符串值实施自动保护；普通文本写入、Skill 写入、Resource 导入、直接 VikingFS 文本写入和 `read_visible` 已接入；`ov privacy scan` 默认 dry-run，`--fix` 显式修复存量正文。会话采集、Gateway 内部还原以及所有外部导出/备份路径仍需后续验收，不能把本轮接入理解为全链路已经闭环。

### 2.1 统一引用格式

建议采用：

```text
{{ov_privacy:{owner_user_id}:viking://~/privacy/{category}/{target_key}#/values/{field}}}
```

例如用户 `user_id_1` 向公共技能区写入包含 GitHub 密钥的内容，替换结果为：

```text
Authorization: Bearer {{ov_privacy:user_id_1:viking://~/privacy/credential/github-prod#/values/api_key}}
```

语义约定：

- `owner_user_id` 是 Privacy 配置所有者，也是本次自动替换的溯源身份；本阶段不增加引用协议版本，未来出现不兼容语法时再加入。
- 引用内部的 `~` **在 Privacy 引用解析器内**相对于 `owner_user_id` 解析，而不是相对于当前阅读者解析；普通 `viking://~` 在其他 API 中仍保持“当前调用者”语义。
- `category + target_key` 定位配置目标，`#/values/{field}` 定位单个字段；不能只引用 target，否则可能一次暴露同一目标下的多个值。
- `{owner_user_id}`、`category`、`target_key` 和 `field` 必须走统一的标识符校验与转义，不能通过字符串拼接后直接访问存储。
- 引用始终解析当前 active version，不绑定 `current.json` 等物理文件。密钥轮换后正文引用无需变化。
- 自动 Sanitizer 只生成所有者绑定引用，不生成调用者绑定引用。这使 `/agent/skills` 等公共区域中的内容可追溯，同时阻止其他用户将引用误解析为自己的同名配置。
- canonical reference 始终采用无空格形式。解析器仅兼容 `{{` 后、`}}` 前的空格或 Tab，解析后立即规范化为无空格形式；owner、URI、category、target 和 field 内部不接受任意空白。

当其他用户读取公共内容时，应保留引用并返回结构化状态，而不是尝试跨用户读取：

```text
[Privacy Config Notice]
owner: user_id_1
status: forbidden
action: ask the owner or an administrator for access or configuration guidance
```

这项设计会向有权读取公共内容的用户显示配置所有者 ID，是为了支持溯源和协作；如部署不希望暴露真实 user ID，后续可以用可审计的 `owner_ref` 替代，但不能移除服务端真实 owner 绑定。

### 2.2 高效 PrivacySanitizer

PrivacySanitizer 应成为统一底层能力，而不是 Skill 专用的 LLM 后处理。建议工作方式如下：

1. 按 `(account_id, user_id, privacy_revision)` 缓存当前生效的敏感值目录。每次该用户 upsert/activate/delete Privacy 后只失效对应缓存；缓存同时使用 3600 秒 TTL，多 worker/多节点上的外部修改最多一小时后被本进程重新加载。
2. Privacy 是显式保护边界，不再通过 `_SECRET_FIELD_NAMES` 或字段名模式猜测敏感性；当前 active Privacy 中字符数不少于 6 的字符串值进入匹配目录，包括用户自定义字段名。更短的值仍可保存和显式 resolve，但不会参与正文全文替换，以避免 `cn`、`1` 等造成大量误命中。
3. 在受控内存中构建多模式匹配器（如 Aho-Corasick），扫描复杂度保持为 `O(正文长度 + 命中数)`；重叠命中选择最长值，同一个值对应多个 Privacy 引用时标记为歧义并拒绝自动替换。持久缓存和日志只保存 HMAC/引用元数据，不记录原值。
4. 对当前用户发起的 user 空间写入生效；写入 `/agent/skills` 等公共区域时仍使用**写入者**的 Privacy 目录，并在引用中写入该用户 ID。
5. 先匹配完整原值，再按明确白名单处理 URL 编码、JSON 转义、PEM 换行标准化等变体。多个 Privacy 字段对应同一值、过短密钥造成高歧义、或无法可靠生成引用时，应拒绝/隔离写入并返回候选引用，不能任意选择。
6. Privacy 自身存储路径不参与扫描。审计只记录正文 URI、owner、引用、位置和匹配规则，不记录命中的秘密。

必须覆盖以下写入和派生入口：

- 普通 `write`、`edit`、batch write；
- Skill 的 frontmatter、正文、description、metadata 和文本附件；
- Resource 解析后的正文及文本派生物；
- Memory 最终序列化正文和可进入上下文的字段；
- 写入 `.abstract.md`、`.overview.md`、关键词索引、向量 payload 或发送摘要模型之前。

建议采用“两道门”：第一道在各类内容进入持久化/摘要/索引之前替换；第二道在 `read`、search inline content 和 context assembler 输出前再次扫描，拦截绕过统一写入入口或尚未完成手工修复的存量内容。第二道只做当前响应脱敏，不在读取路径中隐式改写存储。

### 2.3 显式存量扫描与修复

Privacy 新增、轮换后暂不默认扫描全部存量，以避免不可预期的大范围 IO 和内容修改。提供显式 CLI：

```bash
# 默认只报告命中，不修改
ov privacy scan --scope resources,skills,memories
ov privacy scan --target viking://~/resources/project-a

# 用户确认后替换正文，并刷新摘要和索引
ov privacy scan --scope resources,skills,memories --fix --wait
```

建议约束：

- 普通用户只能扫描其可读且可写的内容，并只使用自己的 Privacy 目录；管理员代用户扫描必须显式指定 owner 并留下审计。
- `scan` 默认 dry-run，只返回 URI、字段引用、命中数量及是否可自动修复，不返回原值。
- `--fix` 在持有内容锁时重新扫描，采用 expected revision/CAS 防止覆盖并发修改；修复后删除旧索引记录，重新生成摘要和索引。
- 历史快照、导出、外部备份和已发送日志不承诺由该命令清理，需单独的保留与销毁策略。

### 2.4 上下文表示与 Agent 还原

上下文正文保持统一引用，不在组装阶段自动展开，并可以附加不含密钥的状态：

```xml
<privacy-ref
  owner="user_id_1"
  category="credential"
  target="github-prod"
  field="api_key"
  status="available" />
```

本阶段允许 Agent 自己发起还原，但应是**显式、字段级、受权限控制**的操作：

1. Agent 识别引用并提取 owner、category、target 和 field，不自行拼接或改写引用。
2. 当当前身份有权读取 owner 的 Privacy 时，调用字段级 resolve/read 接口获取当前 active value；接口只返回被引用字段，不返回整个 target。
3. Agent 将值用于当前外部系统调用；工具输入、工具输出、错误、会话采集和后续写入仍需经过 PrivacySanitizer，避免还原值再次进入 resources、skills 或 memories。
4. 当前用户无权读取时，解析器返回 `forbidden + owner_user_id`。Agent 应说明需联系该 owner/管理员，不能回退到猜测、搜索或跨用户读取。
5. 缺少 target/field 时返回 `missing`；Agent 可以引导 owner 补充 Privacy，不能把占位符当作真实参数调用。

OpenViking Gateway 可以提供更安全的增强路径：Gateway 在转发外部请求前于内部解析引用、注入密钥，并在响应返回 Agent 前再次脱敏，使明文不进入模型上下文。普通 OpenViking 接入仍允许 Agent 显式还原，两种方式共用同一引用、权限校验、审计和 Sanitizer，不应维护两套占位符协议。

## 3. 主要发现与建议

优先级：P0 表示应在承诺“自动安全保存生产凭据”前解决；P1 表示下一阶段补齐；P2 表示完善运维和产品语义。下表分别标明执行复现与代码审查证据。

| 优先级 | 发现及影响 | 建议与证据 |
|---|---|---|
| P0 | **Agent 不能自然发现完整的 Privacy 使用方法。** MCP 没有 Privacy 写入、查询、激活工具；Python SDK 也没有对应方法。插件指导包含“不要回显凭据”“不要把凭据放进技能”，但没有教如何将用户交付的账号密钥转存、引用、使用及清理。仅有 HTTP/CLI 能力不能证明 Agent 会选对保存路径。 | 增加明确的 `set/list/delete/resolve-field` 等工具与接入技能；普通管理响应默认只返回 owner、键名、引用和配置版本，仅显式字段还原返回该字段值。给出账号密钥处理示例及工具不可用时的分支。依据：[MCP 注册](../../openviking/server/mcp_endpoint.py)、[插件记忆指导](../../examples/codex-memory-plugin/skills/openviking-memory/SKILL.md)、[插件技能指导](../../examples/codex-memory-plugin/skills/openviking-skills/SKILL.md)、`sdk/python`。这是接入完备性判断，尚未通过真实 Agent 行为评测证明其选择结果。 |
| P0 | **模型识别成功也不等于清除成功。** 仅替换引号包裹的完整值，或 `:` / `=` 后直到行尾的完整裸值。Bearer、自然语言、带行尾注释等会保留原值；同一密钥在赋值和说明文字同时出现时，会一边保存 Privacy、一边留下明文。 | 对已经登记的密钥改用确定性的 PrivacySanitizer 全文匹配和残留校验，不再依赖字段格式；有歧义或未处理秘密时拒绝/隔离写入。对尚未登记的新秘密仍需检测或模型辅助，但不能把“模型未识别”解释为安全。已用虚构密钥执行复现，见下一节；依据：[替换器](../../openviking/privacy/skill_placeholder.py)。 |
| P0 | **无法区分“没有秘密”和“提取没有成功”。** 非 JSON、错误结构、匹配失败可得到空 `values` 并保留原文；模型调用异常会传播，但正常返回无效内容没有严格失败状态。提示词要求输出缺值配置项，代码却过滤空值并只返回实际替换成功的项，所需配置清单会丢失。 | 定义严格输出 schema、提取状态、已识别/已替换/未解决三类结果；失败时阻止敏感内容持久化。保留缺值字段及引用，供 Agent 请求配置。已复现无效响应和空值；依据：[提取器](../../openviking/privacy/skill_extractor.py)、[提取提示词](../../openviking/prompts/templates/skill/privacy_extraction.yaml)。 |
| P0 | **保护未贯穿持久化链路。** 只替换 `skill_dict.content`；description、metadata 和辅助文件不受同等处理，且附件会随技能写入并排入递归语义处理。普通 `write`、资源导入、`remember`、会话消息没有自动转存 Privacy 的机制。原始技能正文在清理前已经发给配置的 VLM。 | 覆盖所有技能文本、元数据和附件；在首次保存及外发模型前执行秘密检测。资源/记忆/会话应使用统一敏感数据策略，以引用替代密钥，并支持无需向模型提交原值的确定性保存接口。依据：[SkillLoader](../../openviking/core/skill_loader.py)、[技能写入与附件](../../openviking/utils/skill_processor.py)、[MCP remember](../../openviking/server/mcp_endpoint.py)、[会话保存](../../openviking/session/session.py)。附件/派生数据扩散是代码链路风险，本次未运行真实模型泄漏评测。 |
| P0 | **密钥还原后可能再次被保存。** `read` 会把实际值注入上下文；未引用配置也被完整追加到 Notice。采集过滤只改文本，工具输入/输出保持原样，即使配置文本脱敏规则也无效。工具结果采集默认因 harness 而异，DSH 默认开启，不能笼统认为所有插件都默认采集工具结果。 | 普通接入允许 Agent 经字段级、权限受控接口显式还原，但 Notice 只能列 owner/键名/状态，还原值不能随整个 target 返回；工具输入、输出、错误、会话采集和再次写入统一经过 Sanitizer。Gateway 可在内部解析和注入，避免明文进入模型。已复现 Notice 回显及文本过滤生效而工具载荷不变；依据：[还原器](../../openviking/privacy/skill_restore.py)、[采集过滤](../../examples/codex-memory-plugin/scripts/shared/capture-utils.mjs)、[默认配置](../../examples/codex-memory-plugin/scripts/shared/config-schema.mjs)。 |
| P0 | **版本写入缺少多文件事务保障。** `upsert` 依次写 history、current、meta，读操作不持同一锁。meta 写入失败后 current 可以已切到新版本，但 meta 仍为旧版本；下一次写入会复用版本号并覆盖历史。锁防并发写入，不能解决部分写入和读取中间态。 | 引入原子版本发布/提交指针及故障恢复，版本号不能只依赖可能过时的 meta。验证 history、current、meta 的一致性和历史不可覆盖；对 activate、取消、重启也做故障注入。已用真实配置服务加内存存储故障注入复现，见下一节；依据：[配置服务](../../openviking/privacy/service.py)。 |
| P1 | **保留占位符的技能更新可能删掉仍需要的配置。** `PUT /skills/{name}` 对空提取结果执行 `delete_if_empty=True`。传入已占位符化内容、模型返回缺值字段时，仍有配置引用却会走删除分支。现有测试只覆盖“内容确实不再需要配置时删除”。 | 检查现存占位符与字段引用，区分未提供值、显式删除和提取失败；保留仍被引用的值。已在实际 prepare/apply 方法组合中复现删除调用；完整 HTTP 情景应补回归测试。依据：[技能更新](../../openviking/server/routers/skills.py)、[apply_skill_privacy](../../openviking/utils/skill_processor.py)、[现有删除测试](../../tests/server/test_api_skills.py)。 |
| P1 | **核心 Privacy 回归没有明确接入现有 CI。** `tests/server` 中相关测试可本地运行，但工作流中的主 API 集成任务运行 `tests/api_test`，该目录无 Privacy 专项测试；Lite 任务仅运行 cuVS 指定测试。当前配置中未发现直接运行这些 Privacy 核心测试的 job，也未配置 Privacy 覆盖率门槛。 | 增加 PR 必跑的 Privacy 回归任务，将本简报列出的安全不变量列为门禁；涉及提示词或 Agent 技能的 Markdown/YAML 修改也要触发。依据：[API CI](../../.github/workflows/api_test.yml)、[PR CI](../../.github/workflows/pr.yml)、[Lite CI](../../.github/workflows/_test_lite.yml)、[pytest 配置](../../pyproject.toml)。本次审查的是仓库配置，未核验远端 branch protection 和 CI 历史运行。 |
| P2 | **版本记录不等于完整安全审计或删除。** `get_current/get_version` 不更新 `last_accessed_at`，也未在 Privacy 服务记录逐次读取审计；旧密钥长期存在历史快照。全文 CLI 输出、命令参数、本地 JSON 文件和备份都是额外副本；存储快照枚举默认没有排除 Privacy。 | 增加读取/使用审计、历史保留/销毁策略、默认脱敏和输入 stdin 等方式；备份与加密策略纳入生命周期。依据：[配置服务](../../openviking/privacy/service.py)、[CLI](../../crates/ov_cli/src/commands/privacy.rs)、[快照枚举](../../crates/ragfs/src/git/enumerate.rs)。是否实际备份取决于部署，本次未核验外部备份。 |
| P2 | **部分更新和目标命名容易造成误操作。** HTTP upsert 整包替换；CLI `--key-*` 是先读再合并再写，两个客户端并行更新不同键仍可能丢更新。`category=skill` 的同名目标没有独立的服务/账号/环境维度。 | 增加原子 PATCH 或 expected_version/CAS；明确命名及绑定规则。人工保存非技能凭据时按服务、环境、账号组织目标，并告知它们不会自动在技能读取中还原。依据：[Privacy API](api/10-privacy.md)、[CLI 合并写入](../../crates/ov_cli/src/commands/privacy.rs)、[技能还原](../../openviking/service/fs_service.py)。并行 CLI 丢更新是读改写语义分析，本次未执行双客户端复现。 |

## 4. 本次验证与现有测试的证明范围

本地使用 macOS / Python 3.12。所有复现只使用虚构密钥，未调用真实模型或外部账号系统。

现有测试执行命令：

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -p pytest_asyncio.plugin \
  -q -o addopts='' --tb=short \
  tests/server/test_privacy_config_service.py \
  tests/server/test_api_privacy_configs.py \
  tests/server/test_skill_privacy_lock.py \
  tests/unit/test_skill_privacy_cancellation.py \
  tests/session/test_commit_skill_inference.py

PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -p pytest_asyncio.plugin \
  -q -o addopts='' --tb=short \
  tests/server/test_api_skills.py tests/server/test_skill_update_lock.py \
  -k 'privacy or rollback'
```

第一组 **35 passed**；第二组 **6 passed、15 deselected**，共 **41 个选定的相关测试通过**。上述命令使用显式插件并关闭自动插件加载。运行未开启覆盖率，因此不声称已经获得 Privacy 覆盖率统计。

| 测试层 | 已有保障 | 仍缺的关键证明 |
|---|---|---|
| 配置服务/API | 版本递增、同值去重、激活、增加键、404；部分底层错误传播 | 多文件故障一致性、损坏数据恢复、重启、读取中间态、原子部分更新 |
| 抽取/还原 | 固定模型返回值、引用恢复、缺值与额外配置 Notice、引号/换行/CRLF/正则字符处理 | 真实模型识别质量；Bearer、自然语言、注释、重复残留、私钥、提示注入、元数据/附件 |
| 更新与并发 | 8 次并发写版本测试使用内存存储锁；另有服务级更新回滚、等待写入和取消释放锁测试 | 多进程真实存储竞争、进程崩溃、带占位符更新、历史快照不被覆盖；不能把单进程测试扩大为分布式保证 |
| 身份与隔离 | 当前用户路径写入和通用命名空间策略；API 测试主要使用 DevAuth/ROOT | Privacy 专项的无密钥/普通用户/跨用户/跨账户读写历史拒绝测试，以及共享技能的每用户绑定 |
| Agent 与整条链路 | 插件有采集和文本过滤测试；训练产出技能有隐私处理调用测试 | Agent 是否选对 Privacy、是否避免回显；原值是否进入 messages/history/记忆/摘要/工具日志/导出；真实模型与完整 Agent 的行为评测 |

**额外执行复现（调用当前实现，非正式回归测试）：**

- 已给提取器正确的虚构值：`api_key=FAKE_SECRET` 能替换；`Authorization: Bearer FAKE_SECRET`、`密码是 FAKE_SECRET`、`api_key=FAKE_SECRET # prod` 保留明文。赋值后再加 `Use FAKE_SECRET here`，Privacy 成功提取但正文仍有原值。
- VLM 返回 `I cannot process this request.` 或 `{"values":{"api_key":""}}`，提取结果为空且原正文不变；无明确失败状态。
- `restore_skill_content` 给不含引用的正文配上 `unused_key=FAKE_SECRET`，Notice 包含完整虚构密钥。
- `shapeCaptureParts` 配置替换规则后，文本中的虚构密钥变为 `[redacted]`，同一消息的 `tool_output` 中原值保留。
- 对 `UserPrivacyConfigService` 的 `.meta.json` 写入注入异常：先写 v1，再写 v2 失败后得到 `meta.active_version=1`、`current.version=2`；随后写另一值仍分配 v2，并覆盖原来的 `history/version_002.json`。
- 对包含 `{{ov_privacy:skill:audit-skill:api_key}}` 的内容调用 `prepare_skill_privacy`，VLM 返回空字段后，再以 `delete_if_empty=True` 调用 `apply_skill_privacy`：内容仍有引用，配置删除方法被调用。

## 5. 推荐的 Agent 使用流程

**当前可以通过 HTTP/CLI 人工管理秘密，但尚无经过验证的“接入即可自动学会”流程。** `remember`、普通 `write`、资源导入都不应被当作外部账号密钥的保存入口；也不应为了利用自动抽取而先把真实密钥写进技能正文。

建议把如下流程落实为工具协议和 Agent 接入技能，而不是只添加一句“注意隐私”：

1. 接收到账号密码、AK/SK、token、私钥等时，先识别所属用户、服务、环境和账号，选定 Privacy 目标。持久化技能只写字段声明或引用。
2. 使用专用工具保存值，工具返回带 owner 的统一引用、键名和版本号；普通回复与记忆只记“已配置”及用途。现有 HTTP 写入会回显值，接入包装器应处理响应及采集内容。
3. 使用时，普通接入允许 Agent 在当前身份权限内通过字段级接口显式还原；Gateway 接入优先在内部解析并注入。两条路径都必须在工具输出、错误、会话采集和再次写入时重新脱敏。
4. owner 不同、值缺失、提取失败或权限不足时返回 `forbidden/missing` 和可联系的 owner；不把未解析引用当成密钥，不通过搜索绕过权限。外部凭据轮换后更新 Privacy；明确回滚不能恢复已被第三方撤销的密钥。
5. 更新技能保留仍被引用的配置；移除技能/账号时清理 current、history 及保留策略涵盖的副本。用元信息验证成功，不通过打印密钥确认。

## 6. 建议的验收顺序

1. **先实现高效写入 Sanitizer 和输出防线。** 覆盖正文、frontmatter、附件、普通写入、资源、memory、摘要、索引和采集的虚构秘密样本；验证 user 写入及 `/agent/skills` 写入均生成 owner 绑定引用，失败必须阻止发布或转入明确状态。
2. **补引用解析、身份与 Agent/Gateway 回归。** 验证 owner 本人字段级还原、其他用户得到 forbidden 与 owner 提示、缺值处理、轮换后解析 active value；分别验证 Agent 显式还原和 Gateway 内部注入不会把值再次写回内容或会话。
3. **提供显式存量扫描。** 验证 `ov privacy scan` 默认只报告，`--fix` 使用内容 revision、刷新摘要和索引，且不越过用户权限；暂不把 Privacy upsert 后全量反向扫描设为默认行为。
4. **补事务回归并接入 PR CI。** 对 history/current/meta 每一步注入写失败、取消及重启；检查版本一致、历史不覆盖，并把 Sanitizer、引用解析、身份隔离和 CLI 修复测试设为门禁。覆盖率辅助发现未测分支，不能替代安全断言。
5. **再验证真实 Agent 行为。** 用虚构外部账号构建完整任务：保存凭据、读取公共技能、owner/非 owner 还原、轮换、缺配置和修复；检查模型回复、工具调用和会话中是否出现非预期明文，并记录模型与提示词版本。

完成这些验收前，适合将 Privacy 定位为**有用的敏感配置基础设施**；生产凭据的安全性仍需要接入层、执行层和存储生命周期共同落实。
