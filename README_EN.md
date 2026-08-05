# NapCat QQ Adapter

> **Language / 语言：** [中文](README.md) | [English](README_EN.md)

A QQ platform adapter based on the OneBot v11 protocol, adding QQ support to Hermes Agent.

Supports NapCat / go-cqhttp / Lagrange.OneBot / LLOneBot and other compatible implementations.

## Architecture

```
QQ Client ←→ NapCat (OneBot implementation)
                  ↓ Reverse WebSocket (NapCat connects to us)
             NapCat Adapter (hermes-qq-onebot)
                  ↓ Optional HTTP API (image sending, file retrieval)
             OneBot API
```

- **Reverse WebSocket**: The adapter runs a server; NapCat connects to it
- **HTTP API**: Optional but recommended, resolves image send timeouts, file retrieval, etc.

## Module Structure

```
napcat/
├── plugin.yaml        # Plugin metadata
├── adapter.py         # Registration entry (register function)
├── main.py            # Adapter body (NapCat适配器 class)
├── ws.py              # Reverse WS server (WS class)
├── napcat_http.py     # HTTP API caller (NapcatHttp class)
└── tools.py           # Constants, LRU cache, media download, message segment build/parse
```

## Installation

```bash
hermes plugins install landamao/hermes-qq-onebot --enable
```

## Message Tag Format

Each media type carries detailed info so the Agent can access paths or URLs directly:

| Type | Tag Format |
|------|-----------|
| Image | `[图片:file=/tmp/xxx.jpg]` or `[图片:url=https://...]` |
| Voice | `[语音:file=/tmp/xxx.ogg]` or `[语音:url=https://...]` |
| Video | `[视频:url=https://...]` or `[视频:file=/tmp/xxx.mp4]` |
| File | `[文件:name=report.pdf,file=/tmp/xxx]` or `[文件:name=report.pdf,url=https://...]` |
| Emoji | `[表情:id=123]` |
| @Mention | `@Nickname(QQ:123456)` |

## CQ Code Support

The Agent can send complex messages via CQ codes — just write them inline in the message text:

```
Check this out [CQ:image,file=/tmp/test.jpg]
```

```
Here's the file you wanted [CQ:file,file=/tmp/document.pdf,name=文档.pdf]
```

**Supported CQ code types:**
- `[CQ:at,qq=123]` — @someone
- `[CQ:image,file=path_or_URL]` — Send image
- `[CQ:record,file=path_or_URL]` — Send voice
- `[CQ:video,file=path_or_URL]` — Send video
- `[CQ:file,file=path_or_URL,name=filename]` — Send file
- `[CQ:face,id=123]` — Send emoji
- See OneBot v11 docs for more CQ codes

## Download Limits

Media exceeding the configured size is not auto-downloaded; only the URL is kept. The Agent downloads it on demand:

```yaml
extra:
  download_limits:
    image: 10MB       # Supports B/KB/MB/GB, case-insensitive
    record: 50MB
    video: 100MB
    file: 50MB
```

## Features

- Private chat / group chat message send & receive
- @Mention detection + keyword triggers
- Image, voice, file send & receive
- Reply message parsing (with smart truncation, preserving full media tags)
- Long message auto-split + merged forwarding (group chat; CQ codes extracted as standalone normal messages)
- User whitelist (deny by default, must configure explicitly)
- Emoji reactions / poke (disabled by default)

## Configuration

`~/.hermes/config.yaml`:

```yaml
platforms:
  napcat:
    enabled: true
    extra:
      # ── Reverse WS config ──
      reverse_host: "127.0.0.1"          # Listen address (default 127.0.0.1, localhost only)
      reverse_port: 6700                  # Listen port (default 6700)
      access_token: ""                    # Access token (optional, authenticates NapCat connection)
      # reverse_token works as an alias for access_token

      # ── HTTP API (recommended) ──
      http_api_url: "http://127.0.0.1:5700"  # OneBot HTTP API address
      http_api_token: ""                      # HTTP token (defaults to access_token)

      # ── Bot info ──
      bot_self_id: ""                     # Bot QQ number (optional, auto-learned from messages)

      # ── Media download limits ──
      # When file_size is available, items exceeding the limit are not downloaded; only URL kept
      # Supports B/KB/MB/GB (case-insensitive)
      download_limits:
        image: 10MB                     # Image limit (default 10MB)
        record: 10MB                    # Voice limit (default 10MB)
        video: 10MB                     # Video limit (default 10MB)
        file: 10MB                      # File limit (default 10MB)

      # ── Long message handling ──
      merge_forward_threshold: 800      # Group chat messages exceeding this length trigger merged forwarding (default 800, private chat not affected)
      forward_name: "纳西妲"            # Name shown in merged forwarding (default 纳西妲)

      # ── Reply quoting ──
      reply_text_max_length: 50         # Max chars when parsing reply-quoted messages; truncate with ellipsis beyond this (default 50)
                                         # Truncation preserves full media tags (e.g. [图片:file=...]) — won't cut mid-tag

      # ── Keyword triggers ──
      # Auto-respond when these regexes match in group chat (case-insensitive)
      mention_patterns:
        - "纳猫"
        - "帮我"

      # ── User whitelist ──
      # Empty/unset → reject all users
      # Set to "all" or "*" → allow all users
      allowed_qq_ids: "123456,789012"   # Comma-separated, list, or bare numbers all work

      # ── Emoji reactions ──
      emoji_react: false                # Random emoji reaction on message receive (default false)
```

## Environment Variables (optional)

All config items can be overridden via environment variables. Variable name = `NAPCAT_` + config key uppercased.

Priority: environment variable > config.yaml > default value

Value parsing: try JSON first (numbers, booleans, lists, dicts all supported), then recognize boolean keywords (`off/false/no` → False, `on/true/yes` → True), otherwise return string as-is.

```bash
# Basic config
NAPCAT_REVERSE_HOST=127.0.0.1
NAPCAT_REVERSE_PORT=6700
NAPCAT_ACCESS_TOKEN=your_token
NAPCAT_HTTP_API_URL=http://127.0.0.1:5700
NAPCAT_HTTP_API_TOKEN=your_http_token
NAPCAT_BOT_SELF_ID=123456789

# Boolean (these are equivalent)
NAPCAT_EMOJI_REACT=false
NAPCAT_EMOJI_REACT=off
NAPCAT_EMOJI_REACT=no

# Integer
NAPCAT_MERGE_FORWARD_THRESHOLD=1000

# JSON dict (complex values use JSON)
NAPCAT_DOWNLOAD_LIMITS='{"image":"20MB","video":"100MB"}'

# JSON array or comma-separated
NAPCAT_MENTION_PATTERNS='["纳猫","帮我"]'
NAPCAT_MENTION_PATTERNS=纳猫,帮我

# Whitelist
NAPCAT_ALLOWED_QQ_IDS=123456,789012
NAPCAT_ALLOWED_QQ_IDS='[123, 456]'        # JSON array works too
NAPCAT_ALLOWED_QQ_IDS=123456              # Single bare number works too

# Whitelist alias (only effective when config doesn't set allowed_qq_ids)
NAPCAT_ALLOWED_USERS=123456,789012

# Allow all users (set to true to skip whitelist)
NAPCAT_ALLOW_ALL_USERS=false
```

## NapCat Side Configuration

Set up reverse WS connection in NapCat's config file:

```json
{
  "ws_reverse": {
    "enable": true,
    "url": "ws://127.0.0.1:6700",
    "reconnect_interval": 3000,
    "token": ""
  }
}
```

If you configured `access_token`, NapCat must also set the same token.

## Startup Output

Hermes' default log level is WARNING; `logger.info()` output is invisible to users, which can cause the false impression that the plugin isn't loaded. Therefore infrequent important info logs (connect/disconnect/startup/exception) also `print()` to the terminal; frequent ones (message send/receive) don't print.

A config summary is printed at startup for easy troubleshooting:

```
[NapCat插件] 反向WS模式启动，等待 NapCat 连接 端口 6700
[NapCat插件] HTTP接口已启用: http://127.0.0.1:5700
[NapCat插件] 配置: 监听地址=127.0.0.1 端口=6700 令牌=已设置
[NapCat插件] 配置: HTTP接口=已启用 表情回应=未启用
[NapCat插件] 配置: 机器人QQ号=未设置(自动学习) 合并转发阈值=800 引用文本最大字数=50
[NapCat插件] 配置: 允许所有用户=否 白名单用户(2): 123456, 789012
[NapCat插件] 配置: 下载限制={'image': '10MB', 'record': '10MB', 'video': '10MB', 'file': '10MB'}
[NapCat插件] 配置: 关键词触发模式数=2
```

## Uninstall

```bash
rm -rf ~/.hermes/plugins/napcat
hermes gateway restart
```

---

<details>
<summary><b>📖 Differences from v2.x (click to expand)</b></summary>

v3.0.0 is a refactored upgrade from v2.1.x with identical functionality. Details below:

### Code Structure

| Item | v2.1.x (old) | v3.0.0 (new) |
|------|-------------|-------------|
| File organization | Monolithic `napcat_adapter.py` (1530 lines) | Modular split into 5 files |
| WS server | Embedded in main file | Standalone `ws.py` (WS class) |
| HTTP caller | Embedded in adapter | Standalone `napcat_http.py` (NapcatHttp class) |
| Utility functions | Embedded in main file | Standalone `tools.py` with `__all__` export list |
| API boundaries | None, all code interdependent | Clear module boundaries |

### Config Type Validation

- **Old**: `extra_config.get()` + `os.getenv()` simple fallback, no type checking, invalid input silently passes
- **New**: `获取配置()` helper function, each field validated with `isinstance`; invalid values raise `ValueError` with detailed error info

### Environment Variable Reading

- **Old**: Config items read directly from `os.getenv()`, only handles strings; env vars and config file are two independent logic paths
- **New**: Unified through `获取配置()` function, supports JSON parse + boolean keyword recognition + string fallback

### Security

| Item | v2.1.x | v3.0.0 |
|------|--------|--------|
| Default listen address | `0.0.0.0` (all interfaces) | `127.0.0.1` (localhost only) |
| Empty whitelist | Implicitly allows all users | Rejects all users, prints warning at startup |
| Allow all users | No explicit mechanism | Must set `"all"` or `"*"` to allow |

### Other Changes

- **Private chat session ID**: `napcat_{userID}` → `napcat_private_{userID}`
- **Global state**: Removed `_全局接口调用器` global variable; WS instance held by adapter
- **WS API timeout**: 60s → 120s (accommodates slow operations like large file retrieval)
- **WS event filtering**: `post_type == "meta"` → `"meta_event"` (OneBot v11 standard field name)
- **Whitelist parsing**: Added `int`/`float` support (YAML bare numbers auto-converted to string)
- **HTTP API token**: Added `http_api_token`, defaults to `access_token`
- **Startup output**: Infrequent important info logs also `print()` to terminal (Hermes defaults to WARNING level, info invisible)
- **Message segment parsing**: `构建完整文本()` split into `_格式化媒体标签()`, `_格式化文件标签()`, `_追加详细艾特文本()`
- **show_qq_id**: Removed; display name fixed as `nickname(QQnumber)` format
- **Config aliases**: `reverse_token` as alias for `access_token`; `NAPCAT_ALLOWED_USERS` as fallback env var for whitelist

</details>
