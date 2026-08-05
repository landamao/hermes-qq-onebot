<div align="center">

# Hermes-QQ-OneBot

**Hermes Agent × QQ — Bringing AI to Life on QQ**

[![Hermes Plugin](https://img.shields.io/badge/Hermes-Platform%20Plugin-7c3aed?logo=data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSIyNCIgaGVpZ2h0PSIyNCIgdmlld0JveD0iMCAwIDI0IDI0IiBmaWxsPSJub25lIiBzdHJva2U9IndoaXRlIiBzdHJva2Utd2lkdGg9IjIiPjxwYXRoIGQ9Ik0xMiAyTDIuNSA3djEwTDEyIDIybDkuNS0yVjciLz48L3N2Zz4=)](https://hermes-agent.nousresearch.com/docs)
[![OneBot v11](https://img.shields.io/badge/OneBot-v11-1677ff?logo=data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSIyNCIgaGVpZ2h0PSIyNCIgdmlld0JveD0iMCAwIDI0IDI0IiBmaWxsPSJub25lIiBzdHJva2U9IndoaXRlIiBzdHJva2Utd2lkdGg9IjIiPjxjaXJjbGUgY3g9IjEyIiBjeT0iMTIiIHI9IjEwIi8+PC9zdmc+)](https://github.com/botuniverse/onebot)
[![Version](https://img.shields.io/badge/version-3.0.0-green)](./plugin.yaml)
[![License](https://img.shields.io/badge/license-MIT-blue)](./LICENSE)

**Language / 语言：** [中文](README.md) | [English](README_EN.md)

*A QQ platform adapter based on the OneBot v11 protocol, bringing QQ connectivity to [Hermes Agent](https://github.com/NousResearch/hermes-agent)*

</div>

---

## ✨ Highlights

<table>
<tr>
<td width="50%">

### 🔌 Plug & Play
One command to install and enable. Reverse WebSocket needs zero config — NapCat connects to you

</td>
<td width="50%">

### 🧩 Pure Plugin Design
Doesn't touch a line of Hermes source. Install to activate, remove to clean up — zero intrusion

</td>
</tr>
<tr>
<td width="50%">

### 📦 Native CQ Code Support
Agent writes `[CQ:image,file=...]` directly in text to send complex messages — no extra API needed

</td>
<td width="50%">

### 🛡️ On-Demand Media Download
Media is only downloaded when the Agent is invoked. Idle messages never touch disk. Oversized items keep URL only for Agent to fetch as needed

</td>
</tr>
<tr>
<td width="50%">

### ✂️ Long Message Merged Forwarding
Group chat replies exceeding the threshold are auto-merged. CQ codes are smartly split into independent message nodes

</td>
<td width="50%">

### 🔑 Keyword Triggers
Regex matching auto-responds to group chat messages — no @mention needed to wake the Agent

</td>
</tr>
</table>

---

## 🏗️ Architecture

```
📱 QQ Client
      ↕
🌊 NapCat / Lagrange / go-cqhttp / LLOneBot  (OneBot v11 implementations)
      ↓ Reverse WebSocket (connects to adapter)
🔌 hermes-qq-onebot
      ↓
🤖 Hermes Agent (full AI capabilities: terminal/browser/files/search/...)
```

> **Reverse WebSocket** — The adapter runs a server; OneBot implementations connect to it. No public IP or open ports needed.
>
> **HTTP API** — Optional but recommended, resolves image send timeouts, file retrieval, etc.

---

## 🚀 Installation

```bash
hermes plugins install landamao/hermes-qq-onebot --enable
```

Done! Now just configure NapCat to connect.

<details>
<summary>🔧 Manual Installation</summary>

```bash
# Clone into Hermes plugins directory
git clone https://github.com/landamao/hermes-qq-onebot.git ~/.hermes/plugins/napcat

# Install dependencies
pip install websockets

# Restart gateway
hermes gateway restart
```
</details>

---

## 📋 Compatible OneBot Implementations

| Implementation | Status | Notes |
|:---------------|:------:|:------|
| [NapCat](https://github.com/NapNeko/NapCatQQ) | ✅ Recommended | Best feature support |
| [Lagrange.OneBot](https://github.com/LagrangeDev/Lagrange.Core) | ✅ Compatible | Works fine |
| [go-cqhttp](https://github.com/Mrs4s/go-cqhttp) | ⚠️ Legacy | Usable but no longer maintained |
| [LLOneBot](https://github.com/LLOneBot/LLOneBot) | ✅ Compatible | Works fine |

> Any implementation conforming to the OneBot v11 standard works!

---

## 📁 Module Structure

```
napcat/
├── plugin.yaml        # Plugin metadata
├── adapter.py         # Registration entry (register function)
├── main.py            # Adapter body (NapCat适配器 class)
├── ws.py              # Reverse WS server (WS class)
├── napcat_http.py     # HTTP API caller (NapcatHttp class)
└── tools.py           # Constants, LRU cache, media download, message segment build/parse
```

---

## 🎯 Feature Overview

### 💬 Messaging

| Feature | Description |
|:--------|:------------|
| Private / Group chat | Dual-mode message send & receive |
| @Mention detection | Auto-respond when mentioned |
| Keyword triggers | Regex matching — no @mention needed to wake Agent |
| Reply quoting | Parses quoted original text with smart truncation, preserves full media tags |
| Long message merged forwarding | Group chat auto-merges above threshold; CQ codes split into independent nodes |
| Emoji reactions / poke | Disabled by default, enable on demand |

### 📎 Media Support

| Type | Receive | Send | Message Tag |
|:-----|:-------:|:----:|:------------|
| 🖼️ Image | ✅ | ✅ | `[图片:file=/tmp/xxx.jpg]` or `[图片:url=https://...]` |
| 🎤 Voice | ✅ | ✅ | `[语音:file=/tmp/xxx.ogg]` or `[语音:url=https://...]` |
| 🎬 Video | ✅ | ✅ | `[视频:url=https://...]` or `[视频:file=/tmp/xxx.mp4]` |
| 📄 File | ✅ | ✅ | `[文件:name=report.pdf,file=/tmp/xxx]` |
| 😊 Emoji | ✅ | ✅ | `[表情:id=123]` |
| 📢 @Mention | ✅ | ✅ | `@Nickname(QQ:123456)` → `[CQ:at,qq=123]` |

> The Agent sees structured tags with paths/URLs — no extra processing needed to access files.

### 📤 CQ Code Sending

The Agent writes CQ codes directly in reply text; the adapter auto-parses and sends:

```
Check this out [CQ:image,file=/tmp/test.jpg]
Here's the file you wanted [CQ:file,file=/tmp/document.pdf,name=文档.pdf]
```

**Supported CQ codes:** `[CQ:at]` · `[CQ:image]` · `[CQ:record]` · `[CQ:video]` · `[CQ:file]` · `[CQ:face]` · and more OneBot v11 standard CQ codes

---

## ⚙️ Configuration

Add to `~/.hermes/config.yaml`:

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

<details>
<summary>🌍 Environment Variable Overrides</summary>

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
</details>

---

## 🔗 NapCat Side Configuration

Set up reverse WS connection in NapCat's config:

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

> If you configured `access_token`, NapCat must also set the same token.

---

## 📟 Startup Output

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

---

## 🗑️ Uninstall

```bash
rm -rf ~/.hermes/plugins/napcat
hermes gateway restart
```

---

## 🧩 As a Hermes Plugin

This project is a Hermes Agent platform adapter plugin. Once registered with the Hermes plugin system, it activates automatically:

- **Plugin name:** `napcat`
- **Kind:** `platform`
- **Registered platform:** `napcat` (NapCat QQ)
- **Dependencies:** `websockets`

The plugin entry auto-registers the platform adapter with the Hermes gateway — no manual intervention needed.

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

---

## 📄 License

MIT License © [懒大猫](https://github.com/landamao)
