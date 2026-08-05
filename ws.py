import asyncio
import hmac
import json
import logging
import os
import time
from typing import Optional
from urllib.parse import parse_qs, urlparse
import websockets
from websockets.asyncio.server import ServerConnection

from .tools import 打印

logger = logging.getLogger(__name__)


class WS:
    """反向 WebSocket 服务端（OneBot v11），配置在初始化时传入，启动时直接监听。"""

    def __init__(
        self,
        事件处理器,
        监听地址: str = "127.0.0.1",
        监听端口: int = 6700,
        访问令牌: str = "",
    ):
        """
        参数:
            事件处理器: 异步回调，处理收到的 OneBot 事件。
            监听地址: 绑定地址（如 "0.0.0.0" 或 "127.0.0.1"）。
            监听端口: 绑定端口（如 6700）。
            访问令牌: 可选 Bearer token，用于认证 NapCat 等客户端。
        """
        self._事件处理器 = 事件处理器
        self._监听地址 = 监听地址
        self._监听端口 = 监听端口
        self._访问令牌 = 访问令牌

        self._ws连接实例: Optional[ServerConnection] = None
        self._待响应映射表: dict[str, asyncio.Future] = {}
        self._自增计数器: int = 0
        self._服务端 = None  # asyncio 服务器对象，由启动() 创建

    async def 启动(self) -> None:
        """启动反向 WS 服务端（使用 __init__ 中保存的配置）。"""
        async def _处理连接(ws连接: ServerConnection):
            await self._认证并处理连接(ws连接) # type: ignore[attr-defined]

        self._服务端 = await websockets.serve(
            _处理连接,
            self._监听地址,
            self._监听端口,
            ping_interval=20,
            ping_timeout=20,
        )
        logger.info(f"反向WS服务端启动：ws://{self._监听地址}:{self._监听端口}，等待连接")
        打印(f"反向WS服务端启动：ws://{self._监听地址}:{self._监听端口}，等待连接")

    async def 停止(self) -> None:
        """停止服务端并清理资源。"""
        if self._ws连接实例:
            try:
                await self._ws连接实例.close()
            except Exception:
                pass
        if self._服务端:
            self._服务端.close()
            await self._服务端.wait_closed()

    # ── 内部方法 ──────────────────────────────────────────────────────────

    async def _认证并处理连接(self, ws连接) -> None:
        """认证 NapCat 连接，然后进入消息接收循环。"""
        self._ws连接实例 = ws连接
        if self._访问令牌:
            认证头 = ws连接.request.headers.get("Authorization", "")
            提取的令牌 = 认证头.removeprefix("Bearer ").strip()

            if not 提取的令牌:
                try:
                    查询参数 = parse_qs(urlparse(ws连接.request.path).query)
                    提取的令牌 = 查询参数.get("access_token", [""])[0]
                except Exception:
                    提取的令牌 = ""

            if not hmac.compare_digest(提取的令牌, self._访问令牌):
                await ws连接.close(1008, "认证失败")
                return

        logger.info(f"反向WS客户端已连接：{ws连接.remote_address}")
        打印(f"反向WS客户端已连接：{ws连接.remote_address}")

        try:
            async for 原始消息 in ws连接:
                await self._处理消息(原始消息)
        except websockets.ConnectionClosed as e:
            logger.warning(f"反向WS连接关闭: rcvd={e.rcvd} sent={e.sent}")
            打印(f"反向WS连接关闭: rcvd={e.rcvd} sent={e.sent}")
        except Exception as e:
            logger.error(f"反向WS处理错误: {e}", exc_info=True)
            打印(f"反向WS处理错误: {e}")
        finally:
            logger.info("反向WS客户端已断开")
            打印("反向WS客户端已断开")
            for 正在等待 in self._待响应映射表.values():
                if not 正在等待.done():
                    正在等待.set_exception(ConnectionError("WebSocket 已断开"))
            self._待响应映射表.clear()

    async def _处理消息(self, 原始消息: str) -> None:
        """解析并分发 WebSocket 消息。"""
        try:
            数据 = json.loads(原始消息)

            if "echo" in 数据:
                self.处理echo响应(数据)
            elif 数据.get("post_type") == "meta_event":
                pass
            else:
                await self._事件处理器(数据)

        except json.JSONDecodeError:
            logger.debug(f"反向WS: 非JSON消息: {原始消息[:200]}")
        except Exception as e:
            logger.error(f"反向WS事件处理错误: {e}", exc_info=True)

    async def 调用API(self, 动作: str, 参数: dict, 超时秒数: float = 120.0) -> dict:
        """调用 OneBot API 并等待响应。"""
        if not self._ws连接实例:
            return {"status": "failed", "msg": "WebSocket 未连接"}

        self._自增计数器 += 1
        回显标识 = f"napcat_{self._自增计数器}_{int(time.time() * 1000)}"

        数据包 = json.dumps({
            "action": 动作,
            "params": 参数,
            "echo": 回显标识,
        })

        future: asyncio.Future = asyncio.get_running_loop().create_future()
        self._待响应映射表[回显标识] = future

        try:
            await self._ws连接实例.send(数据包)
            return await asyncio.wait_for(future, timeout=超时秒数)
        except asyncio.TimeoutError:
            return {"status": "failed", "msg": f"WebSocket 调用「{动作}」超时未响应"}
        except websockets.exceptions.ConnectionClosed as e:
            return {"status": "failed", "msg": f"连接已关闭: {e}"}
        except ConnectionError as e:
            return {"status": "failed", "msg": str(e)}
        finally:
            self._待响应映射表.pop(回显标识, None)

    def 处理echo响应(self, 数据: dict) -> None:
        """处理 WebSocket 返回的带 echo 的响应。"""
        回显标识 = 数据.get("echo")
        if not 回显标识:
            return
        future = self._待响应映射表.pop(回显标识, None)
        if future and not future.done():
            future.set_result(数据)

    # ── 常用 API 封装（保持不变）──────────────────────────────────────────

    async def 发送私聊消息(self, 用户ID: str, 消息内容) -> dict:
        return await self.调用API("send_private_msg", {
            "user_id": int(用户ID),
            "message": 消息内容,
        })

    async def 发送群聊消息(self, 群ID: str, 消息内容) -> dict:
        return await self.调用API("send_group_msg", {
            "group_id": int(群ID),
            "message": 消息内容,
        })

    async def 获取群信息(self, 群ID: str) -> dict:
        return await self.调用API("get_group_info", {"group_id": int(群ID)})

    async def 获取文件(self, 文件ID: str) -> dict:
        return await self.调用API("get_file", {"file_id": 文件ID})

    async def 获取消息(self, 消息ID: str) -> dict:
        return await self.调用API("get_msg", {"message_id": int(消息ID)})

    async def 上传群文件(self, 群ID: str, 文件路径: str, 文件名: str = "") -> dict:
        return await self.调用API("upload_group_file", {
            "group_id": int(群ID),
            "file": 文件路径,
            "name": 文件名 or os.path.basename(文件路径),
        })

    async def 上传私聊文件(self, 用户ID: str, 文件路径: str, 文件名: str = "") -> dict:
        return await self.调用API("upload_private_file", {
            "user_id": int(用户ID),
            "file": 文件路径,
            "name": 文件名 or os.path.basename(文件路径),
        })

    async def 发送群合并转发(self, 群ID: str, 消息节点列表: list) -> dict:
        return await self.调用API("send_group_forward_msg", {
            "group_id": int(群ID),
            "messages": 消息节点列表,
        })

    async def 发送私聊合并转发(self, 用户ID: str, 消息节点列表: list) -> dict:
        return await self.调用API("send_private_forward_msg", {
            "user_id": int(用户ID),
            "messages": 消息节点列表,
        })

    async def 设置表情回应(self, 消息ID: str, 表情ID: int = 12) -> dict:
        return await self.调用API("set_msg_emoji_like", {
            "message_id": int(消息ID),
            "emoji_id": 表情ID,
            "set": True,
        })

    async def 戳一戳好友(self, 用户ID: str) -> dict:
        return await self.调用API("friend_poke", {"user_id": int(用户ID)})