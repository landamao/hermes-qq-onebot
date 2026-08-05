"""NapCat HTTP API 调用器 — 独立于 WS 通道。

用途：图片发送等可能超时的操作（反向 WS 下图片消息不返回 echo，会导致 60s 超时）。
用 asyncio.to_thread 包装同步 HTTP 请求，不阻塞事件循环。
"""

import json
import asyncio
import logging
import urllib.request

logger = logging.getLogger(__name__)


class NapcatHttp:
    """通过 HTTP 调用 OneBot API，独立于 WS 通道。"""

    def __init__(self, HTTP接口地址: str, 访问令牌: str = ""):
        self._接口地址 = HTTP接口地址.rstrip("/")
        self._访问令牌 = 访问令牌

    async def 调用API(self, 动作: str, 参数: dict) -> dict:
        """通过 HTTP 调用 OneBot API。"""
        if not self._接口地址:
            return {"status": "failed", "msg": "HTTP 接口未配置"}

        请求地址 = f"{self._接口地址}/{动作}"
        请求体 = json.dumps(参数).encode()
        请求头 = {"Content-Type": "application/json"}
        if self._访问令牌:
            请求头["Authorization"] = f"Bearer {self._访问令牌}"

        请求 = urllib.request.Request(请求地址, data=请求体, headers=请求头)

        try:
            def _同步HTTP调用():
                with urllib.request.urlopen(请求, timeout=30) as 响应:
                    return json.loads(响应.read().decode())

            return await asyncio.to_thread(_同步HTTP调用)
        except Exception as e:
            return {"status": "failed", "msg": str(e)}

    # ── 常用 API 封装 ──────────────────────────────────────────────────

    async def 发送群聊消息(self, 群ID: str, 消息内容: str) -> dict:
        """通过 HTTP 发送群聊消息。"""
        return await self.调用API("send_group_msg", {
            "group_id": int(群ID),
            "message": 消息内容,
        })

    async def 发送私聊消息(self, 用户ID: str, 消息内容: str) -> dict:
        """通过 HTTP 发送私聊消息。"""
        return await self.调用API("send_private_msg", {
            "user_id": int(用户ID),
            "message": 消息内容,
        })

    async def 获取文件信息(self, 文件ID: str) -> dict:
        """通过 HTTP 获取文件信息。"""
        return await self.调用API("get_file", {"file_id": 文件ID})
