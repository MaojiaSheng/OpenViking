# Privacy Configs

Privacy configs manage sensitive values by `category + target_key` (for example, a skill's `api_key` and `base_url`).

Changed values create a version snapshot. You can query history and switch the active version. Submitting the same values as the current version does not create a new version.

These examples use the current user’s API key. In trusted mode, supply the identity headers required by your deployment. Reads and CLI output contain the stored values; `***` below is an example placeholder, not automatic redaction.

Activating a version changes only the values stored in OpenViking. It does not rotate, revoke, or restore credentials at the external provider.

## Endpoint Summary

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/privacy-configs` | List privacy config categories |
| POST | `/api/v1/privacy-configs/scan` | Scan or repair registered values in stored content |
| GET | `/api/v1/privacy-configs/{category}` | List targets under a category |
| GET | `/api/v1/privacy-configs/{category}/{target_key}` | Get active config (`meta + current`) |
| GET | `/api/v1/privacy-configs/{category}/{target_key}/field` | Get a field reference; optionally reveal its value |
| POST | `/api/v1/privacy-configs/resolve` | Explicitly reveal a field by reference or URI |
| POST | `/api/v1/privacy-configs/{category}/{target_key}` | Upsert and activate a new/current version |
| DELETE | `/api/v1/privacy-configs/{category}/{target_key}` | Delete a target and every version |
| DELETE | `/api/v1/privacy-configs/{category}/{target_key}/field` | Remove a field from the active config |
| DELETE | `/api/v1/privacy-configs/selector` | Delete by target URI or field reference/URI |
| GET | `/api/v1/privacy-configs/{category}/{target_key}/versions` | List version numbers |
| GET | `/api/v1/privacy-configs/{category}/{target_key}/versions/{version}` | Get a specific version snapshot |
| POST | `/api/v1/privacy-configs/{category}/{target_key}/activate` | Activate a specific version |

---

## Common Use Cases

- Store sensitive settings for a skill
- Rotate keys by writing a new version
- Roll back to an old version
- Restore placeholders in skill content at read time

---

## Scan Stored Content

Explicitly scan persisted text. The default is a dry run and never returns the matched value. With `fix=true`, unambiguous matches are replaced and affected content is refreshed.

```text
POST /api/v1/privacy-configs/scan
```

```json
{
  "scopes": ["resources", "skills", "memories"],
  "target_uri": "",
  "fix": false,
  "wait": false,
  "node_limit": 10000
}
```

Use either `scopes` or `target_uri`. When one value maps to multiple Privacy fields, the result reports `ambiguous` and never chooses a reference arbitrarily.

---

## Data Structures

### current (active version snapshot)

```json
{
  "version": 3,
  "category": "skill",
  "target_key": "byted-viking-search-knowledgebase",
  "values": {
    "api_key": "***",
    "base_url": "https://example.com"
  },
  "created_at": "2026-04-27T10:00:00+08:00",
  "created_by": "alice",
  "change_reason": "rotate key"
}
```

### meta

```json
{
  "category": "skill",
  "target_key": "byted-viking-search-knowledgebase",
  "active_version": 3,
  "latest_version": 5,
  "created_at": "2026-04-21T10:00:00+08:00",
  "updated_at": "2026-04-27T10:00:00+08:00",
  "updated_by": "alice",
  "last_accessed_at": "2026-04-27T10:00:00+08:00",
  "labels": {
    "env": "prod"
  }
}
```

---

## API Reference

### list_privacy_categories()

List categories that have privacy configs for the current user.

**HTTP API**

```
GET /api/v1/privacy-configs
```

```bash
curl -X GET http://localhost:1933/api/v1/privacy-configs \
  -H "X-API-Key: your-key"
```

**Response**

```json
{
  "status": "ok",
  "result": ["skill"]
}
```

---

### list_privacy_targets()

List target keys under a category.

**HTTP API**

```
GET /api/v1/privacy-configs/{category}
```

```bash
curl -X GET http://localhost:1933/api/v1/privacy-configs/skill \
  -H "X-API-Key: your-key"
```

**Response**

```json
{
  "status": "ok",
  "result": ["byted-viking-search-knowledgebase"]
}
```

---

### get_privacy_current()

Get active config for a target (`meta + current`).

**HTTP API**

```
GET /api/v1/privacy-configs/{category}/{target_key}
```

```bash
curl -X GET "http://localhost:1933/api/v1/privacy-configs/skill/byted-viking-search-knowledgebase" \
  -H "X-API-Key: your-key"
```

**Response**

```json
{
  "status": "ok",
  "result": {
    "meta": {
      "category": "skill",
      "target_key": "byted-viking-search-knowledgebase",
      "active_version": 3,
      "latest_version": 5
    },
    "current": {
      "version": 3,
      "category": "skill",
      "target_key": "byted-viking-search-knowledgebase",
      "values": {
        "api_key": "***",
        "base_url": "https://example.com"
      }
    }
  }
}
```

> Returns `NOT_FOUND` if the target does not exist.

---

### get_privacy_field()

Get one field from the active version. By default the endpoint returns an owner-bound reference and configuration status without returning the value. Add `reveal=true` to explicitly read that one field for immediate use.

```text
GET /api/v1/privacy-configs/{category}/{target_key}/field?field={field}&reveal=false
```

```json
{
  "status": "ok",
  "result": {
    "owner_user_id": "alice",
    "category": "credential",
    "target_key": "github-prod",
    "field": "api_key",
    "version": 1,
    "configured": true,
    "reference": "{{ov_privacy:alice:viking://~/privacy/credential/github-prod#/values/api_key}}"
  }
}
```

With `reveal=true`, the response also contains that field's `value`. Sibling fields are never returned. A missing target or field returns `NOT_FOUND`.

An owner-bound reference or field URI can instead be sent to the selector endpoint:

```text
POST /api/v1/privacy-configs/resolve
```

```json
{"selector":"{{ov_privacy:alice:viking://~/privacy/credential/github-prod#/values/api_key}}"}
```

Field URIs may use `viking://~/privacy/...#/values/...` or an explicit `viking://user/{user_id}/privacy/...#/values/...`. An explicit owner that differs from the current identity returns `PERMISSION_DENIED`.

References generated, stored, and returned by OpenViking always use the whitespace-free canonical form. The parser accepts spaces or tabs immediately after `{{` and before `}}`, such as `{{ ov_privacy:alice:... }}`, then normalizes the result to `{{ov_privacy:alice:...}}`. Whitespace is not accepted inside the owner, URI, or path tokens.

---

### upsert_privacy_config()

Write a new version and set it as active.

**Behavior**

- `values` replaces the complete value map for that version; omitted keys are absent from the new snapshot
- New keys are allowed and persisted
- If `values` is identical to the current version, no new version is created

**HTTP API**

```
POST /api/v1/privacy-configs/{category}/{target_key}
```

**Request Body**

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| values | object | Yes | - | Privacy key-value pairs |
| change_reason | string | No | "" | Reason for change |
| labels | object | No | null | Labels stored in meta |

```bash
curl -X POST "http://localhost:1933/api/v1/privacy-configs/skill/byted-viking-search-knowledgebase" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: your-key" \
  -d '{
    "values": {
      "api_key": "secret-2",
      "base_url": "https://example.com",
      "region": "cn"
    },
    "change_reason": "rotate key",
    "labels": {
      "env": "prod"
    }
  }'
```

**Response**

```json
{
  "status": "ok",
  "result": {
    "version": 4,
    "category": "skill",
    "target_key": "byted-viking-search-knowledgebase",
    "values": {
      "api_key": "secret-2",
      "base_url": "https://example.com",
      "region": "cn"
    },
    "change_reason": "rotate key"
  }
}
```

---

### delete_privacy_config()

Delete a target's current value, metadata, and complete version history. Repeated deletion is safe: a missing target returns `deleted: false`.

```text
DELETE /api/v1/privacy-configs/{category}/{target_key}
```

```json
{
  "status": "ok",
  "result": {
    "category": "credential",
    "target_key": "github-prod",
    "deleted": true
  }
}
```

Field deletion affects only the active configuration and does not expose a version parameter. If fields remain, it publishes a new active snapshot without that field and keeps historical snapshots. Removing the final field deletes the complete target, including current values, metadata, and all history, and returns `target_deleted: true`.

```text
DELETE /api/v1/privacy-configs/{category}/{target_key}/field?field={field}
```

Target URIs, field URIs, and owner-bound references can also be deleted through:

```text
DELETE /api/v1/privacy-configs/selector
```

```json
{"selector":"viking://~/privacy/credential/github-prod#/values/api_key"}
```

---

### list_privacy_versions()

List all version numbers for a target.

**HTTP API**

```
GET /api/v1/privacy-configs/{category}/{target_key}/versions
```

```bash
curl -X GET "http://localhost:1933/api/v1/privacy-configs/skill/byted-viking-search-knowledgebase/versions" \
  -H "X-API-Key: your-key"
```

**Response**

```json
{
  "status": "ok",
  "result": [1, 2, 3, 4]
}
```

> Returns `NOT_FOUND` if the target does not exist.

---

### get_privacy_version()

Get one version snapshot.

**HTTP API**

```
GET /api/v1/privacy-configs/{category}/{target_key}/versions/{version}
```

```bash
curl -X GET "http://localhost:1933/api/v1/privacy-configs/skill/byted-viking-search-knowledgebase/versions/2" \
  -H "X-API-Key: your-key"
```

**Response**

```json
{
  "status": "ok",
  "result": {
    "version": 2,
    "category": "skill",
    "target_key": "byted-viking-search-knowledgebase",
    "values": {
      "api_key": "secret-1",
      "base_url": "https://example.com"
    }
  }
}
```

> Returns `NOT_FOUND` if target/version does not exist.

---

### activate_privacy_version()

Switch active version.

**HTTP API**

```
POST /api/v1/privacy-configs/{category}/{target_key}/activate
```

**Request Body**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| version | int | Yes | Version number to activate |

```bash
curl -X POST "http://localhost:1933/api/v1/privacy-configs/skill/byted-viking-search-knowledgebase/activate" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: your-key" \
  -d '{"version": 2}'
```

**Response**

```json
{
  "status": "ok",
  "result": {
    "version": 2,
    "category": "skill",
    "target_key": "byted-viking-search-knowledgebase",
    "values": {
      "api_key": "secret-1",
      "base_url": "https://example.com"
    }
  }
}
```

> Returns `NOT_FOUND` if target/version does not exist.

---

## CLI Quick Operations

```bash
# Categories and targets
ov privacy categories
ov privacy list skill

# Active config (shortcut supported)
ov privacy get skill byted-viking-search-knowledgebase
ov privacy skill byted-viking-search-knowledgebase

# Get the owner-bound reference without returning the value
ov privacy reference credential github-prod api_key

# Explicitly reveal one field in the active version
ov privacy resolve credential github-prod api_key
ov privacy resolve '{{ov_privacy:alice:viking://~/privacy/credential/github-prod#/values/api_key}}'
ov privacy resolve 'viking://~/privacy/credential/github-prod#/values/api_key'

# Upsert with full JSON snapshot
ov privacy upsert skill byted-viking-search-knowledgebase \
  --values-json '{"api_key":"secret-2","base_url":"https://example.com"}'

# Read values from a local JSON file instead of command arguments
ov privacy upsert skill byted-viking-search-knowledgebase --values-file ./privacy-values.json

# Partial key update (CLI merges with current first)
ov privacy upsert skill byted-viking-search-knowledgebase \
  --key-api_key secret-3

# Version query and activation
ov privacy versions skill byted-viking-search-knowledgebase
ov privacy version skill byted-viking-search-knowledgebase 2
ov privacy activate skill byted-viking-search-knowledgebase 2

# Delete the target and every version; non-interactive use requires --yes
ov privacy delete credential github-prod --yes
ov privacy delete 'viking://~/privacy/credential/github-prod' --yes

# Remove the active field; historical snapshots remain
ov privacy delete credential github-prod api_key --yes
ov privacy delete '{{ov_privacy:alice:viking://~/privacy/credential/github-prod#/values/api_key}}' --yes

# Stored-content scans are dry-run unless --fix is passed
ov privacy scan --scope resources,skills,memories
ov privacy scan --target viking://~/resources/project-a --fix --wait
```

---

## Related Documentation

- [Skills](04-skills.md) - Skill write/read APIs
- [File System](03-filesystem.md) - `read`/`write`/`ls`
- [System](07-system.md) - System status and observability
