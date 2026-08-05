# NapCat QQ 适配器

> **语言 / Language：** [中文](README.md) | [English](README_EN.md)

基于 OneBot v11 协议的 QQ 平台适配器，为 Hermes Agent 添加 QQ 支持。

支持 NapCat / go-cqhttp / Lagrange.OneBot / LLOneBot 等兼容实现。

## 架构

```
QQ 客户端 ←→ NapCat (OneBot 实现)
                  ↓ 反向 WebSocket (NapCat 主动连过来)
             NapCat 适配器 (hermes-qq-onebot)
                  ↓ 可选 HTTP API (图片发送、文件获取)
             OneBot API
```

- **反向 WebSocket**：适配器起 server，NapCat 主动连接
- **HTTP API**：可选但推荐，解决图片发送超时、文件获取等问题

## 模块结构

```
napcat/
├── plugin.yaml        # 插件元数据
├── adapter.py         # 注册入口（register 函数）
├── main.py            # 适配器主体（NapCat适配器 类）
├── ws.py              # 反向 WS 服务端（WS 类）
├── napcat_http.py     # HTTP API 调用器（NapcatHttp 类）
└── tools.py           # 常量、LRU缓存、媒体下载、消息段构建/解析
```

## 安装

```bash
hermes plugins install landamao/hermes-qq-onebot --enable
```

## 消息标签格式

每种媒体都带详细信息，Agent 可直接获取路径或 URL：

| 类型 | 标签格式 |
|------|----------|
| 图片 | `[图片:file=/tmp/xxx.jpg]` 或 `[图片:url=https://...]` |
| 语音 | `[语音:file=/tmp/xxx.ogg]` 或 `[语音:url=https://...]` |
| 视频 | `[视频:url=https://...]` 或 `[视频:file=/tmp/xxx.mp4]` |
| 文件 | `[文件:name=report.pdf,file=/tmp/xxx]` 或 `[文件:name=report.pdf,url=https://...]` |
| 表情 | `[表情:id=123]` |
| @提及 | `@昵称(QQ:123456)` |

## CQ 码支持

Agent 可通过 CQ 码直接发送复杂消息，直接写在消息文本中即可：

```
看看这个 [CQ:image,file=/tmp/test.jpg]
```

```
这是你要的文件 [CQ:file,file=/tmp/document.pdf,name=文档.pdf]
```

**支持的 CQ 码类型：**
- `[CQ:at,qq=123]` — @某人
- `[CQ:image,file=路径或URL]` — 发送图片
- `[CQ:record,file=路径或URL]` — 发送语音
- `[CQ:video,file=路径或URL]` — 发送视频
- `[CQ:file,file=路径或URL,name=文件名]` — 发送文件
- `[CQ:face,id=123]` — 发送表情
- 更多 CQ 码参考 OneBot v11 文档

## 下载限制

超过配置体积的媒体不自动下载，只保留 URL，Agent 需要时再下载：

```yaml
extra:
  download_limits:
    image: 10MB       # 支持 B/KB/MB/GB，不区分大小写
    record: 50MB
    video: 100MB
    file: 50MB
```

## 功能

- 私聊 / 群聊消息收发
- @提及检测 + 关键词触发
- 图片、语音、文件收发
- 回复消息解析（带智能截断，保留完整媒体标签）
- 长消息自动拆分 + 合并转发 (群聊，CQ码自动提取为独立普通消息发送)
- 用户白名单（默认拒绝，需显式配置）
- emoji 表情回应 / 戳一戳 (默认关闭)

## 配置

`~/.hermes/config.yaml`：

```yaml
platforms:
  napcat:
    enabled: true
    extra:
      # ── 反向 WS 配置 ──
      reverse_host: "127.0.0.1"          # 监听地址（默认 127.0.0.1，仅本地）
      reverse_port: 6700                  # 监听端口（默认 6700）
      access_token: ""                   # 访问令牌（可选，用于认证 NapCat 连接）
      # 也可用 reverse_token 作为别名

      # ── HTTP API（可选，推荐开启）──
      http_api_url: "http://127.0.0.1:5700"  # OneBot HTTP API 地址
      http_api_token: ""                      # HTTP 令牌（默认与 access_token 相同）

      # ── 机器人信息 ──
      bot_self_id: ""                     # 机器人 QQ 号（可选，会从消息中自动学习）

      # ── 媒体下载限制 ──
      # 有 file_size 时超限不下载，只保留 URL
      # 支持 B/KB/MB/GB（不区分大小写）
      download_limits:
        image: 10MB                       # 图片限制（默认 10MB）
        record: 10MB                      # 语音限制（默认 10MB）
        video: 10MB                       # 视频限制（默认 10MB）
        file: 10MB                        # 文件限制（默认 10MB）

      # ── 长消息处理 ──
      merge_forward_threshold: 800        # 群聊超过此字数触发合并转发（默认 800，私聊不触发）
      forward_name: "纳西妲"              # 合并转发显示的名字（默认 纳西妲）

      # ── 引用回复 ──
      reply_text_max_length: 50           # 解析引用回复消息的最大字数，超出截断用省略号（默认 50）
                                           # 截断时会保留完整的媒体标签（如 [图片:file=...]），不会在标签中间截断

      # ── 关键词触发 ──
      # 群聊中匹配这些正则时自动响应（不区分大小写）
      mention_patterns:
        - "纳猫"
        - "帮我"

      # ── 用户白名单 ──
      # 支持字符串（逗号分隔）、列表、或裸数字
      # 为空或不设置 → 拒绝所有用户
      # 设置为 "all" 或 "*" → 允许所有用户
      allowed_qq_ids: "123456,789012"

      # ── 表情回应 ──
      emoji_react: false                  # 收到消息后随机回应表情（默认 false）
```

## 环境变量

所有配置项都可以通过环境变量覆盖。环境变量名 = `NAPCAT_` + 配置键名大写。

**优先级**：环境变量 > config.yaml 中的 extra 配置 > 默认值

环境变量值的解析逻辑：
1. 先尝试 JSON 解析（数字、布尔、列表、字典等都能正确处理）
2. JSON 失败时识别常见布尔关键词：`off/false/no/n` → False，`on/true/yes/y` → True
3. 其他情况原样返回字符串

| 环境变量 | 对应配置键 | 说明 |
|----------|-----------|------|
| `NAPCAT_REVERSE_HOST` | reverse_host | 监听地址 |
| `NAPCAT_REVERSE_PORT` | reverse_port | 监听端口（整数） |
| `NAPCAT_ACCESS_TOKEN` | access_token | WS 访问令牌 |
| `NAPCAT_REVERSE_TOKEN` | reverse_token | WS 令牌别名（access_token 优先） |
| `NAPCAT_HTTP_API_URL` | http_api_url | HTTP API 地址 |
| `NAPCAT_HTTP_API_TOKEN` | http_api_token | HTTP 令牌（默认同 access_token） |
| `NAPCAT_EMOJI_REACT` | emoji_react | 表情回应开关（布尔） |
| `NAPCAT_BOT_SELF_ID` | bot_self_id | 机器人 QQ 号 |
| `NAPCAT_DOWNLOAD_LIMITS` | download_limits | 下载限制（JSON 字典） |
| `NAPCAT_MERGE_FORWARD_THRESHOLD` | merge_forward_threshold | 合并转发阈值（整数） |
| `NAPCAT_FORWARD_NAME` | forward_name | 合并转发昵称 |
| `NAPCAT_REPLY_TEXT_MAX_LENGTH` | reply_text_max_length | 引用文本最大字数（整数） |
| `NAPCAT_MENTION_PATTERNS` | mention_patterns | 关键词正则（JSON 数组或逗号分隔） |
| `NAPCAT_ALLOWED_QQ_IDS` | allowed_qq_ids | 用户白名单（字符串/列表/裸数字） |
| `NAPCAT_ALLOWED_USERS` | — | 白名单别名（仅在 config 未设 allowed_qq_ids 时生效） |
| `NAPCAT_ALLOW_ALL_USERS` | — | 允许所有用户（适配器注册层处理，设为 true 跳过白名单） |

示例：

```bash
# 基本配置
NAPCAT_REVERSE_HOST=127.0.0.1
NAPCAT_REVERSE_PORT=6700
NAPCAT_ACCESS_TOKEN=your_token
NAPCAT_HTTP_API_URL=http://127.0.0.1:5700
NAPCAT_BOT_SELF_ID=123456789

# 布尔值（以下写法等价）
NAPCAT_EMOJI_REACT=false
NAPCAT_EMOJI_REACT=off
NAPCAT_EMOJI_REACT=no

# 整数
NAPCAT_MERGE_FORWARD_THRESHOLD=1000

# JSON 字典（复杂值用 JSON）
NAPCAT_DOWNLOAD_LIMITS='{"image":"20MB","video":"100MB"}'

# JSON 数组或逗号分隔
NAPCAT_MENTION_PATTERNS='["纳猫","帮我"]'
NAPCAT_MENTION_PATTERNS=纳猫,帮我

# 白名单
NAPCAT_ALLOWED_QQ_IDS=123456,789012
NAPCAT_ALLOWED_QQ_IDS='[123, 456]'        # JSON 数组也行
NAPCAT_ALLOWED_QQ_IDS=123456              # 单个裸数字也行
```

## NapCat 端配置

在 NapCat 的配置文件中设置反向 WS 连接：

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

如果配置了 `access_token`，NapCat 端也需要设置相同的 token。

## 启动信息

Hermes 默认日志级别为 WARNING，`logger.info()` 的输出用户通常看不到，容易误以为插件没加载。因此关键信息在 `logger.info()` 之外同时用 `print()` 直接输出到终端。

启动时会输出配置摘要，便于排查问题：

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

WS 连接和断开时也会 print 到终端，不频繁的重要 info 日志（连接/断开/启动/异常）同时 print 以防 WARNING 级别看不到。

## 卸载

```bash
rm -rf ~/.hermes/plugins/napcat
hermes gateway restart
```

---

<details>
<summary><b>📖 与 v2.x 旧版的差异（点击展开）</b></summary>

v3.0.0 是对 v2.1.x 的重构升级，功能逻辑一致，以下为详细差异：

### 代码结构

| 项目 | v2.1.x (旧) | v3.0.0 (新) |
|------|-------------|-------------|
| 文件组织 | 单体文件 `napcat_adapter.py` (1530行) | 模块化拆分为 5 个文件 |
| WS 服务端 | 内嵌在主文件 | 独立 `ws.py`（WS 类） |
| HTTP 调用器 | 内嵌在适配器中 | 独立 `napcat_http.py`（NapcatHttp 类） |
| 工具函数 | 内嵌在主文件 | 独立 `tools.py`，有 `__all__` 导出列表 |
| API 边界 | 无，所有代码互相依赖 | 清晰的模块边界 |

### 配置类型校验

- **旧**：`extra_config.get()` + `os.getenv()` 简单回退，无类型检查，错误输入静默通过
- **新**：`获取配置()` 辅助函数，每个字段做 `isinstance` 类型校验，不合法时抛 `ValueError` 并给出详细错误信息（包含字段名、期望类型、实际类型和值）

### 环境变量读取

- **旧**：配置项直接从 `os.getenv()` 取值，只处理字符串，环境变量和配置文件两套独立逻辑
- **新**：统一走 `获取配置()` 函数，环境变量名 = `NAPCAT_` + 配置键大写，解析顺序：
  1. JSON 解析（数字 `123`、布尔 `true`、列表 `[1,2]`、字典 `{"k":"v"}` 都能正确处理）
  2. 布尔关键词识别（`off/false/no/n` → `False`，`on/true/yes/y` → `True`）
  3. 原样返回字符串

### 安全性

| 项目 | v2.1.x | v3.0.0 |
|------|--------|--------|
| 默认监听地址 | `0.0.0.0`（所有接口） | `127.0.0.1`（仅本地） |
| 白名单为空 | 隐式允许所有用户 | 拒绝所有用户，启动时打印警告 |
| 允许所有用户 | 无显式机制 | 需设置 `"all"` 或 `"*"` 才放行 |

### 私聊会话ID格式

- **旧**：`napcat_{用户ID}`
- **新**：`napcat_private_{用户ID}`（更明确，不易与群聊混淆）

### 全局状态

- **旧**：有 `_全局接口调用器` 全局变量 + `获取全局接口调用器()` 函数，外部工具可访问
- **新**：移除全局引用，WS 实例由适配器持有，无外部全局访问

### WS API 超时

- **旧**：60 秒默认
- **新**：120 秒默认（适配大文件获取等慢操作）

### WS 事件过滤

- **旧**：忽略 `post_type == "meta"`
- **新**：忽略 `post_type == "meta_event"`（OneBot v11 标准字段名）

### 白名单解析

- **旧**：仅支持字符串（逗号分隔）和列表
- **新**：额外支持 `int`/`float`（YAML 裸数字如 `allowed_qq_ids: 204676209` 自动转为字符串）

### HTTP API 令牌

- **旧**：HTTP API 和 WS 共用 `access_token`，无独立令牌配置
- **新**：新增 `http_api_token` 配置项，默认回退到 `access_token`，可独立设置

### 启动信息输出

- **旧**：仅 `logger.info()` 输出，Hermes 默认 WARNING 级日志，info 用户看不到
- **新**：Hermes 默认日志级别为 WARNING，`logger.info()` 用户看不到，容易误以为插件没加载。因此不频繁的重要 info 日志（连接/断开/启动/异常）同时 `print()` 到终端；频繁的日志（收发消息）不加 print

### 消息段解析重构

- **旧**：`构建完整文本()` 内联所有分支逻辑
- **新**：拆分为 `_格式化媒体标签()`、`_格式化文件标签()`、`_追加详细艾特文本()` 三个辅助函数

### show_qq_id 配置

- **旧**：有 `show_qq_id` 配置项，控制显示名称是否带 QQ 号
- **新**：移除该选项，显示名称固定为 `昵称(QQ号)` 格式

### 配置项别名

- **新**：`reverse_token` 作为 `access_token` 的别名（优先级低于 `access_token`）
- **新**：`NAPCAT_ALLOWED_USERS` 作为 `NAPCAT_ALLOWED_QQ_IDS` 的备用环境变量（仅在 config 未设 `allowed_qq_ids` 时生效）

</details>
