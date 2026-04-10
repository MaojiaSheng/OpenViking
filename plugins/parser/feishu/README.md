# Feishu Parser Plugin

Feishu/Lark 云文档解析器插件。

## 支持的文档类型

- **飞书文档**: `https://*.feishu.cn/docx/{document_id}`
- **飞书 Wiki**: `https://*.feishu.cn/wiki/{token}`
- **飞书表格**: `https://*.feishu.cn/sheets/{token}`
- **飞书多维表格**: `https://*.feishu.cn/base/{app_token}`

## 安装依赖

```bash
pip install lark-oapi>=1.0.0
```

或者使用 OpenViking 的可选依赖：

```bash
pip install 'openviking[bot-feishu]'
```

## 配置

需要配置飞书应用凭证。在 `ov.conf` 中通过 `plugins.feishu` 配置：

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

### 配置字段说明

| 字段 | 说明 | 必填 | 默认值 |
|------|------|------|--------|
| `app_id` | 飞书应用 App ID | 是 | `""` |
| `app_secret` | 飞书应用 App Secret | 是 | `""` |
| `domain` | 飞书 API 域名 | 否 | `https://open.feishu.cn` |
| `max_rows_per_sheet` | 表格最大读取行数 | 否 | `1000` |
| `max_records_per_table` | 多维表格最大读取记录数 | 否 | `1000` |

### 环境变量

也可以通过环境变量配置（优先级高于配置文件）：

```bash
export FEISHU_APP_ID="your_app_id"
export FEISHU_APP_SECRET="your_app_secret"
```

## 使用方法

```python
from openviking.parse import parse

# 直接解析飞书文档 URL
result = await parse("https://your-domain.feishu.cn/docx/doxcnabc123")
```

## 获取凭证

1. 访问 [飞书开放平台](https://open.feishu.cn)
2. 创建企业自建应用
3. 获取 App ID 和 App Secret
4. 配置应用权限（读取文档、表格等）
