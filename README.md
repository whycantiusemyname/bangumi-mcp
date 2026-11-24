# bangumi-mcp

> [中文说明](#中文说明) | [English](#english)

---

## 中文说明

功能完整、面向 LLM 脱水优化的 **Bangumi (bgm.tv) API v0 MCP Server + 轻量 CLI**。

- **免 Token 开箱即用**：搜索、条目详情、关联人物/角色/条目、章节列表、每日放送日历、用户公开收藏全量拉取、**批量推荐去重核验**、目录读取全部免鉴权直跑。
- **可选个人读写**：配好 `BANGUMI_ACCESS_TOKEN` 即可直接维护个人收藏、评分/标签/短评、单集与批量追番进度、角色/人物收藏、目录增删改；不配 Token 时优雅提示，不影响任何公开只读能力。
- **为 LLM 上下文省 Token**：自动脱水压缩冗余图片字典、评分直方图与过长简介，保留核心结构化字段与 `https://bgm.tv/...` 直达链接。
- **内置批量去重核验（`check_user_collections`）**：传入一组番名或 `subject_id`（支持整数或 `id:10380`），先独立解析作品身份再对照用户收藏库标出「看过 / 在看 / 想看 / 搁置 / 抛弃 / 未收藏 / 核验失败」，避免第一季误判第二季或把纯数字番名（如 `86`）误当 ID。
- **安全边界清晰**：MCP 侧全量同步严格只读（不写本机文件，导出请用 `bangumi-cli sync -o`）；非幂等写请求不自动重放；`streamable-http` 模式默认禁用个人 Token（仅允许本机 loopback 显式加 `--allow-token-over-http` 开启）。

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
# 默认以公开只读模式运行（不暴露环境中的 BANGUMI_ACCESS_TOKEN）
uvx --from git+https://github.com/whycantiusemyname/bangumi-mcp \
  bangumi-mcp --transport streamable-http --host 127.0.0.1 --port 8765 --path /mcp

# 若确需在本机 loopback HTTP 上启用个人 Token 读写，显式传入 --allow-token-over-http（禁止非本机地址）
bangumi-mcp --transport streamable-http --host 127.0.0.1 --port 8765 --allow-token-over-http
```

### 环境变量

| 变量名 | 必填 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `BANGUMI_ACCESS_TOKEN` | 否 | 无 | Bangumi Personal Access Token，仅个人读写接口需要（非本机 `http://` 将被拒绝发送） |
| `BANGUMI_DEFAULT_USERNAME` | 否 | 无 | 默认 Bangumi 用户名，调用用户相关 MCP 工具及 `bangumi-cli sync/check/user` 时可省略用户名 |
| `BANGUMI_USER_AGENT` | 否 | `whycantiusemyname/bangumi-mcp/<ver> (...)` | 符合 Bangumi API 规范的自定义 `User-Agent` |
| `BANGUMI_BASE_URL` | 否 | `https://api.bgm.tv` | API 基础地址 |
| `BANGUMI_TIMEOUT` | 否 | `20.0` | HTTP 请求超时（秒） |
| `BANGUMI_MAX_RETRIES` | 否 | `4` | 仅针对只读请求的 429 / 5xx 最大重试次数（指数退避 + `Retry-After` 秒数/HTTP 日期） |
| `BANGUMI_MAX_RETRY_AFTER` | 否 | `30.0` | `Retry-After` 最大等待预算（秒），超出则直接返回限流提示 |
| `BANGUMI_CACHE_TTL` | 否 | `300.0` | 用户完整收藏库内存缓存有效期（秒），带并发合并与写后自动失效 |

### MCP 工具清单（共 33 个）

**公开只读（20 个，免 Token）**

| 分类 | 工具名 | 说明 |
| --- | --- | --- |
| 条目检索与浏览 | `search_subjects`, `browse_subjects` | 高级搜索（类型/标签/meta_tags/发售日/评分/排名/排序）与分类浏览 |
| 条目详情与关联 | `get_subject`, `get_subject_persons`, `get_subject_characters`, `get_subject_relations` | 条目完整脱水信息、制作人员、登场角色与 CV、关联续作/原作 |
| 章节与放送日历 | `get_episodes`, `get_episode`, `get_calendar` | 章节分页查询、单集详情、每日放送表（支持 `today` / 周一~周日过滤） |
| 角色与现实人物 | `search_characters`, `get_character`, `search_persons`, `get_person` | 角色/声优/导演/制作公司检索、详情与关联条目 |
| 用户收藏与去重 | `get_user`, `get_user_collections`, `get_user_subject_collection`, `sync_user_collections`, `check_user_collections`, `get_user_favorites` | 用户资料、单页/单条目收藏、全 5 类分页同步与完整性统计、**批量去重核验**、收藏角色与人物 |
| 目录读取 | `get_index` | 读取公开目录详情及其收录条目 |

**个人鉴权读写（13 个，需 `BANGUMI_ACCESS_TOKEN`）**

| 分类 | 工具名 | 说明 |
| --- | --- | --- |
| 当前用户 | `get_me` | 获取当前 Token 对应的登录用户信息 |
| 收藏管理 | `upsert_collection` | 新增/修改条目收藏状态、评分（0-10）、标签、短评、私密标记与书籍进度 |
| 追番进度 | `get_episode_progress`, `update_episode_status`, `batch_update_episodes` | 读取/单集更新/批量更新章节观看状态（未收藏/想看/看过/抛弃） |
| 角色与人物收藏 | `set_character_collection`, `set_person_collection` | 收藏角色/现实人物（注：上游 `bangumi/server` 目前暂未开放角色/人物取消收藏 `DELETE` 路由，`collect=false` 会明确提示） |
| 目录维护 | `create_index`, `update_index`, `add_index_subject`, `update_index_subject`, `remove_index_subject`, `set_index_collection` | 创建/编辑目录、增删改目录条目（修改条目需同时传 `sort` 与 `comment`）、收藏/取消收藏目录 |

### 轻量 CLI (`bangumi-cli`)

```bash
# 全量拉取用户 5 大类收藏并导出 JSON（含统计 + 收藏角色/人物）
bangumi-cli sync <username> --favorites -o collections.json

# 仅拉取动画收藏
bangumi-cli sync <username> --types anime -o anime.json

# 批量推荐去重核验（支持番名与 subject_id 混传，也可配 BANGUMI_DEFAULT_USERNAME 省略 -u 或用 --file）
bangumi-cli check -u <username> "葬送的芙莉莲" "孤独摇滚" id:10380 --types anime

# 快速查新番表 / 搜番 / 查条目
bangumi-cli calendar --weekday today
bangumi-cli search "命运石之门" --types anime --sort rank --limit 5
bangumi-cli subject 10380
```

---

## English

A full-featured, LLM-friendly **Bangumi (`bgm.tv`) API v0 MCP Server + lightweight CLI**.

### Highlights

- **Zero-auth public read-only tools (20 tools)**: Subject search (`POST /v0/search/subjects`) & browse, subject details/staff/characters/relations, episodes, weekly broadcast calendar (`/calendar`), characters & persons search/details, public user profiles/collections/favorites, full 5-category collection sync with completeness tracking, **batch recommendation deduplication**, and public index reading.
- **Optional personal read/write tools (13 tools)**: Set `BANGUMI_ACCESS_TOKEN` to manage your own collections, ratings/tags/comments, single & batch episode watch progress, character/person collecting, and curated indices. Missing token yields a clear `AUTH_REQUIRED` MCP tool error without affecting read-only tools.
- **Safe by default**: MCP `sync_user_collections` never writes local files (use `bangumi-cli sync -o`); mutating requests never auto-retry on ambiguous failures; `streamable-http` disables `BANGUMI_ACCESS_TOKEN` by default unless explicitly opted in on a loopback address (`--allow-token-over-http`).
- **Built-in Recommendation Deduplicator (`check_user_collections`)**: Separates subject identity resolution from collection lookup, surfaces cross-media ambiguity, guards against cross-season false positives and numeric titles like `"86"`, and reports `unknown` if fallback search fails.

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
