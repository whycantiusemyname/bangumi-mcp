# bangumi-mcp

> [中文说明](#中文说明) | [English](#english)

---

## 中文说明

功能完整、面向 LLM 脱水优化的 **Bangumi (bgm.tv) API v0 MCP Server + 轻量 CLI**。

- **免 Token 开箱即用**：搜索、条目详情、关联人物/角色/条目、章节列表、每日放送日历、用户公开收藏全量拉取、**批量推荐去重核验**、目录读取全部免鉴权直跑。
- **可选个人读写**：配好 `BANGUMI_ACCESS_TOKEN` 即可直接维护个人收藏、评分/标签/短评、单集与批量追番进度、角色/人物收藏、目录增删改；不配 Token 时优雅提示，不影响任何公开只读能力。
- **为 LLM 上下文省 Token**：自动脱水压缩冗余图片字典、评分直方图与过长简介，保留核心结构化字段与 `https://bgm.tv/...` 直达链接。
- **内置批量去重核验（`check_user_collections`）**：传入一组番名或 `subject_id`，直接对照用户 Bangumi 收藏库标出「看过 / 在看 / 想看 / 搁置 / 抛弃 / 未收藏」及个人评分与短评，未直接命中时可自动用 Bangumi 搜索解析标准 `subject_id` 二次核对，彻底避免 AI 推番撞车。
- **双传输 + 轻量 CLI**：同时支持 `stdio` 与 `streamable-http`（`bangumi-mcp`），并附带 `bangumi-cli` 终端直跑全量同步与去重。

### 快速接入（一行 `uvx` / 本地配置）

> 公开只读无需 `env`；需要个人读写时按需加上 `BANGUMI_ACCESS_TOKEN`（申请地址：<https://next.bgm.tv/demo/access-token>）。

#### Claude Code

```bash
# 免安装直接运行（推荐）
claude mcp add bangumi -- uvx --from git+https://github.com/whycantiusemyname/bangumi-mcp bangumi-mcp

# 带默认用户名与个人 Token（可选）
claude mcp add bangumi \
  -e BANGUMI_DEFAULT_USERNAME=your_username \
  -e BANGUMI_ACCESS_TOKEN=your_token \
  -- uvx --from git+https://github.com/whycantiusemyname/bangumi-mcp bangumi-mcp
```

#### Codex CLI (`~/.codex/config.toml`)

```toml
[mcp_servers.bangumi]
command = "uvx"
args = ["--from", "git+https://github.com/whycantiusemyname/bangumi-mcp", "bangumi-mcp"]

[mcp_servers.bangumi.env]
BANGUMI_DEFAULT_USERNAME = "your_username"
# BANGUMI_ACCESS_TOKEN = "your_token"  # 可选，写操作时填写
```

#### Antigravity / Cursor / Claude Desktop（通用 MCP JSON）

```json
{
  "mcpServers": {
    "bangumi": {
      "command": "uvx",
      "args": [
        "--from",
        "git+https://github.com/whycantiusemyname/bangumi-mcp",
        "bangumi-mcp"
      ],
      "env": {
        "BANGUMI_DEFAULT_USERNAME": "your_username"
      }
    }
  }
}
```

#### 本地开发目录接入

```json
{
  "mcpServers": {
    "bangumi": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/bangumi-mcp", "bangumi-mcp"],
      "env": {
        "BANGUMI_DEFAULT_USERNAME": "your_username"
      }
    }
  }
}
```

#### Streamable HTTP 模式

```bash
uvx --from git+https://github.com/whycantiusemyname/bangumi-mcp \
  bangumi-mcp --transport streamable-http --host 127.0.0.1 --port 8765 --path /mcp
```

### 环境变量

| 变量名 | 必填 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `BANGUMI_ACCESS_TOKEN` | 否 | 无 | Bangumi Personal Access Token，仅个人读写接口需要 |
| `BANGUMI_DEFAULT_USERNAME` | 否 | 无 | 默认查询的 Bangumi 用户名，调用用户相关工具时可省略 `username` |
| `BANGUMI_USER_AGENT` | 否 | `whycantiusemyname/bangumi-mcp/<ver> (...)` | 符合 Bangumi API 规范的自定义 `User-Agent` |
| `BANGUMI_BASE_URL` | 否 | `https://api.bgm.tv` | API 基础地址 |
| `BANGUMI_TIMEOUT` | 否 | `20.0` | HTTP 请求超时（秒） |
| `BANGUMI_MAX_RETRIES` | 否 | `4` | 遇 429 / 5xx 时的最大重试次数（指数退避 + `Retry-After`） |
| `BANGUMI_CACHE_TTL` | 否 | `300.0` | 用户全量收藏库内存缓存有效期（秒），供去重工具复用 |

### MCP 工具清单（共 33 个）

**公开只读（20 个，免 Token）**

| 分类 | 工具名 | 说明 |
| --- | --- | --- |
| 条目检索与浏览 | `search_subjects`, `browse_subjects` | 高级搜索（类型/标签/meta_tags/发售日/评分/排名/排序）与分类浏览 |
| 条目详情与关联 | `get_subject`, `get_subject_persons`, `get_subject_characters`, `get_subject_relations` | 条目完整脱水信息、制作人员、登场角色与 CV、关联续作/原作 |
| 章节与放送日历 | `get_episodes`, `get_episode`, `get_calendar` | 章节分页查询、单集详情、每日放送表（支持 `today` / 周一~周日过滤） |
| 角色与现实人物 | `search_characters`, `get_character`, `search_persons`, `get_person` | 角色/声优/导演/制作公司检索、详情与关联条目 |
| 用户收藏与去重 | `get_user`, `get_user_collections`, `get_user_subject_collection`, `sync_user_collections`, `check_user_collections`, `get_user_favorites` | 用户资料、单页/单条目收藏、全 5 类分页同步与统计、**批量去重核验**、收藏角色与人物 |
| 目录读取 | `get_index` | 读取公开目录详情及其收录条目 |

**个人鉴权读写（13 个，需 `BANGUMI_ACCESS_TOKEN`）**

| 分类 | 工具名 | 说明 |
| --- | --- | --- |
| 当前用户 | `get_me` | 获取当前 Token 对应的登录用户信息 |
| 收藏管理 | `upsert_collection` | 新增/修改条目收藏状态、评分（0-10）、标签、短评、私密标记与书籍进度 |
| 追番进度 | `get_episode_progress`, `update_episode_status`, `batch_update_episodes` | 读取/单集更新/批量更新章节观看状态（未收藏/想看/看过/抛弃） |
| 角色与人物收藏 | `set_character_collection`, `set_person_collection` | 收藏或取消收藏角色、现实人物 |
| 目录维护 | `create_index`, `update_index`, `add_index_subject`, `update_index_subject`, `remove_index_subject`, `set_index_collection` | 创建/编辑目录、增删改目录条目、收藏/取消收藏目录 |

### 轻量 CLI (`bangumi-cli`)

```bash
# 全量拉取用户 5 大类收藏并导出 JSON（含统计 + 收藏角色/人物）
bangumi-cli sync <username> --favorites -o collections.json

# 仅拉取动画收藏
bangumi-cli sync <username> --types anime -o anime.json

# 批量推荐去重核验（支持番名与 subject_id 混传，也可用 --file 每行一个）
bangumi-cli check <username> "葬送的芙莉莲" "孤独摇滚" 10380 --types anime

# 快速查新番表 / 搜番 / 查条目
bangumi-cli calendar --weekday today
bangumi-cli search "命运石之门" --types anime --sort rank --limit 5
bangumi-cli subject 10380
```

---

## English

A full-featured, LLM-friendly **Bangumi (`bgm.tv`) API v0 MCP Server + lightweight CLI**.

### Highlights

- **Zero-auth public read-only tools (20 tools)**: Subject search (`POST /v0/search/subjects`) & browse, subject details/staff/characters/relations, episodes, weekly broadcast calendar (`/calendar`), characters & persons search/details, public user profiles/collections/favorites, full 5-category collection sync, **batch recommendation deduplication**, and public index reading.
- **Optional personal read/write tools (13 tools)**: Set `BANGUMI_ACCESS_TOKEN` to manage your own collections, ratings/tags/comments, single & batch episode watch progress, character/person favorites, and curated indices. Missing token yields a clear guidance message without affecting read-only tools.
- **LLM-optimized responses**: Compacts verbose Bangumi payloads (redundant image variants, raw vote histograms, bloated fields) into clean structured JSON with canonical `https://bgm.tv/...` URLs.
- **Built-in Recommendation Deduplicator (`check_user_collections`)**: Pass a batch of candidate titles and/or `subject_id`s to check against a user's collection library (`collect` / `doing` / `wish` / `on_hold` / `dropped` / `uncollected`), with normalized title matching and optional Bangumi search resolution fallback.
- **Dual MCP Transports + CLI**: Runs over `stdio` or `streamable-http` (`bangumi-mcp`), plus `bangumi-cli` for direct terminal sync, dedup, search, and calendar queries.

### Quick Setup

```bash
# Claude Code
claude mcp add bangumi -- uvx --from git+https://github.com/whycantiusemyname/bangumi-mcp bangumi-mcp

# Local development & tests
git clone https://github.com/whycantiusemyname/bangumi-mcp.git
cd bangumi-mcp
uv sync --extra dev
uv run pytest
```

### License

[MIT](./LICENSE)
