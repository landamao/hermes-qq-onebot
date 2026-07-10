<div align="center">

# Hermes-QQ-OneBot

**Hermes Agent × QQ — 让 AI 在 QQ 里活起来**

[![Hermes Plugin](https://img.shields.io/badge/Hermes-Platform%20Plugin-7c3aed?logo=data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSIyNCIgaGVpZ2h0PSIyNCIgdmlld0JveD0iMCAwIDI0IDI0IiBmaWxsPSJub25lIiBzdHJva2U9IndoaXRlIiBzdHJva2Utd2lkdGg9IjIiPjxwYXRoIGQ9Ik0xMiAyTDIuNSA3djEwTDEyIDIybDkuNS0yVjciLz48L3N2Zz4=)](https://hermes-agent.nousresearch.com/docs)
[![OneBot v11](https://img.shields.io/badge/OneBot-v11-1677ff?logo=data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSIyNCIgaGVpZ2h0PSIyNCIgdmlld0JveD0iMCAwIDI0IDI0IiBmaWxsPSJub25lIiBzdHJva2U9IndoaXRlIiBzdHJva2Utd2lkdGg9IjIiPjxjaXJjbGUgY3g9IjEyIiBjeT0iMTIiIHI9IjEwIi8+PC9zdmc+)](https://github.com/botuniverse/onebot)
[![Version](https://img.shields.io/badge/version-2.1.4-green)](./plugin.yaml)
[![License](https://img.shields.io/badge/license-MIT-blue)](./LICENSE)

*基于 OneBot v11 协议的 QQ 平台适配器，为 [Hermes Agent](https://github.com/NousResearch/hermes-agent) 接入 QQ 生态*

[English](./README_EN.md)

</div>

---

## ✨ 亮点

<table>
<tr>
<td width="50%">

### 🔌 即装即用
一行命令安装启用，反向 WebSocket 零配置连接，NapCat 主动连过来

</td>
<td width="50%">

### 🧩 纯插件设计
不动 Hermes 一行源码，安装即生效，卸载即干净，零侵入

</td>
</tr>
<tr>
<td width="50%">

### 📦 CQ 码原生支持
Agent 直接在文本里写 `[CQ:image,file=...]` 发送复杂消息，无需额外 API

</td>
<td width="50%">

### 🛡️ 按需下载媒体
只在被唤醒时下载媒体，闲聊消息不碰磁盘，超限只保留 URL 由 Agent 按需取用

</td>
</tr>
<tr>
<td width="50%">

### ✂️ 长消息合并转发
群聊超长回复自动合并转发，CQ 码智能拆分为独立消息节点

</td>
<td width="50%">

### 🔑 关键词触发
正则匹配群聊消息自动响应，不用 @ 也能唤醒 Agent

</td>
</tr>
</table>

---

## 🏗️ 架构

```
📱 QQ 客户端
      ↕
🌊 NapCat / Lagrange / go-cqhttp / LLOneBot  (OneBot v11 实现)
      ↓ 反向 WebSocket (主动连接适配器)
🔌 hermes-qq-onebot
      ↓
🤖 Hermes Agent (完整 AI 能力: 终端/浏览器/文件/搜索/...)
```

> **反向 WebSocket** — 适配器起 Server，OneBot 实现主动连过来，无需公网 IP，无需开放端口。

---

## 🚀 安装 & 使用

### 1️⃣ 安装插件

```bash
hermes plugins install landamao/hermes-qq-onebot --enable
```

<details>
<summary>🔧 手动安装</summary>

```bash
git clone https://github.com/landamao/hermes-qq-onebot.git ~/.hermes/plugins/napcat
pip install websockets
hermes gateway restart
```
</details>

### 2️⃣ 配置 Hermes

在 `~/.hermes/config.yaml` 中添加：

```yaml
platforms:
  napcat:
    enabled: true
    extra:
      reverse_host: "127.0.0.1"            # 监听地址
      reverse_port: 6700                    # 监听端口
      access_token: ""                      # 访问令牌（可选）
      http_api_url: "http://127.0.0.1:5700" # HTTP API（推荐开启）
```

<details>
<summary>⚙️ 更多可选配置</summary>

```yaml
      # ── 媒体下载限制 ──
      download_limits:
        image: 10MB                         # 支持 B/KB/MB/GB
        record: 10MB
        video: 10MB
        file: 10MB

      # ── 长消息 ──
      merge_forward_threshold: 800          # 群聊超过此字数触发合并转发
      forward_name: "纳西妲"                 # 合并转发显示名

      # ── 引用回复 ──
      reply_text_max_length: 50             # 引用原文最大字数

      # ── 关键词触发 ──
      mention_patterns:                     # 正则，不区分大小写
        - "纳猫"
        - "帮我"

      # ── 用户白名单 ──
      allowed_qq_ids: "123456,789012"       # 逗号分隔，留空=允许所有

      # ── 其他 ──
      show_qq_id: false                     # 用户名后显示 QQ 号
      emoji_react: false                    # 随机回应表情
      bot_self_id: ""                        # 机器人 QQ 号（自动学习）
```

</details>

### 3️⃣ 配置 NapCat

在 NapCat 配置文件中设置反向 WS：

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

> 如果 Hermes 端配了 `access_token`，NapCat 端也需要设置相同的 token。

### 4️⃣ 启动

```bash
hermes gateway restart
```

连接成功后日志会显示 `反向WS模式启动，等待 NapCat 连接端口 6700`，NapCat 连入后即可在 QQ 中与 Agent 对话。

<details>
<summary>🌍 环境变量覆盖</summary>

所有配置项都可通过环境变量覆盖（优先级低于 config.yaml）：

```bash
NAPCAT_ACCESS_TOKEN=***                  # 访问令牌
NAPCAT_HTTP_API_URL=http://127.0.0.1:5700  # HTTP API 地址
NAPCAT_BOT_SELF_ID=123456789             # 机器人 QQ 号
NAPCAT_ALLOWED_USERS=123456,789012       # 用户白名单
NAPCAT_ALLOW_ALL_USERS=false             # 允许所有用户
NAPCAT_MENTION_PATTERNS=纳猫,帮我        # 关键词触发
```
</details>

---

## 📋 兼容的 OneBot 实现

| 实现 | 状态 | 说明 |
|:-----|:----:|:-----|
| [NapCat](https://github.com/NapNeko/NapCatQQ) | ✅ 首选 | 推荐使用，功能最全面 |
| [Lagrange.OneBot](https://github.com/LagrangeDev/Lagrange.Core) | ✅ 兼容 | 正常工作 |
| [go-cqhttp](https://github.com/Mrs4s/go-cqhttp) | ⚠️ 旧版 | 可用但已停止维护 |
| [LLOneBot](https://github.com/LLOneBot/LLOneBot) | ✅ 兼容 | 正常工作 |

> 只要符合 OneBot v11 标准的实现都能用～

---

## 🎯 功能一览

### 💬 消息能力

| 功能 | 说明 |
|:-----|:-----|
| 私聊 / 群聊 | 双模式消息收发 |
| @ 提及检测 | 被 @ 自动响应 |
| 关键词触发 | 正则匹配，不 @ 也能唤醒 |
| 引用回复 | 解析被引用的原文并截断 |
| 长消息合并转发 | 群聊超阈值自动合并，CQ 码拆分为独立节点 |
| 表情回应 / 戳一戳 | 默认关闭，按需开启 |

### 📎 媒体支持

| 类型 | 接收 | 发送 | 消息标签 |
|:-----|:----:|:----:|:---------|
| 🖼️ 图片 | ✅ | ✅ | `[图片:file=/tmp/xxx.jpg]` 或 `[图片:url=https://...]` |
| 🎤 语音 | ✅ | ✅ | `[语音:file=/tmp/xxx.ogg]` 或 `[语音:url=https://...]` |
| 🎬 视频 | ✅ | ✅ | `[视频:url=https://...]` 或 `[视频:file=/tmp/xxx.mp4]` |
| 📄 文件 | ✅ | ✅ | `[文件:name=report.pdf,file=/tmp/xxx]` |
| 😊 表情 | ✅ | ✅ | `[表情:id=123]` |
| 📢 @ 提及 | ✅ | ✅ | `@昵称(QQ:123456)` → `[CQ:at,qq=123]` |

> Agent 看到的是带路径/URL 的结构化标签，不需要额外处理就能拿到文件。

### 📤 CQ 码发送

Agent 直接在回复文本里写 CQ 码，适配器自动解析发送：

```
看看这个 [CQ:image,file=/tmp/test.jpg]
这是你要的文件 [CQ:file,file=/tmp/document.pdf,name=文档.pdf]
```

**支持的 CQ 码：** `[CQ:at]` · `[CQ:image]` · `[CQ:record]` · `[CQ:video]` · `[CQ:file]` · `[CQ:face]` · 以及更多 OneBot v11 标准 CQ 码

---

## 🗑️ 卸载

```bash
rm -rf ~/.hermes/plugins/napcat
hermes gateway restart
```

---

## 🧩 作为 Hermes 插件

本项目是一个 Hermes Agent 平台适配器插件，注册到 Hermes 插件系统后自动生效：

- **插件名：** `napcat`
- **类型：** `platform`
- **注册平台：** `napcat` (NapCat QQ)
- **依赖：** `websockets`

插件入口自动注册平台适配器到 Hermes 网关，无需手动干预。

---

## 📝 更新日志

### v2.1.4 (2025-07-08)

- 修复 `ws.request_headers` 兼容性问题：适配 websockets 15.x API 变更 (`ws.request.headers`)
- 修复 `connect()` 缺少 `is_reconnect` 参数导致新版 gateway 启动 TypeError

---

## 📄 许可证

MIT License © [懒大猫](https://github.com/landamao)
