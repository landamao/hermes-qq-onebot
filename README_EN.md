<div align="center">

# Hermes-QQ-OneBot

**Hermes Agent × QQ — Bring a fully capable AI agent into QQ**

[![Hermes Plugin](https://img.shields.io/badge/Hermes-Platform%20Plugin-7c3aed?logo=data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSIyNCIgaGVpZ2h0PSIyNCIgdmlld0JveD0iMCAwIDI0IDI0IiBmaWxsPSJub25lIiBzdHJva2U9IndoaXRlIiBzdHJva2Utd2lkdGg9IjIiPjxwYXRoIGQ9Ik0xMiAyTDIuNSA3djEwTDEyIDIybDkuNS0yVjciLz48L3N2Zz4=)](https://hermes-agent.nousresearch.com/docs)
[![OneBot v11](https://img.shields.io/badge/OneBot-v11-1677ff?logo=data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSIyNCIgaGVpZ2h0PSIyNCIgdmlld0JveD0iMCAwIDI0IDI0IiBmaWxsPSJub25lIiBzdHJva2U9IndoaXRlIiBzdHJva2Utd2lkdGg9IjIiPjxjaXJjbGUgY3g9IjEyIiBjeT0iMTIiIHI9IjEwIi8+PC9zdmc+)](https://github.com/botuniverse/onebot)
[![Version](https://img.shields.io/badge/version-2.1.4-green)](./plugin.yaml)
[![License](https://img.shields.io/badge/license-MIT-blue)](./LICENSE)

*A QQ platform adapter for [Hermes Agent](https://github.com/NousResearch/hermes-agent), built on the OneBot v11 protocol*

[中文文档](./README.md)

</div>

---

## Highlights

<table>
<tr>
<td width="50%">

### Plug and Play
Install and enable with one command. Reverse WebSocket means NapCat connects to you — zero extra configuration.

</td>
<td width="50%">

### Pure Plugin Design
No Hermes source-code changes needed. Install to enable, remove to cleanly uninstall — zero intrusion.

</td>
</tr>
<tr>
<td width="50%">

### Native CQ Code Support
Agents send rich QQ messages by writing `[CQ:image,file=...]` directly in replies — no extra API needed.

</td>
<td width="50%">

### On-Demand Media Downloads
Media is only downloaded for messages that wake the agent. Oversized files keep their URL for the agent to fetch as needed.

</td>
</tr>
<tr>
<td width="50%">

### Long-Message Merged Forwarding
Long group replies are automatically sent as QQ merged-forward messages, with CQ codes split into separate nodes.

</td>
<td width="50%">

### Keyword Triggers
Regex-based group message matching wakes the agent — no @ mention required.

</td>
</tr>
</table>

---

## Architecture

```
QQ client
     ↕
NapCat / Lagrange / go-cqhttp / LLOneBot  (OneBot v11 implementation)
     ↓ reverse WebSocket (initiated by OneBot side)
hermes-qq-onebot
     ↓
Hermes Agent (full AI capabilities: terminal / browser / files / search / …)
```

> **Reverse WebSocket** — the adapter runs as a server; the OneBot implementation connects to it. No public IP or exposed port needed.

---

## Installation & Usage

### 1. Install the Plugin

```bash
hermes plugins install landamao/hermes-qq-onebot --enable
```

<details>
<summary>Manual installation</summary>

```bash
git clone https://github.com/landamao/hermes-qq-onebot.git ~/.hermes/plugins/napcat
pip install websockets
hermes gateway restart
```
</details>

### 2. Configure Hermes

Add the following to `~/.hermes/config.yaml`:

```yaml
platforms:
  napcat:
    enabled: true
    extra:
      reverse_host: "127.0.0.1"            # Listen address
      reverse_port: 6700                    # Listen port
      access_token: ""                      # Access token (optional)
      http_api_url: "http://127.0.0.1:5700" # HTTP API (recommended)
```

<details>
<summary>More optional settings</summary>

```yaml
      # -- Media download limits --
      download_limits:
        image: 10MB                         # Supports B / KB / MB / GB
        record: 10MB
        video: 10MB
        file: 10MB

      # -- Long messages --
      merge_forward_threshold: 800          # Character count to trigger merged forwarding
      forward_name: "Hermes"                # Display name in merged-forward messages

      # -- Reply quoting --
      reply_text_max_length: 50             # Max characters of quoted text

      # -- Keyword triggers --
      mention_patterns:                     # Regex, case-insensitive
        - "hermes"
        - "help me"

      # -- User allowlist --
      allowed_qq_ids: "123456,789012"       # Comma-separated; empty = allow all

      # -- Misc --
      show_qq_id: false                     # Show QQ number after username
      emoji_react: false                    # React with random emoji
      bot_self_id: ""                        # Bot QQ number (auto-learned)
```
</details>

### 3. Configure NapCat

Set up reverse WebSocket in your NapCat configuration:

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

> If you set `access_token` in Hermes, make sure the same token is configured on the NapCat side.

### 4. Start

```bash
hermes gateway restart
```

After a successful start, logs should show `反向WS模式启动，等待 NapCat 连接端口 6700`. Once NapCat connects, you can chat with the agent in QQ.

<details>
<summary>Environment variable overrides</summary>

All configuration items can be overridden via environment variables (lower priority than `config.yaml`):

```bash
NAPCAT_ACCESS_TOKEN=***                  # Access token
NAPCAT_HTTP_API_URL=http://127.0.0.1:5700  # HTTP API address
NAPCAT_BOT_SELF_ID=123456789             # Bot QQ number
NAPCAT_ALLOWED_USERS=123456,789012       # User allowlist
NAPCAT_ALLOW_ALL_USERS=false             # Allow all users
NAPCAT_MENTION_PATTERNS=hermes,help me   # Keyword triggers
```
</details>

---

## Compatible OneBot Implementations

| Implementation | Status | Notes |
|:--|:--:|:--|
| [NapCat](https://github.com/NapNeko/NapCatQQ) | ✅ Recommended | Best supported and feature-complete. |
| [Lagrange.OneBot](https://github.com/LagrangeDev/Lagrange.Core) | ✅ Compatible | Works normally. |
| [go-cqhttp](https://github.com/Mrs4s/go-cqhttp) | ⚠️ Legacy | Usable but no longer maintained. |
| [LLOneBot](https://github.com/LLOneBot/LLOneBot) | ✅ Compatible | Works normally. |

> Any implementation that follows the OneBot v11 standard should work.

---

## Features

### Message Handling

| Feature | Description |
|:--|:--|
| Private & group chats | Both DM and group message support. |
| @ mention detection | Automatically responds when the bot is @'d. |
| Keyword triggers | Regex-based triggers wake the agent without @ mention. |
| Reply quoting | Reads quoted messages and truncates them safely. |
| Long-message merged forwarding | Group replies over the threshold are sent as merged-forward messages; CQ codes are split into separate nodes. |
| Emoji reaction & poke | Optional reaction behavior, disabled by default. |

### Media Support

| Type | Receive | Send | Agent-visible tag |
|:--|:--:|:--:|:--|
| Image | ✅ | ✅ | `[Image:file=/tmp/a.jpg]` or `[Image:url=https://...]` |
| Voice | ✅ | ✅ | `[Voice:file=/tmp/a.ogg]` or `[Voice:url=https://...]` |
| Video | ✅ | ✅ | `[Video:url=https://...]` or `[Video:file=/tmp/a.mp4]` |
| File | ✅ | ✅ | `[File:name=report.pdf,file=/tmp/a]` |
| Face emoji | ✅ | ✅ | `[Face:id=123]` |
| @ mention | ✅ | ✅ | `@Name(QQ:123456)` → `[CQ:at,qq=123]` |

> The agent sees structured tags with local paths or URLs — tools can inspect downloaded media directly when needed.

### Sending CQ Codes

Agents write CQ codes directly in their response text; the adapter parses and sends them automatically:

```
Check this out [CQ:image,file=/tmp/test.jpg]
Here is the file [CQ:file,file=/tmp/document.pdf,name=document.pdf]
```

**Supported CQ codes:** `[CQ:at]` · `[CQ:image]` · `[CQ:record]` · `[CQ:video]` · `[CQ:file]` · `[CQ:face]` · and other OneBot v11 standard message segments.

---

## Uninstallation

```bash
rm -rf ~/.hermes/plugins/napcat
hermes gateway restart
```

---

## As a Hermes Plugin

This project is a Hermes Agent platform adapter plugin. Once registered, Hermes Gateway loads it automatically:

- **Plugin name:** `napcat`
- **Kind:** `platform`
- **Registered platform:** `napcat` (NapCat QQ)
- **Runtime dependency:** `websockets`
- **Entry point:** `adapter.py`

---

## Security Notes

- Keep `access_token` private. Do not commit it to version control.
- Do not publish real tokens, cookies, or API keys in issues, logs, or screenshots.
- If you expose the reverse WebSocket port beyond localhost, use an `access_token` and firewall rules.
- Prefer binding to `127.0.0.1` when NapCat and Hermes run on the same machine.
- Review media download limits before allowing untrusted groups to trigger the agent.

---

## Changelog

### v2.1.4 (2025-07-08)

- Fix `ws.request_headers` compatibility: adapt to websockets 15.x API change (`ws.request.headers`)
- Fix `connect()` missing `is_reconnect` parameter causing TypeError with newer gateway versions

---

## License

MIT License © [懒大猫](https://github.com/landamao)
