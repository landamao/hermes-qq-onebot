"""
NapCat QQ 适配器 — 基于 OneBot v11 协议 (仅反向 WS 模式)

架构:
    QQ 客户端 ←→ NapCat (OneBot 实现)
                      ↓ 反向 WebSocket (NapCat 主动连过来)
                 NapCat 适配器 (本文件)

"""

import asyncio
import json
import logging
import mimetypes
import os
import random
import re
import time
import tempfile
import hmac
import urllib.request
import urllib.error
import urllib.parse
from collections import OrderedDict
from typing import Any, Dict, List, Optional, Set

import websockets
from websockets.asyncio.client import ClientConnection

from gateway.config import Platform, PlatformConfig
from gateway.platforms.base import (
    BasePlatformAdapter,
    MessageEvent,
    MessageType,
    SendResult,
    cache_image_from_bytes,
)
from gateway.platforms.helpers import MessageDeduplicator

日志 = logging.getLogger(__name__)

# ── 全局引用 (供外部工具调用) ──────────────────────────────────────────────
_全局接口调用器: Optional["_OneBot接口调用器"] = None
def 获取全局接口调用器() -> Optional["_OneBot接口调用器"]:
    """获取全局 OneBot 接口调用器实例。"""
    return _全局接口调用器
def 检查依赖() -> bool:
    """检查运行时依赖是否可用。"""
    try:
        import websockets
        return True
    except ImportError:
        return False


def _is_loopback_host(主机: str) -> bool:
    return 主机 in ("127.0.0.1", "localhost", "::1")


# ── 常量 ──────────────────────────────────────────────────────────────────
消息最大长度 = 4500
默认合并转发阈值 = 800
表情回应ID列表 = [66,76,124,144,147,192,201,282,297]
默认引用文本最大字数 = 50

# ── 自动下载限制 ─────────────────────────────────────────────────────
# 超过限制的媒体不下载，只保留 URL，Agent 需要时再下载
# 支持单位: B/KB/MB/GB (不区分大小写)
默认下载限制 = {
    "image": "10MB",
    "record": "10MB",
    "video": "10MB",
    "file": "10MB",
}
def 解析文件大小(值) -> int:
    """
    解析带单位的文件大小字符串为字节数。
    支持: 1024, "10MB", "1.5GB", "500kb" 等。
    """
    if isinstance(值, (int, float)):
        return int(值)
    原始 = str(值).strip()
    if not 原始:
        return 0
    # 纯数字
    try:
        return int(float(原始))
    except ValueError:
        pass
    # 带单位
    匹配 = re.match(r'^([0-9.]+)\s*([a-zA-Z]+)$', 原始)
    if not 匹配:
        return 0
    数字 = float(匹配.group(1))
    单位 = 匹配.group(2).upper()
    倍率 = {
        "B": 1,
        "K": 1024, "KB": 1024,
        "M": 1024**2, "MB": 1024**2,
        "G": 1024**3, "GB": 1024**3,
    }.get(单位, 0)
    return int(数字 * 倍率)

# ══════════════════════════════════════════════════════════════════════════
# LRU 缓存 (防内存泄漏)
# ══════════════════════════════════════════════════════════════════════════

class 简易LRU缓存:
    """轻量级 LRU 缓存，超过容量自动淘汰最久未用的条目。"""

    def __init__(self, 最大容量: int = 1000):
        self._缓存: OrderedDict[str, Any] = OrderedDict()
        self._最大容量 = 最大容量

    def 获取(self, 键: str, 默认值: Any = None) -> Any:
        if 键 in self._缓存:
            self._缓存.move_to_end(键)
            return self._缓存[键]
        return 默认值

    def 设置(self, 键: str, 值: Any) -> None:
        if 键 in self._缓存:
            self._缓存.move_to_end(键)
        self._缓存[键] = 值
        if len(self._缓存) > self._最大容量:
            self._缓存.popitem(last=False)

    def 弹出(self, 键: str, 默认值: Any = None) -> Any:
        return self._缓存.pop(键, 默认值)

    def __contains__(self, 键: str) -> bool:
        return 键 in self._缓存

    def __len__(self) -> int:
        return len(self._缓存)
# ══════════════════════════════════════════════════════════════════════════
# 消息段构建 (OneBot v11 格式，发送方向)
# ══════════════════════════════════════════════════════════════════════════

def 构建文本段(文本: str) -> dict:
    return {"type": "text", "data": {"text": 文本}}
def 构建图片段(地址: str) -> dict:
    """
    构建图片消息段。
    """
    if 地址.startswith(("http://", "https://")):
        return {"type": "image", "data": {"file": 地址}}
    地址 = 地址.lstrip("/")
    return {"type": "image", "data": {"file": f"file:///{地址}"}}
def 构建语音段(地址: str) -> dict:
    """构建语音消息段 (type = 'record')。"""
    if 地址.startswith(("http://", "https://")):
        return {"type": "record", "data": {"file": 地址}}
    地址 = 地址.lstrip("/")
    return {"type": "record", "data": {"file": f"file:///{地址}"}}
def 构建回复段(消息ID: str) -> dict:
    return {"type": "reply", "data": {"id": 消息ID}}
def 构建艾特段(QQ号: str) -> dict:
    return {"type": "at", "data": {"qq": QQ号}}
def 构建文件段(地址: str) -> dict:
    return {"type": "file", "data": {"file": 地址}}
def 构建消息数组(
    文本: str,
    回复目标: Optional[str] = None,
    附件列表: Optional[List[dict]] = None,
) -> List[dict]:
    """
    构建 OneBot v11 消息数组 (发送用)。
    根据文件扩展名自动选择图片/语音/文件消息段。
    """
    消息段: List[dict] = []
    if 回复目标:
        消息段.append(构建回复段(回复目标))
    if 文本.strip():
        消息段.append(构建文本段(文本))
    for 附件 in (附件列表 or []):
        路径 = 附件.get("path", "")
        if not 路径:
            continue
        扩展名 = 路径.rsplit(".", 1)[-1].lower() if "." in 路径 else ""
        if 扩展名 in ("png", "jpg", "jpeg", "gif", "webp"):
            消息段.append(构建图片段(路径))
        elif 扩展名 in ("ogg", "mp3", "wav", "amr", "silk"):
            消息段.append(构建语音段(路径))
        else:
            消息段.append(构建文件段(路径))
    return 消息段


def 文本转CQ码(文本: str, 附件列表: Optional[List[dict]] = None) -> str:
    """
    将文本和附件列表转换为 CQ 码字符串。
    OneBot v11 同时支持段数组和 CQ 码字符串两种格式，这里统一用字符串。
    """
    部分 = []
    if 文本.strip():
        部分.append(文本)
    for 附件 in (附件列表 or []):
        路径 = 附件.get("path", "")
        if not 路径:
            continue
        扩展名 = 路径.rsplit(".", 1)[-1].lower() if "." in 路径 else ""
        if 扩展名 in ("png", "jpg", "jpeg", "gif", "webp"):
            部分.append(f"[CQ:image,file=file:///{路径.lstrip('/')}]")
        elif 扩展名 in ("ogg", "mp3", "wav", "amr", "silk"):
            部分.append(f"[CQ:record,file=file:///{路径.lstrip('/')}]")
        else:
            部分.append(f"[CQ:file,file=file:///{路径.lstrip('/')}]")
    return "".join(部分)

# ── CQ 码拆分 (合并转发用) ──────────────────────────────────────────────────
CQ码正则 = re.compile(r'\[CQ:[^\]]+\]')

def 拆分CQ码(内容: str) -> List[tuple]:
    """将内容拆分为 (类型, 片段) 列表。类型为 'text' 或 'cq'。"""
    片段 = []
    位置 = 0
    for 匹配 in CQ码正则.finditer(内容):
        前文本 = 内容[位置:匹配.start()]
        if 前文本.strip():
            片段.append(("text", 前文本))
        片段.append(("cq", 匹配.group()))
        位置 = 匹配.end()
    尾文本 = 内容[位置:]
    if 尾文本.strip():
        片段.append(("text", 尾文本))
    return 片段

# ══════════════════════════════════════════════════════════════════════════
# 消息解析 (接收方向)
# ══════════════════════════════════════════════════════════════════════════

def 从消息段提取文本(消息段列表: List[dict]) -> str:
    """从 OneBot v11 消息段中提取纯文本部分。"""
    部分: List[str] = []
    for 段 in 消息段列表:
        段类型 = 段.get("type", "")
        数据 = 段.get("data", {})
        if 段类型 == "text":
            部分.append(数据.get("text", ""))
        elif 段类型 == "at":
            QQ号 = 数据.get("qq", "")
            昵称 = 数据.get("name", "")
            if QQ号 == "all":
                部分.append("@全体成员")
            elif 昵称:
                部分.append(f"@{昵称}")
            elif QQ号:
                部分.append(f"@{QQ号}")
        elif 段类型 == "face":
            部分.append("[表情]")
    return "".join(部分).strip()
def 构建完整文本(消息段列表: List[dict], 媒体映射: dict) -> str:
    """
    从消息段数组构建完整可读文本。
    每个媒体段都带详细标签:
      [图片:file=本地路径] 或 [图片:url=远程URL]
      [语音:file=本地路径] 或 [语音:url=远程URL]
      [视频:url=远程URL] 或 [视频:file=本地路径]
      [文件:name=xxx,file=本地路径] 或 [文件:name=xxx,url=远程URL]
      [表情:id=123]
    """
    部分: List[str] = []
    for i, 段 in enumerate(消息段列表):
        段类型 = 段.get("type", "")
        数据 = 段.get("data", {})
        信息 = 媒体映射.get(i, {})

        if 段类型 == "text":
            部分.append(数据.get("text", ""))

        elif 段类型 == "at":
            QQ号 = 数据.get("qq", "")
            昵称 = 数据.get("name", "")
            if QQ号 == "all":
                部分.append("@全体成员")
            elif 昵称:
                部分.append(f"@{昵称}(QQ:{QQ号})")
            elif QQ号:
                部分.append(f"@{QQ号}")

        elif 段类型 == "face":
            表情ID = 数据.get("id", "")
            部分.append(f"[表情:id={表情ID}]")

        elif 段类型 == "image":
            if 信息.get("本地路径"):
                部分.append(f"[图片:file={信息['本地路径']}]")
            else:
                部分.append(f"[图片:url={信息.get('原始URL', 数据.get('url', ''))}]")

        elif 段类型 == "record":
            if 信息.get("本地路径"):
                部分.append(f"[语音:file={信息['本地路径']}]")
            else:
                部分.append(f"[语音:url={信息.get('原始URL', 数据.get('url', ''))}]")

        elif 段类型 == "video":
            原始URL = 数据.get("url", "") or 数据.get("file", "")
            if 信息.get("本地路径"):
                部分.append(f"[视频:file={信息['本地路径']}]")
            else:
                部分.append(f"[视频:url={原始URL}]")

        elif 段类型 == "file":
            文件名 = 数据.get("file", "")
            原始URL = 数据.get("url", "") or 数据.get("file", "")
            if 信息.get("本地路径"):
                部分.append(f"[文件:name={文件名},file={信息['本地路径']}]")
            else:
                部分.append(f"[文件:name={文件名},url={原始URL}]")

        elif 段类型 == "reply":
            continue  # reply 段单独处理

        else:
            部分.append(f"[不支持的消息类型:{段类型}]")

    return "".join(部分).strip()

# ── 智能截断（保留完整媒体标签）──────────────────────────────────────

_媒体标签正则 = re.compile(r'\[(?:图片|语音|视频|文件|表情):[^\]]*\]')

def _智能截断保留媒体标签(文本: str, 最大字数: int) -> str:
    """
    按顺序截断到最大字数，如果截断点落在媒体标签内部则延伸到标签结尾。
    """
    if len(文本) <= 最大字数:
        return 文本

    # 找截断点之后最近的 ] 位置，看是否在标签内部
    截断处 = 文本[:最大字数]
    # 检查截断处是否有未闭合的 [
    最后左括号 = 截断处.rfind("[")
    if 最后左括号 != -1:
        # 看这个 [ 是否是媒体标签的开头
        候选 = 文本[最后左括号:]
        匹配 = _媒体标签正则.match(候选)
        if 匹配:
            # 截断点在媒体标签内部，延伸到标签结尾
            标签结束 = 最后左括号 + 匹配.end()
            return 文本[:标签结束] + "..."

    return 截断处 + "..."

def 提取被艾特的QQ号(消息段列表: List[dict], 机器人QQ号: str) -> Optional[str]:
    """检查消息中是否 @了指定 QQ 号。"""
    for 段 in 消息段列表:
        if 段.get("type") == "at":
            QQ号 = 段.get("data", {}).get("qq", "")
            if str(QQ号) == 机器人QQ号:
                return str(QQ号)
    return None
# OneBot 接口调用器 (通过 WebSocket 发送 API 调用)
# ══════════════════════════════════════════════════════════════════════════

class _OneBot接口调用器:
    """通过 WebSocket 连接调用 OneBot v11 API，支持请求-响应匹配。"""

    def __init__(self):
        self._ws: Optional[ClientConnection] = None
        self._待响应: Dict[str, asyncio.Future] = {}
        self._计数器: int = 0

    def 设置连接(self, ws: Optional[ClientConnection]):
        """设置或清除 WebSocket 连接。断开时快速失败所有挂起请求。"""
        self._ws = ws
        if ws is None:
            for 未来 in self._待响应.values():
                if not 未来.done():
                    未来.set_exception(ConnectionError("WebSocket 已断开"))
            self._待响应.clear()

    async def 调用(self, 动作: str, 参数: dict, 超时: float = 60.0) -> dict:
        """
        调用 OneBot API 并等待响应。
        通过 echo 字段匹配请求和响应。
        """
        if not self._ws:
            return {"status": "failed", "msg": "WebSocket 未连接"}

        self._计数器 += 1
        回显标识 = f"napcat_{self._计数器}_{int(time.time() * 1000)}"

        数据包 = json.dumps({
            "action": 动作,
            "params": 参数,
            "echo": 回显标识,
        })

        未来: asyncio.Future = asyncio.get_running_loop().create_future()
        self._待响应[回显标识] = 未来

        try:
            await self._ws.send(数据包)
            async with asyncio.timeout(超时):
                return await 未来
        except TimeoutError:
            return {"status": "failed", "msg": f"API 调用超时 ({动作})"}
        except websockets.exceptions.ConnectionClosed as e:
            return {"status": "failed", "msg": f"连接已关闭: {e}"}
        except ConnectionError as e:
            return {"status": "failed", "msg": str(e)}
        finally:
            self._待响应.pop(回显标识, None)

    def 处理响应(self, 数据: dict):
        """处理 WebSocket 返回的响应帧 (带 echo 字段的)。"""
        回显标识 = 数据.get("echo")
        if 回显标识 and 回显标识 in self._待响应:
            未来 = self._待响应.pop(回显标识)
            if not 未来.done():
                未来.set_result(数据)

    # ── 常用 API 封装 ──────────────────────────────────────────────────

    async def 发送私聊消息(self, 用户ID: str, 消息) -> dict:
        return await self.调用("send_private_msg", {"user_id": int(用户ID), "message": 消息})

    async def 发送群聊消息(self, 群ID: str, 消息) -> dict:
        return await self.调用("send_group_msg", {"group_id": int(群ID), "message": 消息})

    async def 获取群信息(self, 群ID: str) -> dict:
        return await self.调用("get_group_info", {"group_id": int(群ID)})

    async def 获取文件(self, 文件ID: str) -> dict:
        return await self.调用("get_file", {"file_id": 文件ID}, 超时=120.0)

    async def 获取消息(self, 消息ID: str) -> dict:
        return await self.调用("get_msg", {"message_id": int(消息ID)})

    async def 上传群文件(self, 群ID: str, 文件路径: str, 文件名: str = "") -> dict:
        return await self.调用("upload_group_file", {
            "group_id": int(群ID),
            "file": 文件路径,
            "name": 文件名 or os.path.basename(文件路径),
        })

    async def 上传私聊文件(self, 用户ID: str, 文件路径: str, 文件名: str = "") -> dict:
        return await self.调用("upload_private_file", {
            "user_id": int(用户ID),
            "file": 文件路径,
            "name": 文件名 or os.path.basename(文件路径),
        })

    async def 发送群合并转发(self, 群ID: str, 消息节点: list) -> dict:
        return await self.调用("send_group_forward_msg", {"group_id": int(群ID), "messages": 消息节点})

    async def 发送私聊合并转发(self, 用户ID: str, 消息节点: list) -> dict:
        return await self.调用("send_private_forward_msg", {"user_id": int(用户ID), "messages": 消息节点})

    async def 设置表情回应(self, 消息ID: str, 表情ID: int = 12) -> dict:
        return await self.调用("set_msg_emoji_like", {
            "message_id": int(消息ID), "emoji_id": 表情ID, "set": True,
        })

    async def 戳一戳好友(self, 用户ID: str) -> dict:
        return await self.调用("friend_poke", {"user_id": int(用户ID)})
# ══════════════════════════════════════════════════════════════════════════
# 反向 WebSocket 服务端 (NapCat 主动连过来)
# ══════════════════════════════════════════════════════════════════════════

class _反向WebSocket服务:
    """
    反向 WS 模式：本适配器起 server，NapCat 主动连过来。
    支持 access_token 认证。
    """

    def __init__(self, 接口调用器: _OneBot接口调用器, 事件处理器):
        self._接口调用器 = 接口调用器
        self._事件处理器 = 事件处理器
        self._服务端 = None
        self._当前连接: Optional[ClientConnection] = None
        self._令牌: str = ""

    async def 启动(self, 主机: str, 端口: int, 令牌: str = ""):
        self._令牌 = 令牌

        async def _处理连接(ws):
            # ── 认证 ──
            if self._令牌:
                提取的令牌 = ws.request.headers.get("Authorization", "").removeprefix("Bearer ")
                if not 提取的令牌:
                    try:
                        from urllib.parse import parse_qs, urlparse
                        查询参数 = parse_qs(urlparse(ws.request.path).query)
                        提取的令牌 = 查询参数.get("access_token", [""])[0]
                    except Exception as e:
                        日志.debug("反向WS: 解析查询参数令牌失败: %s", e)
                if not hmac.compare_digest(提取的令牌, self._令牌):
                    await ws.close(1008, "认证失败")
                    return

            日志.info("反向WS客户端已连接: %s", ws.remote_address)
            self._当前连接 = ws
            self._接口调用器.设置连接(ws)
            global _全局接口调用器
            _全局接口调用器 = self._接口调用器

            try:
                async for 消息 in ws:
                    try:
                        数据 = json.loads(消息)
                        if "echo" in 数据:
                            # 这是 API 响应帧
                            self._接口调用器.处理响应(数据)
                        elif 数据.get("post_type") == "meta":
                            pass  # 生命周期/心跳 — 忽略
                        else:
                            await self._事件处理器(数据)
                    except json.JSONDecodeError:
                        日志.debug("反向WS: 非JSON消息: %s", 消息[:200])
                    except Exception as e:
                        日志.error("反向WS事件处理错误: %s", e, exc_info=True)
            except websockets.ConnectionClosed as e:
                日志.warning("反向WS连接关闭: code=%s reason=%s", e.code, e.reason)
            except Exception as e:
                日志.error("反向WS处理错误: %s", e, exc_info=True)
            finally:
                日志.info("反向WS客户端已断开")
                # 只在当前连接确实是自己的时候才清空，防止旧连接断开覆盖新连接
                if self._当前连接 is ws:
                    self._当前连接 = None
                    self._接口调用器.设置连接(None)

        self._服务端 = await websockets.serve(
            _处理连接, 主机, 端口,
            ping_interval=20,
            ping_timeout=20,
        )
        日志.info("反向WS服务端启动: ws://%s:%s", 主机, 端口)

    async def 停止(self):
        if self._当前连接:
            try:
                await self._当前连接.close()
            except Exception:
                pass
        if self._服务端:
            self._服务端.close()
            await self._服务端.wait_closed()
# ══════════════════════════════════════════════════════════════════════════
# 主适配器
# ══════════════════════════════════════════════════════════════════════════

class NapCat适配器(BasePlatformAdapter):
    """NapCat QQ 适配器 — 仅反向 WS 模式。

    QQ 不支持消息编辑（edit_message），网关会自动降级为分段发送。
    SendResult 不返回 message_id — 对 QQ 无意义，避免被误用于流式编辑。
    """

    最大消息长度 = 消息最大长度

    def __init__(self, 配置: PlatformConfig):
        super().__init__(配置, Platform("napcat"))
        附加配置 = 配置.extra or {}

        # ── 反向 WS 配置 ──
        self._反向主机: str = 附加配置.get("reverse_host", "127.0.0.1")
        self._反向端口: int = int(附加配置.get("reverse_port", 6700))
        self._访问令牌: str = 附加配置.get("access_token", "") or os.getenv("NAPCAT_ACCESS_TOKEN", "")

        # ── HTTP API (可选，推荐开启) ──
        self._HTTP接口地址: str = 附加配置.get("http_api_url", "") or os.getenv("NAPCAT_HTTP_API_URL", "")

        # ── 表情回应 ──
        self._启用表情回应: bool = 附加配置.get("emoji_react", False)

        # ── 机器人信息 ──
        self._机器人QQ号: str = 附加配置.get("bot_self_id", "") or os.getenv("NAPCAT_BOT_SELF_ID", "")

        # ── 内部状态 ──
        self._接口调用器 = _OneBot接口调用器()
        self._反向服务: Optional[_反向WebSocket服务] = None
        self._去重器 = MessageDeduplicator(max_size=2000)
        self._投递信息 = 简易LRU缓存(最大容量=2000)
        self._后台任务: Set[asyncio.Task] = set()

        # ── 缓存 ──
        self._群名缓存 = 简易LRU缓存(最大容量=500)
        self._昵称缓存 = 简易LRU缓存(最大容量=5000)

        # ── 显示选项 ──
        self._显示QQ号: bool = 附加配置.get("show_qq_id", False)

        # ── 下载限制 ──
        用户限制 = 附加配置.get("download_limits", {})
        合并限制 = {**默认下载限制, **(用户限制 or {})}
        self._下载限制 = {k: 解析文件大小(v) for k, v in 合并限制.items()}

        # ── 合并转发阈值 ──
        self._合并转发阈值: int = int(附加配置.get("merge_forward_threshold", 默认合并转发阈值))
        self._合并转发昵称: str = 附加配置.get("forward_name", "纳西妲")

        # ── 引用回复文本最大字数 ──
        self._引用文本最大字数: int = int(附加配置.get("reply_text_max_length", 默认引用文本最大字数))

        # ── 关键词触发 ──
        self._关键词模式: List[re.Pattern] = self._编译关键词模式(附加配置)

        # ── 用户白名单 ──
        原始白名单 = 附加配置.get("allowed_qq_ids", "") or os.getenv("NAPCAT_ALLOWED_USERS", "")
        self._允许列表: frozenset[str] = frozenset(
            p.strip() for p in str(原始白名单).split(",") if p.strip()
        )

    # ── 配置编译 ──────────────────────────────────────────────────────

    def _编译关键词模式(self, 附加配置: dict) -> List[re.Pattern]:
        """编译群聊关键词触发的正则模式。"""
        模式列表 = 附加配置.get("mention_patterns")
        if 模式列表 is None:
            原始值 = os.getenv("NAPCAT_MENTION_PATTERNS", "").strip()
            if 原始值:
                模式列表 = [p.strip() for p in 原始值.split(",") if p.strip()]
            else:
                return []
        if isinstance(模式列表, str):
            模式列表 = [模式列表]
        if not isinstance(模式列表, list):
            日志.warning("mention_patterns 必须是列表或字符串; 收到 %s", type(模式列表).__name__)
            return []
        结果 = []
        for 模式 in 模式列表:
            if not isinstance(模式, str) or not 模式:
                continue
            try:
                结果.append(re.compile(模式, re.IGNORECASE))
            except re.error as e:
                日志.warning("无效的关键词模式 %r: %s", 模式, e)
        return 结果

    def _检查关键词匹配(self, 文本: str) -> bool:
        """检查文本是否匹配任何配置的关键词。"""
        if not self._关键词模式 or not 文本:
            return False
        return any(模式.search(文本) for 模式 in self._关键词模式)

    def _检查用户权限(self, 用户ID: str) -> bool:
        """检查用户是否在白名单中。空名单 = 允许所有。"""
        if not self._允许列表:
            return True
        return 用户ID in self._允许列表

    # ══════════════════════════════════════════════════════════════════
    # 连接生命周期
    # ══════════════════════════════════════════════════════════════════

    async def connect(self, *, is_reconnect: bool = False) -> bool:
        """启动反向 WS 服务端，等待 NapCat 连接。"""
        if not self._访问令牌 and not _is_loopback_host(self._反向主机):
            raise RuntimeError("反向 WebSocket 公开监听时必须配置 access_token")
        self._反向服务 = _反向WebSocket服务(self._接口调用器, self._处理WS事件)
        await self._反向服务.启动(self._反向主机, self._反向端口, self._访问令牌)
        self._mark_connected()
        日志.info("反向WS模式启动，等待 NapCat 连接端口 %s", self._反向端口)
        if self._HTTP接口地址:
            日志.info("HTTP接口已启用: %s", self._HTTP接口地址)
        return True

    async def disconnect(self):
        """停止服务端并清理资源。"""
        if self._反向服务:
            await self._反向服务.停止()
            self._反向服务 = None
        self._接口调用器.设置连接(None)

        for 任务 in list(self._后台任务):
            任务.cancel()
        if self._后台任务:
            await asyncio.gather(*self._后台任务, return_exceptions=True)
        self._后台任务.clear()

    # ── HTTP API 调用 (可选通道) ──────────────────────────────────────

    async def _HTTP调用(self, 动作: str, 参数: dict) -> dict:
        """通过 HTTP 调用 OneBot API，独立于 WS，不阻塞任何东西。"""
        if not self._HTTP接口地址:
            return {"status": "failed", "msg": "HTTP 接口未配置"}
        地址 = f"{self._HTTP接口地址}/{动作}"
        数据包 = json.dumps(参数).encode()
        请求头 = {"Content-Type": "application/json"}
        if self._访问令牌:
            请求头["Authorization"] = f"Bearer {self._访问令牌}"
        请求 = urllib.request.Request(地址, data=数据包, headers=请求头)
        try:
            def _同步调用():
                with urllib.request.urlopen(请求, timeout=30) as 响应:
                    return json.loads(响应.read().decode())
            return await asyncio.to_thread(_同步调用)
        except Exception as e:
            return {"status": "failed", "msg": str(e)}

    # ══════════════════════════════════════════════════════════════════
    # 事件处理 (接收链路)
    # ══════════════════════════════════════════════════════════════════

    async def _处理WS事件(self, 原始数据: dict):
        """WS 事件分发入口。"""
        事件类型 = 原始数据.get("post_type", "")
        机器人QQ = str(原始数据.get("self_id", ""))
        if 机器人QQ:
            self._机器人QQ号 = 机器人QQ

        if 事件类型 == "message":
            任务 = asyncio.create_task(self._处理消息事件(原始数据))
            self._后台任务.add(任务)
            任务.add_done_callback(self._后台任务.discard)

    async def _处理消息事件(self, 原始数据: dict):
        """
        处理消息事件 — 完整链路追踪。

        链路: 收到 → 去重 → 过滤 → @检测 → 解析文本 → 解析媒体 → 解析回复 → 分发
        """
        消息类型 = 原始数据.get("message_type", "")
        用户ID = str(原始数据.get("user_id", ""))
        消息ID = str(原始数据.get("message_id", ""))
        群ID = str(原始数据.get("group_id", "")) if 消息类型 == "group" else ""
        发送者 = 原始数据.get("sender", {})
        昵称 = 发送者.get("card", "") or 发送者.get("nickname", "") or 用户ID
        消息段列表 = 原始数据.get("message", [])
        if not isinstance(消息段列表, list):
            消息段列表 = []

        日志.info("▶ 收到%s: 用户=%s(%s) 群=%s 消息ID=%s",
                  "群聊" if 消息类型 == "group" else "私聊",
                  昵称, 用户ID, 群ID or "-", 消息ID)

        # ── 步骤1: 去重 ──
        去重键 = f"napcat:{消息ID}" if 消息ID else f"napcat:{用户ID}:{str(原始数据.get('raw_message', ''))[:100]}"
        if self._去重器.is_duplicate(去重键):
            日志.info("✗ 重复消息，跳过")
            return

        # ── 步骤2: 过滤自己 ──
        if 用户ID == self._机器人QQ号:
            日志.info("✗ 自己的消息，跳过")
            return

        # ── 步骤3: 用户权限 ──
        if not self._检查用户权限(用户ID):
            日志.info("✗ 用户 %s 不在白名单", 用户ID)
            return

        # ── 步骤4: 群聊触发检测 ──
        if 消息类型 == "group":
            是否被艾特 = 提取被艾特的QQ号(消息段列表, self._机器人QQ号)
            文本预览 = 从消息段提取文本(消息段列表)
            是否匹配关键词 = self._检查关键词匹配(文本预览)
            是否指令 = 文本预览.startswith("/")

            if 是否指令:
                # 指令消息: 如果带了 @，必须是 @自己才处理
                指令中有艾特 = any(段.get("type") == "at" for 段 in 消息段列表)
                if 指令中有艾特 and not 是否被艾特:
                    日志.info("✗ 指令@了别人，跳过")
                    return
                日志.info("✓ 指令消息通过")
            elif not 是否被艾特 and not 是否匹配关键词:
                日志.info("✗ 群聊未@且无关键词匹配")
                return
            else:
                日志.info("✓ 群聊触发: 被@=%s 关键词=%s",
                          bool(是否被艾特), 是否匹配关键词)

        # ── 步骤5: 缓存昵称 ──
        if 昵称:
            self._昵称缓存.设置(用户ID, 昵称)
        显示名称 = f"{昵称}({用户ID})" if self._显示QQ号 and 昵称 != 用户ID else 昵称

        # ── 步骤6: 构建会话信息 ──
        if 消息类型 == "group":
            会话ID = f"napcat_group_{群ID}"
            会话名称 = self._群名缓存.获取(群ID, f"QQ群{群ID}")
            if 群ID not in self._群名缓存:
                任务 = asyncio.create_task(self._获取群名称(群ID))
                self._后台任务.add(任务)
                任务.add_done_callback(self._后台任务.discard)
        else:
            会话ID = f"napcat_{用户ID}"
            会话名称 = 昵称 or f"QQ用户{用户ID}"

        来源 = self.build_source(
            chat_id=会话ID,
            chat_name=会话名称,
            user_id=用户ID,
            user_name=显示名称,
            chat_type="group" if 消息类型 == "group" else "dm",
            thread_id=群ID if 消息类型 == "group" else None,
        )

        # ── 步骤7: 解析主消息的媒体附件 (下载+记录URL) ──
        媒体映射 = await self._解析媒体附件(消息段列表)

        # ── 步骤8: 构建完整文本 (带详细标签) ──
        文本 = 构建完整文本(消息段列表, 媒体映射)
        日志.info("文本: %s", 文本[:120] if 文本 else "(空)")

        # ── 步骤9: 解析回复的消息 ──
        回复ID, 回复文本, 回复媒体映射 = await self._解析回复消息(消息段列表)

        # ── 步骤10: 收集已下载的媒体路径 ──
        媒体路径: List[str] = []
        媒体类型: List[str] = []
        for 信息 in 媒体映射.values():
            if 信息.get("本地路径"):
                媒体路径.append(信息["本地路径"])
                媒体类型.append(信息.get("MIME", "application/octet-stream"))
        if 回复ID:
            for 信息 in (回复媒体映射 or {}).values():
                if 信息.get("本地路径"):
                    媒体路径.append(信息["本地路径"])
                    媒体类型.append(信息.get("MIME", "application/octet-stream"))

        # ── 步骤11: 兜底文本 ──
        if not 文本.strip() and 媒体路径:
            if any(t.startswith("image/") for t in 媒体类型):
                文本 = "[图片]"
            elif any(t.startswith("audio/") for t in 媒体类型):
                文本 = "[语音]"
            else:
                文本 = "[文件]"

        if not 文本.strip():
            日志.info("✗ 无有效内容")
            return

        # ── 步骤12: 推断消息分类 ──
        消息分类 = MessageType.TEXT
        if 媒体类型:
            if any(t.startswith(("application/", "text/")) for t in 媒体类型):
                消息分类 = MessageType.DOCUMENT
            elif any(t.startswith("audio/") for t in 媒体类型):
                消息分类 = MessageType.AUDIO
            elif any(t.startswith("image/") for t in 媒体类型):
                消息分类 = MessageType.PHOTO

        # ── 步骤13: 记录投递信息 (供发送时回查) ──
        self._投递信息.设置(会话ID, {
            "消息类型": 消息类型,
            "目标ID": 群ID if 消息类型 == "group" else 用户ID,
            "回复目标": 消息ID,
            "群ID": 群ID,
            "用户ID": 用户ID,
        })

        # ── 步骤14: 构建事件 ──
        事件 = MessageEvent(
            message_type=消息分类,
            text=文本,
            source=来源,
            raw_message=原始数据,
            message_id=消息ID or None,
            media_urls=媒体路径,
            media_types=媒体类型,
            reply_to_message_id=回复ID,
            reply_to_text=f"[Reply:msg_id={回复ID}] {回复文本}" if 回复ID and 回复文本 else (f"[Reply:msg_id={回复ID}]" if 回复ID else None),
        )

        日志.info("✓ 消息就绪: 分类=%s 文本=%d字 媒体=%d个 → 分发到网关",
                  消息分类.value, len(文本), len(媒体路径))

        # ── 步骤15: 可选表情回应 ──
        if self._启用表情回应 and 消息ID:
            try:
                if 消息类型 == "group":
                    表情ID = random.choice(表情回应ID列表)
                    任务 = asyncio.create_task(self._后台表情回应(消息ID, 表情ID))
                else:
                    任务 = asyncio.create_task(self._后台戳一戳(用户ID))
                self._后台任务.add(任务)
                任务.add_done_callback(self._后台任务.discard)
            except Exception as e:
                日志.debug("表情回应失败: %s", e)

        # ── 步骤16: 分发到网关 ──
        await self.handle_message(事件)

    # ── 媒体解析 ──────────────────────────────────────────────────────

    async def _解析媒体附件(self, 消息段列表: List[dict]) -> dict:
        """
        提取消息段中的所有媒体附件。
        返回: {段索引: {"本地路径": ..., "原始URL": ..., "文件名": ..., "MIME": ...}}
        优先用 data 里的 file_size 预判，超限不下载。
        """
        媒体映射: dict = {}

        for i, 段 in enumerate(消息段列表):
            段类型 = 段.get("type")
            数据 = 段.get("data", {})
            地址 = 数据.get("url", "") or 数据.get("file", "")
            文件名 = 数据.get("name", "") or 数据.get("file", "")

            本地路径: Optional[str] = None
            默认MIME = "application/octet-stream"

            if 段类型 in ("image", "record", "video", "file") and 地址:
                # ── 用 file_size 预判是否超限，没有 file_size 则不下载 ──
                预报大小 = 数据.get("file_size", "")
                大小限制 = self._下载限制.get(段类型, 50 * 1024 * 1024)

                if 预报大小:
                    try:
                        文件大小 = int(预报大小)
                    except (ValueError, TypeError):
                        文件大小 = 0
                    if 文件大小 and 文件大小 > 大小限制:
                        日志.info("%s 文件太大 (%d > %d bytes)，跳过下载",
                                  段类型, 文件大小, 大小限制)
                    else:
                        # 大小在限制内，下载
                        if 段类型 == "image":
                            本地路径 = await self._下载媒体(地址, "image", 大小限制)
                            默认MIME = "image/jpeg"
                        elif 段类型 == "record":
                            本地路径 = await self._下载媒体(地址, "audio", 大小限制)
                            默认MIME = "audio/ogg"
                        elif 段类型 == "video":
                            本地路径 = await self._下载媒体(地址, "video", 大小限制)
                            默认MIME = "video/mp4"
                        elif 段类型 == "file":
                            日志.info("文件段: path=%s url=%s file_id=%s",
                                      数据.get("path", ""), 数据.get("url", ""), 数据.get("file_id", ""))
                            本地路径 = await self._解析文件段路径(数据)
                            默认MIME = "application/octet-stream"
                else:
                    日志.info("%s 无 file_size，跳过下载", 段类型)

                MIME类型 = mimetypes.guess_type(本地路径 or 地址)[0] or 默认MIME
                媒体映射[i] = {
                    "本地路径": 本地路径,
                    "原始URL": 地址,
                    "文件名": 文件名,
                    "MIME": MIME类型,
                }
                if 本地路径:
                    日志.info("媒体已下载: %s (%s)", os.path.basename(本地路径), MIME类型)
                else:
                    日志.info("媒体未下载: %s", 地址[:80])

        return 媒体映射

    async def _解析文件段路径(self, 数据: dict) -> Optional[str]:
        """异步版本: 从 file 消息段中解析出本地文件路径。"""
        路径 = 数据.get("path", "")
        if 路径 and os.path.isfile(路径):
            return 路径

        地址 = 数据.get("url", "")
        if 地址.startswith("file://"):
            解析结果 = urllib.parse.urlparse(地址).path
            if os.path.isfile(解析结果):
                return 解析结果

        # 兜底: 用 file_id 调 get_file
        for 候选 in [数据.get("file_id", ""), 数据.get("file", "")]:
            if not 候选:
                continue
            try:
                if self._HTTP接口地址:
                    文件信息 = await self._HTTP调用("get_file", {"file_id": 候选})
                else:
                    文件信息 = await self._接口调用器.获取文件(候选)
                if 文件信息.get("status") == "ok":
                    文件路径 = 文件信息.get("data", {}).get("file", "")
                    if 文件路径 and os.path.isfile(文件路径):
                        日志.info("get_file 解析成功: %s", 文件路径)
                        return 文件路径
            except Exception as e:
                日志.debug("get_file 失败 candidate=%s: %s", 候选, e)

        return None

    async def _解析回复消息(self, 消息段列表: List[dict]) -> tuple:
        """解析回复段，获取被回复消息的文本和媒体映射。"""
        回复段 = next((s for s in 消息段列表 if s.get("type") == "reply"), None)
        被回复ID = str(回复段.get("data", {}).get("id", "")) if 回复段 else ""

        if not 被回复ID:
            return None, None, {}

        回复文本 = None
        回复媒体映射: dict = {}

        try:
            被回复消息 = await self._接口调用器.获取消息(被回复ID)
            if 被回复消息.get("status") == "ok":
                原始段列表 = 被回复消息.get("data", {}).get("message", [])
                if isinstance(原始段列表, list):
                    回复媒体映射 = await self._解析媒体附件(原始段列表)
                    回复文本 = 构建完整文本(原始段列表, 回复媒体映射)
                    # 截断引用文本（保留完整媒体标签）
                    if 回复文本 and len(回复文本) > self._引用文本最大字数:
                        回复文本 = _智能截断保留媒体标签(回复文本, self._引用文本最大字数)
                    日志.info("回复消息: ID=%s 文本=%s",
                              被回复ID, 回复文本[:40] if 回复文本 else "(空)")
        except Exception as e:
            日志.debug("获取回复消息失败 %s: %s", 被回复ID, e)

        return 被回复ID, 回复文本, 回复媒体映射

    # ── 后台任务 ──────────────────────────────────────────────────────

    async def _后台表情回应(self, 消息ID: str, 表情ID: int):
        try:
            结果 = await self._接口调用器.设置表情回应(消息ID, 表情ID)
            if 结果.get("status") != "ok":
                日志.warning("表情回应失败: %s", 结果)
        except Exception as e:
            日志.warning("表情回应异常: %s", e)

    async def _后台戳一戳(self, 用户ID: str):
        try:
            结果 = await self._接口调用器.戳一戳好友(用户ID)
            if 结果.get("status") != "ok":
                日志.warning("戳一戳失败: %s", 结果)
        except Exception as e:
            日志.warning("戳一戳异常: %s", e)

    async def _获取群名称(self, 群ID: str):
        if not self._接口调用器 or 群ID in self._群名缓存:
            return
        try:
            结果 = await self._接口调用器.获取群信息(群ID)
            名称 = 结果.get("data", {}).get("group_name", "")
            if 名称:
                self._群名缓存.设置(群ID, 名称)
                日志.debug("群名: %s → %s", 群ID, 名称)
        except Exception as e:
            日志.debug("获取群名失败 %s: %s", 群ID, e)

    # ── 媒体下载 ──────────────────────────────────────────────────────

    async def _下载媒体(self, 地址: str, 媒体类型: str = "image", 大小限制: int = 0) -> Optional[str]:
        """
        下载媒体文件到本地临时目录。
        超过大小限制时不下载，返回 None (调用方会保留 URL)。
        """
        # 推断扩展名
        扩展名 = ".jpg"
        URL路径 = urllib.parse.urlparse(地址).path.lower()
        for 候选扩展名 in (".png", ".gif", ".webp", ".ogg", ".mp3", ".wav", ".mp4", ".mov"):
            if URL路径.endswith(候选扩展名):
                扩展名 = 候选扩展名
                break
        else:
            if 媒体类型 == "audio":
                扩展名 = ".ogg"
            elif 媒体类型 == "video":
                扩展名 = ".mp4"
            elif 媒体类型 == "file":
                扩展名 = ".bin"

        限制字节 = 大小限制 or (10 * 1024 * 1024)
        超时秒数 = 15 if 媒体类型 == "image" else 60

        def _同步下载() -> Optional[str]:
            try:
                # ── 第一步: HEAD 请求预检文件大小 ──
                try:
                    头请求 = urllib.request.Request(地址, method="HEAD")
                    with urllib.request.urlopen(头请求, timeout=10) as 头响应:
                        内容长度 = 头响应.getheader("Content-Length")
                        if 内容长度 and int(内容长度) > 限制字节:
                            日志.info("文件太大 (%s > %d bytes)，跳过下载",
                                      内容长度, 限制字节)
                            return None
                except Exception:
                    pass  # HEAD 失败就继续尝试下载

                # ── 第二步: 流式下载，边下边检查 ──
                请求 = urllib.request.Request(地址)
                with urllib.request.urlopen(请求, timeout=超时秒数) as 响应:
                    块大小 = 64 * 1024  # 64KB 一块
                    已下载 = bytearray()
                    while True:
                        块 = 响应.read(块大小)
                        if not 块:
                            break
                        已下载.extend(块)
                        if len(已下载) > 限制字节:
                            日志.info("下载中超过限制 (%d > %d bytes)，中断",
                                      len(已下载), 限制字节)
                            return None
                    数据 = bytes(已下载)

                if 媒体类型 == "image":
                    return cache_image_from_bytes(数据, ext=扩展名)
                else:
                    fd, 路径 = tempfile.mkstemp(suffix=扩展名)
                    try:
                        with os.fdopen(fd, "wb") as f:
                            f.write(数据)
                        return 路径
                    except Exception:
                        os.close(fd)
                        try:
                            os.unlink(路径)
                        except OSError:
                            pass
                        raise
            except Exception as e:
                日志.warning("下载失败: %s", e)
                return None

        try:
            return await asyncio.to_thread(_同步下载)
        except Exception as e:
            日志.warning("下载异常 %s: %s", 地址, e)
            return None

    # ══════════════════════════════════════════════════════════════════
    # 投递辅助 (发送链路)
    # ══════════════════════════════════════════════════════════════════

    def _获取投递目标(self, 会话ID: str) -> tuple[str | None, str]:
        """
        根据会话ID解析出 (消息类型, 目标ID)。
        解析优先级：
          1. 缓存（来自接收链路记录的投递信息）
          2. napcat_group_<群ID> / napcat_<用户ID> 格式
          3. 纯数字 → 从缓存推断类型，查不到则报错
        """
        # 先查缓存
        投递 = self._投递信息.获取(会话ID, {})
        消息类型 = 投递.get("消息类型", "")
        目标ID = 投递.get("目标ID", "")

        if 目标ID and 消息类型:
            return 消息类型, str(目标ID)

        # 解析格式
        if 会话ID.startswith("napcat_group_"):
            目标ID = 会话ID.removeprefix("napcat_group_")
            消息类型 = "group"
        elif 会话ID.startswith("napcat_"):
            目标ID = 会话ID.removeprefix("napcat_")
            消息类型 = "private"
        elif 会话ID.lstrip("-").isdigit():
            # 纯数字：从缓存推断类型
            目标ID = 会话ID
            for 前缀 in (f"napcat_group_{会话ID}", f"napcat_{会话ID}"):
                信息 = self._投递信息.获取(前缀, {})
                if 信息.get("目标ID"):
                    消息类型 = 信息["消息类型"]
                    break
            if not 消息类型:
                return None, f"无法推断 '{会话ID}' 的类型（群聊/私聊）。请先与该会话交互，或使用 'napcat_group_{会话ID}' / 'napcat_{会话ID}' 格式"
        else:
            return None, f"无效的会话ID格式: '{会话ID}'。群聊用 'napcat_group_<群ID>'，私聊用 'napcat_<用户ID>'"

        if not 目标ID:
            return None, f"会话ID中目标ID为空: '{会话ID}'"

        return 消息类型, str(目标ID)

    # ── 消息拆分 ──────────────────────────────────────────────────────

    @staticmethod
    def _拆分文本(文本: str, 最大长度: int = 1500) -> List[str]:
        """在段落/句子边界处拆分长文本。"""
        if len(文本) <= 最大长度:
            return [文本]

        段落: List[str] = []
        剩余 = 文本

        while len(剩余) > 最大长度:
            # 优先在段落边界拆分
            分割位置 = 剩余.rfind("\n\n", 0, 最大长度)
            # 其次在换行处
            if 分割位置 < 最大长度 * 0.3:
                分割位置 = 剩余.rfind("\n", 0, 最大长度)
            # 再次在中/英文句号处
            if 分割位置 < 最大长度 * 0.3:
                for 标点 in ("。", "！", "？", "；", ".", "!", "?"):
                    位置 = 剩余.rfind(标点, 0, 最大长度)
                    if 位置 > 0:
                        分割位置 = 位置 + 1
                        break
            # 最后在空格处
            if 分割位置 < 最大长度 * 0.3:
                分割位置 = 剩余.rfind(" ", 0, 最大长度)
                if 分割位置 < 最大长度 * 0.3:
                    分割位置 = 最大长度

            段落.append(剩余[:分割位置].strip())
            剩余 = 剩余[分割位置:].strip()

        if 剩余:
            段落.append(剩余)

        return [段 for 段 in 段落 if 段]

    async def _发送合并转发(self, 会话ID: str, 内容: str, 回复目标: Optional[str] = None) -> Optional[SendResult]:
        """尝试以合并转发方式发送长内容。失败时返回 None，调用方回退到拆分发送。

        如果内容中包含 CQ 码，先将其全部提取拼成一条普通消息单独发送，
        然后只把纯文本部分走合并转发。
        """
        投递 = self._投递信息.获取(会话ID, {})
        消息类型 = 投递.get("消息类型", "")
        目标ID = 投递.get("目标ID", "")
        if not 目标ID:
            消息类型, 目标ID = self._获取投递目标(会话ID)
            if 消息类型 is None:
                return None  # 格式错误，回退到拆分发送

        # ── 提取 CQ 码，单独作为一条普通消息发送 ──
        片段列表 = 拆分CQ码(内容)
        CQ码列表 = [片段 for 类型, 片段 in 片段列表 if 类型 == "cq"]
        纯文本 = "".join(片段 for 类型, 片段 in 片段列表 if 类型 == "text")

        if CQ码列表:
            CQ消息 = "".join(CQ码列表)
            日志.info("CQ码单独发送: %s", CQ消息[:80])
            try:
                if 消息类型 == "group":
                    await self._接口调用器.发送群聊消息(目标ID, CQ消息)
                else:
                    await self._接口调用器.发送私聊消息(目标ID, CQ消息)
            except Exception as e:
                日志.error("CQ码发送失败: %s", e)

        # ── 没有纯文本了，不需要合并转发 ──
        if not 纯文本.strip():
            return SendResult(success=True)

        # ── 纯文本走合并转发 ──
        节点列表 = []
        if 回复目标:
            节点列表.append({"type": "node", "data": {"id": int(回复目标)}})

        机器人ID = self._机器人QQ号 or "0"
        节点列表.append({
            "type": "node",
            "data": {
                "uin": int(机器人ID),
                "name": self._合并转发昵称,
                "content": [构建文本段(纯文本)],
            },
        })

        try:
            if 消息类型 == "group":
                结果 = await self._接口调用器.发送群合并转发(目标ID, 节点列表)
            else:
                结果 = await self._接口调用器.发送私聊合并转发(目标ID, 节点列表)

            if 结果.get("status") == "ok" or 结果.get("retcode", -1) == 0:
                return SendResult(success=True)
            日志.debug("合并转发失败 (retcode=%s), 回退到拆分", 结果.get("retcode"))
            return None
        except Exception as e:
            日志.debug("合并转发异常: %s, 回退到拆分", e)
            return None

    # ══════════════════════════════════════════════════════════════════
    # 发送方法 (发送链路)
    # ══════════════════════════════════════════════════════════════════

    async def send(self, chat_id: str, content: str = "", **kwargs) -> SendResult:
        """
        发送文本消息。链路: CQ码检测 → 构建消息段 → 获取投递目标 → WS/HTTP发送 → 返回结果。
        长消息自动拆分或合并转发。
        支持 ```CQ ... ``` 代码块直接发送 CQ 码。
        """
        if not self._接口调用器:
            return SendResult(success=False, error="客户端未初始化")

        回复目标 = kwargs.get("reply_to")
        回复CQ = f"[CQ:reply,id={回复目标}]" if 回复目标 else ""
        文本预览 = content[:20] if content else "非文本"
        日志.info("▶ 发送: 会话=%s 长度=%d 预览=%s", chat_id, len(content), 文本预览)

        # ── CQ 码检测 (```CQ ... ```) ──
        内容 = content.strip()
        if 内容.startswith("```CQ") and 内容.endswith("```"):
            CQ文本 = 内容[len("```CQ"):].rsplit("```", 1)[0].strip()
            if not CQ文本:
                return SendResult(success=False, error="CQ码块内容为空")
            if 回复CQ:
                CQ文本 = 回复CQ + CQ文本
            日志.info("CQ码: %s", CQ文本[:80])
            消息类型, 目标ID = self._获取投递目标(chat_id)
            if 消息类型 is None:
                return SendResult(success=False, error=目标ID)
            try:
                if 消息类型 == "group":
                    结果 = await self._接口调用器.发送群聊消息(目标ID, CQ文本)
                else:
                    结果 = await self._接口调用器.发送私聊消息(目标ID, CQ文本)
            except Exception as e:
                日志.error("CQ码发送失败: %s", e)
                return SendResult(success=False, error=str(e))
            if 结果.get("retcode", 0) == 0:
                return SendResult(success=True)
            错误 = 结果.get("wording", 结果.get("msg", "未知错误"))
            return SendResult(success=False, error=f"OneBot API 错误: {错误}")

        # ── 长消息处理 ──
        if len(content) > self._合并转发阈值:
            消息类型, 目标ID = self._获取投递目标(chat_id)
            if 消息类型 is None:
                return SendResult(success=False, error=目标ID)

            # 群聊超过阈值 → 优先合并转发
            if 消息类型 == "group":
                转发结果 = await self._发送合并转发(chat_id, content, 回复目标)
                if 转发结果:
                    日志.info("✓ 合并转发成功 (阈值=%d)", self._合并转发阈值)
                    return 转发结果
                日志.info("合并转发失败，回退到拆分发送")

        # ── 超长消息拆分发送 (超过绝对上限时触发) ──
        if len(content) > 消息最大长度:
            段落列表 = self._拆分文本(content)
            日志.info("拆分为 %d 段", len(段落列表))
            for i, 段落 in enumerate(段落列表):
                消息段 = 构建消息数组(段落, 回复目标=回复目标)
                if not 消息段:
                    continue
                try:
                    类型, 目标 = self._获取投递目标(chat_id)
                    if 类型 is None:
                        return SendResult(success=False, error=目标)
                    if 类型 == "group":
                        结果 = await self._接口调用器.发送群聊消息(目标, 消息段)
                    else:
                        结果 = await self._接口调用器.发送私聊消息(目标, 消息段)
                    if 结果.get("status") == "failed" or 结果.get("retcode", 0) != 0:
                        错误 = 结果.get("wording") or 结果.get("msg") or "未知错误"
                        日志.error("段%d/%d 发送失败: %s", i + 1, len(段落列表), 错误)
                        return SendResult(success=False, error=f"段{i+1}发送失败: {错误}")
                    日志.info("段%d/%d 发送完成", i + 1, len(段落列表))
                except Exception as e:
                    日志.error("段%d发送异常: %s", i + 1, e)
                    return SendResult(success=False, error=str(e))
                回复目标 = None  # 只有第一段带回复

            return SendResult(success=True)

        # ── 普通消息 (统一用 CQ 码字符串发送) ──
        CQ文本 = 回复CQ + 文本转CQ码(content)
        if not CQ文本.strip():
            return SendResult(success=False, error="消息为空")

        try:
            消息类型, 目标ID = self._获取投递目标(chat_id)
            if 消息类型 is None:
                return SendResult(success=False, error=目标ID)
            日志.info("→ %s:%s", 消息类型, 目标ID)

            if 消息类型 == "group":
                结果 = await self._接口调用器.发送群聊消息(目标ID, CQ文本)
            else:
                结果 = await self._接口调用器.发送私聊消息(目标ID, CQ文本)

            if 结果.get("status") == "failed" or 结果.get("retcode", 0) != 0:
                错误 = 结果.get("wording") or 结果.get("message") or 结果.get("msg") or "未知错误"
                日志.error("✗ 发送失败: %s", 错误)
                return SendResult(success=False, error=f"OneBot API 错误: {错误}")

            日志.info("✓ 发送成功")
            return SendResult(success=True)

        except Exception as e:
            日志.error("✗ 发送异常: %s", e)
            return SendResult(success=False, error=str(e))

    async def send_image(self, chat_id: str, image_url: str, caption: str = "") -> SendResult:
        """发送图片 (URL)。"""
        if not image_url or not image_url.strip():
            return SendResult(success=False, error="图片URL为空")
        if not self._接口调用器:
            return SendResult(success=False, error="客户端未初始化")

        CQ文本 = ""
        if caption and caption.strip():
            CQ文本 = caption
        CQ文本 += f"[CQ:image,file={image_url}]"

        try:
            消息类型, 目标ID = self._获取投递目标(chat_id)
            if 消息类型 is None:
                return SendResult(success=False, error=目标ID)
            if 消息类型 == "group":
                结果 = await self._接口调用器.发送群聊消息(目标ID, CQ文本)
            else:
                结果 = await self._接口调用器.发送私聊消息(目标ID, CQ文本)
            if 结果.get("status") == "failed" or 结果.get("retcode", 0) != 0:
                错误 = 结果.get("wording") or 结果.get("message") or 结果.get("msg") or "未知错误"
                return SendResult(success=False, error=f"图片发送失败: {错误}")
            return SendResult(success=True)
        except Exception as e:
            return SendResult(success=False, error=str(e))

    async def send_image_file(self, chat_id: str, image_path: str, caption: str = "", **kwargs) -> SendResult:
        """
        发送本地图片文件。
        优先用 HTTP API (反向 WS 下图片消息不返回 echo，会导致 60s 超时)。
        """
        if not image_path or not os.path.isfile(image_path):
            return SendResult(success=False, error=f"图片文件不存在: {image_path}")

        if caption and caption.strip():
            try:
                await self.send(chat_id, caption)
            except Exception as e:
                日志.warning("图片caption发送失败: %s", e)

        回复目标 = kwargs.get("reply_to")
        CQ文本 = ""
        if 回复目标:
            CQ文本 = f"[CQ:reply,id={回复目标}]"
        CQ文本 += f"[CQ:image,file=file:///{image_path.lstrip('/')}]"
        消息类型, 目标ID = self._获取投递目标(chat_id)
        if 消息类型 is None:
            return SendResult(success=False, error=目标ID)
        日志.info("发送图片: %s → %s:%s", image_path, 消息类型, 目标ID)

        # 优先 HTTP API
        if self._HTTP接口地址:
            try:
                参数 = {
                    "group_id" if 消息类型 == "group" else "user_id": int(目标ID),
                    "message": CQ文本,
                }
                结果 = await self._HTTP调用(
                    "send_group_msg" if 消息类型 == "group" else "send_private_msg", 参数
                )
                返回码 = 结果.get("retcode", -1)
                if 返回码 in (0, 200):
                    if 返回码 == 200:
                        日志.info("图片发送 retcode=200 (调用超时但可能已送达)")
                    return SendResult(success=True)
                错误 = 结果.get("message", "") or 结果.get("wording", "") or 结果.get("msg", "")
                return SendResult(success=False, error=错误 or f"retcode={返回码}")
            except Exception as e:
                日志.warning("HTTP图片发送失败，回退WS: %s", e)

        # WS 回退
        if not self._接口调用器:
            return SendResult(success=False, error="客户端未初始化")

        try:
            if 消息类型 == "group":
                结果 = await self._接口调用器.发送群聊消息(目标ID, CQ文本)
            else:
                结果 = await self._接口调用器.发送私聊消息(目标ID, CQ文本)
            if 结果.get("status") == "failed" or 结果.get("retcode", 0) != 0:
                错误 = 结果.get("wording") or 结果.get("message") or 结果.get("msg") or "未知错误"
                if "timeout" in 错误.lower():
                    日志.info("WS图片超时 — 可能已送达")
                    return SendResult(success=True)
                return SendResult(success=False, error=错误)
            return SendResult(success=True)
        except Exception as e:
            return SendResult(success=False, error=str(e))

    async def send_typing(self, chat_id: str, **kwargs):
        pass

    async def get_chat_info(self, chat_id: str) -> dict:
        if chat_id.startswith("napcat_group_"):
            群ID = chat_id.removeprefix("napcat_group_")
            名称 = self._群名缓存.获取(群ID, f"QQ群{群ID}")
            return {"name": 名称, "type": "group", "chat_id": chat_id}
        elif chat_id.startswith("napcat_"):
            用户ID = chat_id.removeprefix("napcat_")
            名称 = self._昵称缓存.获取(用户ID, f"QQ用户{用户ID}")
            return {"name": 名称, "type": "private", "chat_id": chat_id}
        return {"name": chat_id, "type": "unknown", "chat_id": chat_id}

    async def send_voice(self, chat_id: str, audio_path: str,
                         reply_to: Optional[str] = None, **kwargs) -> SendResult:
        if not audio_path or not os.path.isfile(audio_path):
            return SendResult(success=False, error=f"语音文件不存在: {audio_path}")
        if not self._接口调用器:
            return SendResult(success=False, error="客户端未就绪")

        CQ文本 = ""
        if reply_to:
            CQ文本 = f"[CQ:reply,id={reply_to}]"
        CQ文本 += f"[CQ:record,file=file:///{audio_path.lstrip('/')}]"
        try:
            消息类型, 目标ID = self._获取投递目标(chat_id)
            if 消息类型 is None:
                return SendResult(success=False, error=目标ID)
            if 消息类型 == "group":
                结果 = await self._接口调用器.发送群聊消息(目标ID, CQ文本)
            else:
                结果 = await self._接口调用器.发送私聊消息(目标ID, CQ文本)

            if 结果.get("status") == "failed" or 结果.get("retcode", 0) != 0:
                错误 = 结果.get("wording") or 结果.get("message") or 结果.get("msg") or "未知错误"
                return SendResult(success=False, error=f"语音发送失败: {错误}")

            return SendResult(success=True)
        except Exception as e:
            return SendResult(success=False, error=str(e))

    async def send_document(self, chat_id: str, file_path: str = "", caption: str = "", **kwargs) -> SendResult:
        路径 = file_path or kwargs.get("path", "")
        if not self._接口调用器:
            return SendResult(success=False, error="客户端未就绪")

        if not 路径 or not os.path.isfile(路径):
            return SendResult(success=False, error=f"文件不存在: {路径}")

        try:
            消息类型, 目标ID = self._获取投递目标(chat_id)
            if 消息类型 is None:
                return SendResult(success=False, error=目标ID)

            if caption and caption.strip():
                try:
                    if 消息类型 == "group":
                        await self._接口调用器.发送群聊消息(目标ID, caption)
                    else:
                        await self._接口调用器.发送私聊消息(目标ID, caption)
                except Exception as e:
                    日志.warning("文件caption发送失败: %s", e)

            if 消息类型 == "group":
                结果 = await self._接口调用器.上传群文件(目标ID, 路径)
            else:
                结果 = await self._接口调用器.上传私聊文件(目标ID, 路径)

            if 结果.get("status") == "failed" or 结果.get("retcode", 0) != 0:
                错误 = 结果.get("wording") or 结果.get("msg") or "上传失败"
                return SendResult(success=False, error=错误)
            return SendResult(success=True)
        except Exception as e:
            return SendResult(success=False, error=str(e))
