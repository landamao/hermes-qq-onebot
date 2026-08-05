"""
NapCat QQ 适配器 — 基于 OneBot v11 协议 (仅反向 WS 模式)

架构:
    QQ 客户端 ←→ NapCat (OneBot 实现)
                      ↓ 反向 WebSocket (NapCat 主动连过来)
                 NapCat 适配器 (本文件)
                      ↓ 可选 HTTP API (图片发送、文件获取)
                 OneBot API
"""

import asyncio
import json
import logging
import mimetypes
import os
import random
import re
import urllib.parse
from typing import Any, Optional

from gateway.config import Platform, PlatformConfig
from gateway.platforms.base import (
    BasePlatformAdapter,
    MessageEvent,
    MessageType,
    SendResult,
)
from gateway.platforms.helpers import MessageDeduplicator

from .tools import *
from .ws import WS
from .napcat_http import NapcatHttp

logger = logging.getLogger(__name__)


class NapCat适配器(BasePlatformAdapter):
    """NapCat QQ 适配器 — 仅反向 WS 模式。

    QQ 不支持消息编辑（edit_message），网关会自动降级为分段发送。
    SendResult 不返回 message_id — 对 QQ 无意义，避免被误用于流式编辑。
    """

    def __init__(self, config: PlatformConfig):
        super().__init__(config, Platform("napcat"))
        self.config = config
        extra_config = config.extra or {}

        def 获取配置(键: str, 默认值):
            # 环境变量优先于配置文件，通常环境变量用于临时设置覆盖配置文件
            原始值 = os.getenv("NAPCAT_" + 键.upper())
            if 原始值 is None:
                return extra_config.get(键, 默认值)
            # 1. 尝试 JSON 解析（可处理数字、布尔、列表、字典等）
            try:
                return json.loads(原始值)
            except json.JSONDecodeError:
                pass
            # 2. JSON 失败时，手动识别常见的布尔关键词
            小写值 = 原始值.lower()
            if 小写值 in ('off', 'false', 'no', 'n'):
                return False
            if 小写值 in ('on', 'true', 'yes', 'y'):
                return True
            # 3. 其他情况原样返回字符串
            return 原始值

        # ── 反向 WS 配置 ──
        self.反向监听地址: str = 获取配置("reverse_host", "127.0.0.1")
        if not isinstance(self.反向监听地址, str):
            raise ValueError(f"reverse_host 必须是字符串; 收到 {type(self.反向监听地址).__name__}: {self.反向监听地址!r}")
        端口值 = 获取配置("reverse_port", 6700)
        try:
            self.反向监听端口: int = int(端口值)
        except (ValueError, TypeError):
            raise ValueError(f"reverse_port 必须是整数; 收到 {type(端口值).__name__}: {端口值!r}")
        令牌值 = 获取配置("access_token", "") or 获取配置("reverse_token", "")
        if not isinstance(令牌值, str):
            raise ValueError(f"access_token 必须是字符串; 收到 {type(令牌值).__name__}: {令牌值!r}")
        self.反向监听令牌: str = 令牌值

        # ── HTTP API（可选，推荐开启）──
        self.HTTP接口地址: str = 获取配置("http_api_url", "")
        if not isinstance(self.HTTP接口地址, str):
            raise ValueError(f"http_api_url 必须是字符串; 收到 {type(self.HTTP接口地址).__name__}: {self.HTTP接口地址!r}")
        http令牌值 = 获取配置("http_api_token", "") or self.反向监听令牌
        if not isinstance(http令牌值, str):
            raise ValueError(f"http_api_token 必须是字符串; 收到 {type(http令牌值).__name__}: {http令牌值!r}")
        self.http令牌: str = http令牌值

        # ── 表情回应 ──
        表情回应值 = 获取配置("emoji_react", False)
        if not isinstance(表情回应值, bool):
            raise ValueError(f"emoji_react 必须是布尔值; 收到 {type(表情回应值).__name__}: {表情回应值!r}")
        self.启用表情回应: bool = 表情回应值

        # ── 机器人信息 ──
        self.机器人QQ号: str = 获取配置("bot_self_id", "")
        if not isinstance(self.机器人QQ号, str):
            raise ValueError(f"bot_self_id 必须是字符串; 收到 {type(self.机器人QQ号).__name__}: {self.机器人QQ号!r}")

        # ── 媒体下载限制 ──
        默认限制: dict[str, str] = {
            "image": "10MB",
            "record": "10MB",
            "video": "10MB",
            "file": "10MB",
        }
        用户限制 = 获取配置("download_limits", {})
        if 用户限制 is None:
            用户限制 = {}
        if not isinstance(用户限制, dict):
            raise ValueError(f"download_limits 必须是字典; 收到 {type(用户限制).__name__}: {用户限制!r}")
        合并限制 = {**默认限制, **用户限制}
        self.下载限制字节: dict[str, int] = {键: 解析文件大小(值) for 键, 值 in 合并限制.items()}

        # ── 长消息处理 ──
        阈值 = 获取配置("merge_forward_threshold", 默认合并转发阈值)
        try:
            self.合并转发阈值: int = int(阈值)
        except (ValueError, TypeError):
            raise ValueError(f"merge_forward_threshold 必须是整数; 收到 {type(阈值).__name__}: {阈值!r}")
        self.合并转发昵称: str = 获取配置("forward_name", "纳西妲")
        if not isinstance(self.合并转发昵称, str):
            raise ValueError(f"forward_name 必须是字符串; 收到 {type(self.合并转发昵称).__name__}: {self.合并转发昵称!r}")

        # ── 引用回复文本最大字数 ──
        引用字数 = 获取配置("reply_text_max_length", 默认引用文本最大字数)
        try:
            self.引用文本最大字数: int = int(引用字数)
        except (ValueError, TypeError):
            raise ValueError(f"reply_text_max_length 必须是整数; 收到 {type(引用字数).__name__}: {引用字数!r}")

        # ── 关键词触发 ──
        模式列表 = 获取配置("mention_patterns", [])
        if isinstance(模式列表, str):
            模式列表 = [模式列表]
        elif not isinstance(模式列表, list):
            raise ValueError(
                f"mention_patterns 必须是列表或字符串; 收到 {type(模式列表).__name__}"
            )
        self.关键词模式列表: list[re.Pattern] = []
        for 模式文本 in 模式列表:
            if not isinstance(模式文本, str) or not 模式文本:
                continue
            try:
                self.关键词模式列表.append(re.compile(模式文本, re.IGNORECASE))
            except re.error as e:
                logger.error(f"无效的正则表达式: 「{模式文本}」：{e}")

        # ── 用户白名单 ──
        原始白名单 = 获取配置("allowed_qq_ids", "") or os.getenv("NAPCAT_ALLOWED_USERS", "")
        if isinstance(原始白名单, str):
            self.允许的用户集合: frozenset[str] = frozenset(
                QQ号.strip() for QQ号 in 原始白名单.split(",") if QQ号.strip()
            )
        elif isinstance(原始白名单, list):
            白名单 = [str(i or "").strip() for i in 原始白名单]
            self.允许的用户集合 = frozenset(QQ号 for QQ号 in 白名单 if QQ号)
        elif isinstance(原始白名单, (int, float)):
            # YAML 把裸数字解析为 int/float，如 allowed_qq_ids: 204676209
            self.允许的用户集合 = frozenset([str(int(原始白名单))])
        elif 原始白名单 is None or 原始白名单 == "":
            self.允许的用户集合 = frozenset()
        else:
            raise ValueError(
                f"allowed_qq_ids 必须是字符串、列表或数字; 收到 {type(原始白名单).__name__}: {原始白名单!r}"
            )

        # 必须显式设置允许所有用户，防止刚安装就全开放
        self.允许所有用户 = any(
            i.lower() in ('all', '*') for i in self.允许的用户集合
        )

        # ── 内部状态 ──
        self.ws = WS(
            self._处理WS事件,
            self.反向监听地址,
            self.反向监听端口,
            self.反向监听令牌,
        )
        self._HTTP调用器: Optional[NapcatHttp] = None
        if self.HTTP接口地址:
            self._HTTP调用器 = NapcatHttp(self.HTTP接口地址, self.http令牌)

        self._去重器 = MessageDeduplicator(max_size=2000)
        self._后台任务集合: set[asyncio.Task] = set()

        self._投递信息缓存 = 简易LRU缓存(最大容量=2000)
        self._群名缓存 = 简易LRU缓存(最大容量=500)
        self._用户名缓存 = 简易LRU缓存(最大容量=5000)

    # ═══════════════════════════════════════════════════════════════════════════════
    # 连接生命周期
    # ═══════════════════════════════════════════════════════════════════════════════

    async def connect(self, *_, **__) -> bool:
        """启动反向 WS 服务端，等待 NapCat 连接。"""
        await self.ws.启动()
        self._mark_connected()
        if self.HTTP接口地址:
            msg2 = f"HTTP接口已启用: {self.HTTP接口地址}"
            logger.info(msg2)
            打印(msg2)
        打印(f"配置: 监听地址={self.反向监听地址} 端口={self.反向监听端口} 令牌={'已设置' if self.反向监听令牌 else '未设置'}")
        打印(f"配置: HTTP接口={'已启用' if self.HTTP接口地址 else '未启用'} 表情回应={'已启用' if self.启用表情回应 else '未启用'}")
        打印(f"配置: 机器人QQ号={self.机器人QQ号 or '未设置(自动学习)'} 合并转发阈值={self.合并转发阈值} 引用文本最大字数={self.引用文本最大字数}")
        if self.允许所有用户:
            打印("配置: 允许所有用户=是（白名单不生效）")
        elif self.允许的用户集合:
            用户列表 = ", ".join(sorted(self.允许的用户集合))
            打印(f"配置: 允许所有用户=否 白名单用户({len(self.允许的用户集合)}): {用户列表}")
        else:
            打印("配置: 允许所有用户=否 白名单为空！请配置 NAPCAT_ALLOWED_USERS 环境变量或在插件配置中设置 allowed_qq_ids，否则无法接收任何消息")
        打印(f"配置: 下载限制={ {k: f'{v//1024//1024}MB' for k, v in self.下载限制字节.items()} }")
        if self.关键词模式列表:
            模式列表 = ", ".join(模式.pattern for 模式 in self.关键词模式列表)
            打印(f"配置: 关键词触发({len(self.关键词模式列表)}): {模式列表}")
        else:
            打印("配置: 关键词触发=无")
        return True

    async def disconnect(self):
        """停止服务端并清理资源。"""
        await self.ws.停止()

        for 任务 in list(self._后台任务集合):
            任务.cancel()
        if self._后台任务集合:
            await asyncio.gather(*self._后台任务集合, return_exceptions=True)
        self._后台任务集合.clear()

        self._mark_disconnected()

    # ═══════════════════════════════════════════════════════════════════════════════
    # 事件处理（接收链路）
    # ═══════════════════════════════════════════════════════════════════════════════

    async def _处理WS事件(self, 原始数据: dict):
        """WS 事件分发入口。"""
        事件类型 = 原始数据.get("post_type", "")

        # 自动学习机器人 QQ 号
        机器人QQ = str(原始数据.get("self_id", ""))
        if 机器人QQ:
            self.机器人QQ号 = 机器人QQ

        if 事件类型 == "message":
            任务 = asyncio.create_task(self._处理消息事件(原始数据))
            self._后台任务集合.add(任务)
            任务.add_done_callback(self._后台任务集合.discard)

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

        logger.info(f"▶ 收到{'群聊' if 消息类型 == 'group' else '私聊'}: 用户={昵称}({用户ID}) 群={群ID or '-'} 消息ID={消息ID}")

        # ── 步骤1: 去重 ──
        去重键 = f"napcat:{消息ID}" if 消息ID else f"napcat:{用户ID}:{str(原始数据.get('raw_message', ''))[:100]}"
        if self._去重器.is_duplicate(去重键):
            logger.info("✗ 重复消息，跳过")
            return

        # ── 步骤2: 过滤自己 ──
        if 用户ID == self.机器人QQ号:
            logger.info("✗ 自己的消息，跳过")
            return

        # ── 步骤3: 用户权限 ──
        if not (self.允许所有用户 or 用户ID in self.允许的用户集合):
            logger.info(f"✗ 用户「{昵称}（{用户ID}）」不在白名单，跳过此消息")
            return

        # ── 步骤4: 群聊触发检测 ──
        if 消息类型 == "group":
            if not self._群聊触发检测(消息段列表):
                return

        # ── 步骤5: 缓存昵称 ──
        if 昵称:
            self._用户名缓存.设置(用户ID, 昵称)
        if 昵称 and 昵称 != 用户ID:
            显示名称 = f"{昵称}({用户ID})"
        else:
            显示名称 = f"QQ用户({用户ID})"

        # ── 步骤6: 构建会话信息 ──
        if 消息类型 == "group":
            会话ID = f"napcat_group_{群ID}"
            会话名称 = self._群名缓存.获取(群ID, f"QQ群{群ID}")
            if 群ID not in self._群名缓存:
                任务 = asyncio.create_task(self._获取群名称(群ID))
                self._后台任务集合.add(任务)
                任务.add_done_callback(self._后台任务集合.discard)
        else:
            会话ID = f"napcat_private_{用户ID}"
            会话名称 = 昵称 or f"QQ用户{用户ID}"

        来源 = self.build_source(
            chat_id=会话ID,
            chat_name=会话名称,
            user_id=用户ID,
            user_name=显示名称,
            chat_type="group" if 消息类型 == "group" else "dm",
            thread_id=群ID if 消息类型 == "group" else None,
        )

        # ── 步骤7: 解析主消息的媒体附件 ──
        媒体映射 = await self._解析媒体附件(消息段列表)

        # ── 步骤8: 构建完整文本 (带详细标签) ──
        文本 = 构建完整可读文本(消息段列表, 媒体映射)
        logger.info(f"文本: {文本[:120] if 文本 else '(空)'}")

        # ── 步骤9: 解析回复的消息 ──
        回复ID, 回复文本, 回复媒体映射 = await self._解析回复消息(消息段列表)

        # ── 步骤10: 收集已下载的媒体路径 ──
        媒体路径, 媒体类型 = self._收集媒体路径(媒体映射, 回复媒体映射, 回复ID)

        # ── 步骤11: 兜底文本 ──
        文本 = self._兜底文本(文本, 媒体路径, 媒体类型)
        if not 文本.strip():
            logger.info("✗ 无有效内容")
            return

        # ── 步骤12: 推断消息分类 ──
        消息分类 = self._推断消息分类(媒体类型)

        # ── 步骤13: 记录投递信息 (供发送时回查) ──
        self._投递信息缓存.设置(会话ID, {
            "消息类型": 消息类型,
            "目标ID": 群ID if 消息类型 == "group" else 用户ID,
            "回复目标": 消息ID,
            "群ID": 群ID,
            "用户ID": 用户ID,
        })

        # ── 步骤14: 构建事件 ──
        回复文本字段 = None
        if 回复ID:
            if 回复文本:
                回复文本字段 = f"[Reply:msg_id={回复ID}] {回复文本}"
            else:
                回复文本字段 = f"[Reply:msg_id={回复ID}]"

        事件 = MessageEvent(
            message_type=消息分类,
            text=文本,
            source=来源,
            raw_message=原始数据,
            message_id=消息ID or None,
            media_urls=媒体路径,
            media_types=媒体类型,
            reply_to_message_id=回复ID,
            reply_to_text=回复文本字段,
        )

        logger.info(f"✓ 消息就绪: 分类={消息分类.value} 文本={len(文本)}字 媒体={len(媒体路径)}个 → 分发到网关")

        # ── 步骤15: 可选表情回应 ──
        if self.启用表情回应 and 消息ID:
            self._消息回应(消息类型, 消息ID, 用户ID)

        # ── 步骤16: 分发到网关 ──
        await self.handle_message(事件)

    # ── 接收链路辅助方法 ──────────────────────────────────────────────

    def _群聊触发检测(self, 消息段列表: list[dict]) -> bool:
        """群聊消息触发检测：@机器人 / 关键词 / 指令。"""
        机器人QQ号 = self.机器人QQ号
        被艾特 = any(
            段.get("type") == "at" and str(段.get("data", {}).get("qq", "")) == 机器人QQ号
            for 段 in 消息段列表
        )

        纯文本 = 从消息段提取纯文本(消息段列表)
        if not self.关键词模式列表 or not 纯文本:
            关键词匹配 = False
        else:
            关键词匹配 = any(模式.search(纯文本) for 模式 in self.关键词模式列表)
        是否指令 = 纯文本.startswith("/")

        if 是否指令:
            # 指令消息: 如果带了 @，必须是 @自己才处理
            指令中有艾特 = any(段.get("type") == "at" for 段 in 消息段列表)
            if 指令中有艾特 and not 被艾特:
                logger.info("✗ 指令@了别人，跳过")
                return False
            logger.info("✓ 指令消息通过")
            return True
        elif not 被艾特 and not 关键词匹配:
            logger.info("✗ 群聊未@且无关键词匹配")
            return False
        else:
            logger.info(f"✓ 群聊触发: 被@={被艾特} 关键词={关键词匹配}")
            return True

    # ── 媒体解析 ──────────────────────────────────────────────────────

    def _获取下载限制(self, 段类型: str) -> int:
        """获取指定媒体类型的下载大小限制（字节）。"""
        return self.下载限制字节.get(段类型, 10 * 1024 * 1024)

    async def _解析媒体附件(self, 消息段列表: list[dict]) -> dict:
        """提取消息段中的所有媒体附件。

        返回: {段索引: {"本地路径": ..., "原始URL": ..., "文件名": ..., "MIME": ...}}
        优先用 data 里的 file_size 预判，超限不下载。
        """
        媒体映射: dict[int, dict] = {}

        for 段索引, 段 in enumerate(消息段列表):
            段类型 = 段.get("type")
            数据 = 段.get("data", {})
            媒体地址 = 数据.get("url", "") or 数据.get("file", "")
            文件名 = 数据.get("name", "") or 数据.get("file", "")

            if 段类型 not in ("image", "record", "video", "file") or not 媒体地址:
                continue

            本地路径, 默认MIME = await self._下载段媒体(段类型, 数据, 媒体地址)
            MIME类型 = mimetypes.guess_type(本地路径 or 媒体地址)[0] or 默认MIME

            媒体映射[段索引] = {
                "本地路径": 本地路径,
                "原始URL": 媒体地址,
                "文件名": 文件名,
                "MIME": MIME类型,
            }

            if 本地路径:
                logger.info(f"媒体已下载: {os.path.basename(本地路径)} ({MIME类型})")
            else:
                logger.info(f"媒体未下载: {媒体地址[:80]}")

        return 媒体映射

    async def _下载段媒体(
        self, 段类型: str, 数据: dict, 媒体地址: str
    ) -> tuple[Optional[str], str]:
        """下载单个媒体段的文件，返回 (本地路径, 默认MIME)。"""
        预报大小 = 数据.get("file_size", "")
        大小限制 = self._获取下载限制(段类型)

        if not 预报大小:
            logger.info(f"{段类型} 无 file_size，跳过下载")
            return None, "application/octet-stream"

        try:
            文件大小 = int(预报大小)
        except (ValueError, TypeError):
            文件大小 = 0

        if 文件大小 and 文件大小 > 大小限制:
            logger.info(f"{段类型} 文件太大 ({文件大小} > {大小限制} bytes)，跳过下载")
            return None, "application/octet-stream"

        if 段类型 == "image":
            路径 = await 下载媒体文件(媒体地址, "image", 大小限制)
            return 路径, "image/jpeg"
        elif 段类型 == "record":
            路径 = await 下载媒体文件(媒体地址, "audio", 大小限制)
            return 路径, "audio/ogg"
        elif 段类型 == "video":
            路径 = await 下载媒体文件(媒体地址, "video", 大小限制)
            return 路径, "video/mp4"
        elif 段类型 == "file":
            logger.info(f"文件段: path={数据.get('path', '')} url={数据.get('url', '')} file_id={数据.get('file_id', '')}")
            路径 = await self._解析文件段路径(数据)
            return 路径, "application/octet-stream"

        return None, "application/octet-stream"

    async def _解析文件段路径(self, 数据: dict) -> Optional[str]:
        """从 file 消息段中解析出本地文件路径。

        优先级: path 字段 > file:// URL > file_id 调用 get_file API
        """
        # path 字段直接可用
        路径 = 数据.get("path", "")
        if 路径 and os.path.isfile(路径):
            return 路径

        # file:// URL
        地址 = 数据.get("url", "")
        if 地址.startswith("file://"):
            解析路径 = urllib.parse.urlparse(地址).path
            if os.path.isfile(解析路径):
                return 解析路径

        # 兜底: 用 file_id 调 get_file API
        for 候选ID in [数据.get("file_id", ""), 数据.get("file", "")]:
            if not 候选ID:
                continue
            try:
                if self._HTTP调用器:
                    文件信息 = await self._HTTP调用器.获取文件信息(候选ID)
                else:
                    文件信息 = await self.ws.获取文件(候选ID)
                if 文件信息.get("status") == "ok":
                    文件路径 = 文件信息.get("data", {}).get("file", "")
                    if 文件路径 and os.path.isfile(文件路径):
                        logger.info(f"get_file 解析成功: {文件路径}")
                        return 文件路径
            except Exception as e:
                logger.debug(f"get_file 失败 candidate={候选ID}: {e}")

        return None

    async def _解析回复消息(self, 消息段列表: list[dict]) -> tuple:
        """解析回复段，获取被回复消息的文本和媒体映射。

        返回: (被回复消息ID, 回复文本, 回复媒体映射)
        """
        回复段 = next((s for s in 消息段列表 if s.get("type") == "reply"), None)
        被回复ID = str(回复段.get("data", {}).get("id", "")) if 回复段 else ""

        if not 被回复ID:
            return None, None, {}

        回复文本 = None
        回复媒体映射: dict = {}

        try:
            被回复消息 = await self.ws.获取消息(被回复ID)
            if 被回复消息.get("status") == "ok":
                原始段列表 = 被回复消息.get("data", {}).get("message", [])
                if isinstance(原始段列表, list):
                    回复媒体映射 = await self._解析媒体附件(原始段列表)
                    回复文本 = 构建完整可读文本(原始段列表, 回复媒体映射)
                    # 截断引用文本（保留完整媒体标签）
                    if 回复文本 and len(回复文本) > self.引用文本最大字数:
                        回复文本 = 智能截断保留媒体标签(
                            回复文本, self.引用文本最大字数
                        )
                    logger.info(f"回复消息: ID={被回复ID} 文本={回复文本[:40] if 回复文本 else '(空)'}")
        except Exception as e:
            logger.debug(f"获取回复消息失败 {被回复ID}: {e}")

        return 被回复ID, 回复文本, 回复媒体映射

    @staticmethod
    def _收集媒体路径(
            媒体映射: dict, 回复媒体映射: dict, 回复ID: Optional[str]
    ) -> tuple[list[str], list[str]]:
        """从媒体映射中收集所有已下载的本地路径和 MIME 类型。"""
        媒体路径: list[str] = []
        媒体类型: list[str] = []

        for 信息 in 媒体映射.values():
            if 信息.get("本地路径"):
                媒体路径.append(信息["本地路径"])
                媒体类型.append(信息.get("MIME", "application/octet-stream"))

        if 回复ID:
            for 信息 in (回复媒体映射 or {}).values():
                if 信息.get("本地路径"):
                    媒体路径.append(信息["本地路径"])
                    媒体类型.append(信息.get("MIME", "application/octet-stream"))

        return 媒体路径, 媒体类型

    @staticmethod
    def _兜底文本(文本: str, 媒体路径: list[str], 媒体类型: list[str]) -> str:
        """当消息无文本时，根据媒体类型生成兜底文本。"""
        if 文本.strip() or not 媒体路径:
            return 文本
        if any(t.startswith("image/") for t in 媒体类型):
            return "[图片]"
        if any(t.startswith("audio/") for t in 媒体类型):
            return "[语音]"
        return "[文件]"

    @staticmethod
    def _推断消息分类(媒体类型: list[str]) -> MessageType:
        """根据媒体 MIME 类型推断 MessageEvent 分类。"""
        if not 媒体类型:
            return MessageType.TEXT
        if any(t.startswith(("application/", "text/")) for t in 媒体类型):
            return MessageType.DOCUMENT
        if any(t.startswith("audio/") for t in 媒体类型):
            return MessageType.AUDIO
        if any(t.startswith("image/") for t in 媒体类型):
            return MessageType.PHOTO
        return MessageType.TEXT

    # ── 后台任务 ──────────────────────────────────────────────────────

    def _消息回应(self, 消息类型: str, 消息ID: str, 用户ID: str):
        """启动表情回应后台任务，私聊戳一戳"""
        try:
            if 消息类型 == "group":
                表情ID = random.choice(表情回应ID列表)
                任务 = asyncio.create_task(self._表情回应(消息ID, 表情ID))
            else:
                任务 = asyncio.create_task(self._戳一戳(用户ID))
            self._后台任务集合.add(任务)
            任务.add_done_callback(self._后台任务集合.discard)
        except Exception as e:
            logger.debug(f"表情回应失败: {e}")

    async def _表情回应(self, 消息ID: str, 表情ID: int):
        """后台执行表情回应。"""
        try:
            结果 = await self.ws.设置表情回应(消息ID, 表情ID)
            if 结果.get("status") != "ok":
                logger.warning(f"表情回应失败: {结果}")
        except Exception as e:
            logger.warning(f"表情回应异常: {e}")

    async def _戳一戳(self, 用户ID: str):
        """后台执行戳一戳。"""
        try:
            结果 = await self.ws.戳一戳好友(用户ID)
            if 结果.get("status") != "ok":
                logger.warning(f"戳一戳失败: {结果}")
        except Exception as e:
            logger.warning(f"戳一戳异常: {e}")

    async def _获取群名称(self, 群ID: str):
        """异步获取群名称并缓存。"""
        if 群ID in self._群名缓存:
            return
        try:
            结果 = await self.ws.获取群信息(群ID)
            名称 = 结果.get("data", {}).get("group_name", "")
            if 名称:
                self._群名缓存.设置(群ID, 名称)
                logger.debug(f"群名: {群ID} → {名称}")
        except Exception as e:
            logger.debug(f"获取群名失败 {群ID}: {e}")

    # ═══════════════════════════════════════════════════════════════════════════════
    # 投递目标解析（发送链路辅助）
    # ═══════════════════════════════════════════════════════════════════════════════

    def _解析投递目标(self, 会话ID: str) -> tuple[Optional[str], str]:
        """根据会话ID解析出 (消息类型, 目标ID)。

        解析优先级：
          1. 缓存（来自接收链路记录的投递信息）
          2. napcat_group_<群ID> / napcat_private_<用户ID> 格式
          3. 纯数字 → 从缓存推断类型，查不到则报错

        失败时返回 (None, 错误信息)。
        """
        # 先查缓存
        投递信息 = self._投递信息缓存.获取(会话ID, {})
        消息类型 = 投递信息.get("消息类型", "")
        目标ID = 投递信息.get("目标ID", "")

        if 目标ID and 消息类型:
            return 消息类型, str(目标ID)

        # 解析格式
        if 会话ID.startswith("napcat_group_"):
            目标ID = 会话ID.removeprefix("napcat_group_")
            消息类型 = "group"
        elif 会话ID.startswith("napcat_private_"):
            目标ID = 会话ID.removeprefix("napcat_private_")
            消息类型 = "private"
        elif 会话ID.lstrip("-").isdigit():
            # 纯数字：从缓存推断类型
            目标ID = 会话ID
            消息类型 = ""
            for 前缀 in (f"napcat_group_{会话ID}", f"napcat_private_{会话ID}"):
                信息 = self._投递信息缓存.获取(前缀, {})
                if 信息.get("目标ID"):
                    消息类型 = 信息["消息类型"]
                    break
            if not 消息类型:
                return None, (
                    f"无法推断「{会话ID}」的类型（群聊/私聊）。"
                    "请先与该会话交互，或使用 napcat_group_{会话ID} / napcat_private_{会话ID} 格式"
                )
        else:
            return None, (
                f"无效的会话ID格式: 「{会话ID}」"
                "群聊用 napcat_group_<群ID>，私聊用 napcat_private_<用户ID>"
            )

        if not 目标ID:
            return None, f"会话ID中目标ID为空「{会话ID}」"

        return 消息类型, str(目标ID)

    # ═══════════════════════════════════════════════════════════════════════════════
    # 发送方法（发送链路）
    # ═══════════════════════════════════════════════════════════════════════════════

    async def send(self, chat_id: str, content: str = "", **kwargs) -> SendResult:
        """发送文本消息。

        链路: CQ码检测 → 获取投递目标 → 长消息处理(合并转发/拆分) → WS/HTTP发送

        支持 ```CQ ... ``` 代码块直接发送 CQ 码。
        长消息自动拆分或合并转发。
        """
        if not self.ws:
            return SendResult(success=False, error="客户端未初始化")

        回复目标 = kwargs.get("reply_to")
        回复CQ前缀 = f"[CQ:reply,id={回复目标}]" if 回复目标 else ""
        logger.info(f"▶ 发送: 会话={chat_id} 长度={len(content)} 预览={content[:20] if content else '非文本'}")

        内容 = content.strip()

        # ── CQ 码块检测 (```CQ ... ```) ──
        if 内容.startswith("```CQ") and 内容.endswith("```"):
            return await self._发送CQ码块(chat_id, 内容, 回复CQ前缀)

        # ── 长消息处理 ──
        if len(content) > self.合并转发阈值:
            消息类型, 目标ID = self._解析投递目标(chat_id)
            if 消息类型 is None:
                return SendResult(success=False, error=目标ID)

            # 群聊超过阈值 → 优先合并转发
            if 消息类型 == "group":
                转发结果 = await self._发送合并转发(chat_id, content, 回复目标)
                if 转发结果:
                    logger.info(f"✓ 合并转发成功 (阈值={self.合并转发阈值})")
                    return 转发结果
                logger.info("合并转发失败，回退到拆分发送")

        # ── 超长消息拆分发送 ──
        if len(content) > 消息最大长度:
            return await self._发送拆分消息(chat_id, content, 回复目标)

        # ── 普通消息（统一用 CQ 码字符串发送）──
        return await self._发送普通消息(chat_id, content, 回复CQ前缀)

    async def _发送CQ码块(
        self, chat_id: str, 内容: str, 回复CQ前缀: str
    ) -> SendResult:
        """发送 ```CQ ... ``` 代码块中的 CQ 码。"""
        CQ文本 = 内容[len("```CQ"):].rsplit("```", 1)[0].strip()
        if not CQ文本:
            return SendResult(success=False, error="CQ码块内容为空")
        if 回复CQ前缀:
            CQ文本 = 回复CQ前缀 + CQ文本
        logger.info(f"CQ码: {CQ文本[:80]}")

        消息类型, 目标ID = self._解析投递目标(chat_id)
        if 消息类型 is None:
            return SendResult(success=False, error=目标ID)

        return await self._执行发送(chat_id, 消息类型, 目标ID, CQ文本)

    async def _发送合并转发(
        self, 会话ID: str, 内容: str, 回复目标: Optional[str]
    ) -> Optional[SendResult]:
        """尝试以合并转发方式发送长内容。

        如果内容中包含 CQ 码，先将其全部提取拼成一条普通消息单独发送，
        然后只把纯文本部分走合并转发。
        失败时返回 None，调用方回退到拆分发送。
        """
        消息类型, 目标ID = self._解析投递目标(会话ID)
        if 消息类型 is None:
            return None

        # ── 提取 CQ 码，单独作为一条普通消息发送 ──
        片段列表 = 拆分CQ码与纯文本(内容)
        CQ码列表 = [片段 for 类型, 片段 in 片段列表 if 类型 == "cq"]
        纯文本部分 = "".join(片段 for 类型, 片段 in 片段列表 if 类型 == "text")

        if CQ码列表:
            CQ消息 = "".join(CQ码列表)
            logger.info(f"CQ码单独发送: {CQ消息[:80]}")
            try:
                await self._执行发送(会话ID, 消息类型, 目标ID, CQ消息)
            except Exception as e:
                logger.error(f"CQ码发送失败: {e}")

        # ── 没有纯文本了，不需要合并转发 ──
        if not 纯文本部分.strip():
            return SendResult(success=True)

        # ── 纯文本走合并转发 ──
        节点列表 = self._构建合并转发节点(纯文本部分, 回复目标)

        try:
            if 消息类型 == "group":
                结果 = await self.ws.发送群合并转发(目标ID, 节点列表)
            else:
                结果 = await self.ws.发送私聊合并转发(目标ID, 节点列表)

            if 结果.get("status") == "ok" or 结果.get("retcode", -1) == 0:
                return SendResult(success=True)
            logger.debug(f"合并转发失败 (retcode={结果.get('retcode')}), 回退到拆分")
            return None
        except Exception as e:
            logger.debug(f"合并转发异常: {e}, 回退到拆分")
            return None

    def _构建合并转发节点(
        self, 纯文本: str, 回复目标: Optional[str]
    ) -> list[dict]:
        """构建合并转发节点列表。"""
        节点列表: list[dict] = []
        if 回复目标:
            节点列表.append({"type": "node", "data": {"id": int(回复目标)}})

        机器人ID = self.机器人QQ号 or "0"
        节点列表.append({
            "type": "node",
            "data": {
                "uin": int(机器人ID),
                "name": self.合并转发昵称,
                "content": [构建文本段(纯文本)],
            },
        })
        return 节点列表

    async def _发送拆分消息(
        self, chat_id: str, content: str, 回复目标: Optional[str]
    ) -> SendResult:
        """超长消息拆分发送，在段落/句子边界处拆分。"""
        段落列表 = 拆分长文本(content)
        logger.info(f"拆分为 {len(段落列表)} 段")

        for 段索引, 段落 in enumerate(段落列表):
            消息段 = 构建消息段数组(段落, 回复目标=回复目标)
            if not 消息段:
                continue
            try:
                消息类型, 目标ID = self._解析投递目标(chat_id)
                if 消息类型 is None:
                    return SendResult(success=False, error=目标ID)
                if 消息类型 == "group":
                    结果 = await self.ws.发送群聊消息(目标ID, 消息段)
                else:
                    结果 = await self.ws.发送私聊消息(目标ID, 消息段)
                if 结果.get("status") == "failed" or 结果.get("retcode", 0) != 0:
                    错误 = 结果.get("wording") or 结果.get("msg") or "未知错误"
                    logger.error(f"段{段索引 + 1}/{len(段落列表)} 发送失败: {错误}")
                    return SendResult(success=False, error=f"段{段索引+1}发送失败: {错误}")
                logger.info(f"段{段索引 + 1}/{len(段落列表)} 发送完成")
            except Exception as e:
                logger.error(f"段{段索引+1}发送异常: {e}")
                return SendResult(success=False, error=str(e))
            回复目标 = None  # 只有第一段带回复

        return SendResult(success=True)

    async def _发送普通消息(
        self, chat_id: str, content: str, 回复CQ前缀: str
    ) -> SendResult:
        """发送普通文本消息（CQ 码字符串格式）。"""
        CQ文本 = 回复CQ前缀 + 文本转CQ码字符串(content)
        if not CQ文本.strip():
            return SendResult(success=False, error="消息为空")

        消息类型, 目标ID = self._解析投递目标(chat_id)
        if 消息类型 is None:
            return SendResult(success=False, error=目标ID)

        return await self._执行发送(chat_id, 消息类型, 目标ID, CQ文本)

    async def _执行发送(
        self, chat_id: str, 消息类型: str, 目标ID: str, 消息内容: str
    ) -> SendResult:
        """执行 WS 发送并处理结果。"""
        logger.info(f"→ {消息类型}:{目标ID}")
        try:
            if 消息类型 == "group":
                结果 = await self.ws.发送群聊消息(目标ID, 消息内容)
            else:
                结果 = await self.ws.发送私聊消息(目标ID, 消息内容)

            if 结果.get("status") == "failed" or 结果.get("retcode", 0) != 0:
                错误 = (
                    结果.get("wording")
                    or 结果.get("message")
                    or 结果.get("msg")
                    or "未知错误"
                )
                logger.error(f"✗ 发送失败: {错误}")
                return SendResult(success=False, error=f"OneBot API 错误: {错误}")

            logger.info("✓ 发送成功")
            return SendResult(success=True)
        except Exception as e:
            logger.error(f"✗ 发送异常: {e}")
            return SendResult(success=False, error=str(e))

    # ── 其他发送方法 ──────────────────────────────────────────────────

    async def send_image(
        self,
        chat_id: str,
        image_url: str,
        caption: Optional[str] = None,
        reply_to: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> SendResult:
        """发送图片 (URL)。"""
        if not image_url or not image_url.strip():
            return SendResult(success=False, error="图片URL为空")
        if not self.ws:
            return SendResult(success=False, error="客户端未初始化")

        CQ文本 = ""
        if caption and caption.strip():
            CQ文本 = caption
        CQ文本 += f"[CQ:image,file={image_url}]"

        消息类型, 目标ID = self._解析投递目标(chat_id)
        if 消息类型 is None:
            return SendResult(success=False, error=目标ID)

        return await self._执行发送(chat_id, 消息类型, 目标ID, CQ文本)

    async def send_image_file(
        self, chat_id: str, image_path: str, caption: str = "", **kwargs
    ) -> SendResult:
        """发送本地图片文件。

        优先用 HTTP API（反向 WS 下图片消息不返回 echo，会导致 60s 超时）。
        """
        if not image_path or not os.path.isfile(image_path):
            return SendResult(success=False, error=f"图片文件不存在: {image_path}")

        # caption 先单独发送
        if caption and caption.strip():
            try:
                await self.send(chat_id, caption)
            except Exception as e:
                logger.warning(f"图片caption发送失败: {e}")

        回复目标 = kwargs.get("reply_to")
        CQ文本 = ""
        if 回复目标:
            CQ文本 = f"[CQ:reply,id={回复目标}]"
        CQ文本 += f"[CQ:image,file=file:///{image_path.lstrip('/')}]"

        消息类型, 目标ID = self._解析投递目标(chat_id)
        if 消息类型 is None:
            return SendResult(success=False, error=目标ID)
        logger.info(f"发送图片: {image_path} → {消息类型}:{目标ID}")

        # 优先 HTTP API
        if self._HTTP调用器:
            try:
                if 消息类型 == "group":
                    结果 = await self._HTTP调用器.发送群聊消息(目标ID, CQ文本)
                else:
                    结果 = await self._HTTP调用器.发送私聊消息(目标ID, CQ文本)
                返回码 = 结果.get("retcode", -1)
                if 返回码 in (0, 200):
                    if 返回码 == 200:
                        logger.info("图片发送 retcode=200 (调用超时但可能已送达)")
                    return SendResult(success=True)
                错误 = 结果.get("message", "") or 结果.get("wording", "") or 结果.get("msg", "")
                return SendResult(success=False, error=错误 or f"retcode={返回码}")
            except Exception as e:
                logger.warning(f"HTTP图片发送失败，回退WS: {e}")

        # WS 回退
        if not self.ws:
            return SendResult(success=False, error="客户端未初始化")

        try:
            if 消息类型 == "group":
                结果 = await self.ws.发送群聊消息(目标ID, CQ文本)
            else:
                结果 = await self.ws.发送私聊消息(目标ID, CQ文本)

            if 结果.get("status") == "failed" or 结果.get("retcode", 0) != 0:
                错误 = (
                    结果.get("wording")
                    or 结果.get("message")
                    or 结果.get("msg")
                    or "未知错误"
                )
                if "timeout" in 错误.lower():
                    logger.info("WS图片超时 — 可能已送达")
                    return SendResult(success=True)
                return SendResult(success=False, error=错误)
            return SendResult(success=True)
        except Exception as e:
            return SendResult(success=False, error=str(e))

    async def send_typing(self, chat_id: str, metadata=None) -> None:
        """QQ 不支持打字指示，空实现。"""
        pass

    async def get_chat_info(self, chat_id: str) -> dict:
        """获取会话信息。"""
        if chat_id.startswith("napcat_group_"):
            群ID = chat_id.removeprefix("napcat_group_")
            名称 = self._群名缓存.获取(群ID, f"QQ群{群ID}")
            return {"name": 名称, "type": "group", "chat_id": chat_id}
        if chat_id.startswith("napcat_private_"):
            用户ID = chat_id.removeprefix("napcat_private_")
            名称 = self._用户名缓存.获取(用户ID, f"QQ用户{用户ID}")
            return {"name": 名称, "type": "private", "chat_id": chat_id}
        return {"name": chat_id, "type": "unknown", "chat_id": chat_id}

    async def send_voice(
        self, chat_id: str, audio_path: str,
        reply_to: Optional[str] = None, **kwargs
    ) -> SendResult:
        """发送语音文件。"""
        if not audio_path or not os.path.isfile(audio_path):
            return SendResult(success=False, error=f"语音文件不存在: {audio_path}")
        if not self.ws:
            return SendResult(success=False, error="客户端未就绪")

        CQ文本 = ""
        if reply_to:
            CQ文本 = f"[CQ:reply,id={reply_to}]"
        CQ文本 += f"[CQ:record,file=file:///{audio_path.lstrip('/')}]"

        消息类型, 目标ID = self._解析投递目标(chat_id)
        if 消息类型 is None:
            return SendResult(success=False, error=目标ID)

        try:
            if 消息类型 == "group":
                结果 = await self.ws.发送群聊消息(目标ID, CQ文本)
            else:
                结果 = await self.ws.发送私聊消息(目标ID, CQ文本)

            if 结果.get("status") == "failed" or 结果.get("retcode", 0) != 0:
                错误 = 结果.get("wording") or 结果.get("message") or 结果.get("msg") or "未知错误"
                return SendResult(success=False, error=f"语音发送失败: {错误}", raw_response=结果)
            return SendResult(success=True)
        except Exception as e:
            return SendResult(success=False, error=str(e))

    async def send_document(
        self, chat_id: str, file_path: str = "", caption: str = "", **kwargs
    ) -> SendResult:
        """发送文件（上传到群文件/私聊文件）。"""
        路径 = file_path or kwargs.get("path", "")
        if not self.ws:
            return SendResult(success=False, error="客户端未就绪")
        if not 路径 or not os.path.isfile(路径):
            return SendResult(success=False, error=f"文件不存在: {路径}")

        消息类型, 目标ID = self._解析投递目标(chat_id)
        if 消息类型 is None:
            return SendResult(success=False, error=目标ID)

        # caption 先单独发送
        if caption and caption.strip():
            try:
                if 消息类型 == "group":
                    await self.ws.发送群聊消息(目标ID, caption)
                else:
                    await self.ws.发送私聊消息(目标ID, caption)
            except Exception as e:
                logger.warning(f"文件caption发送失败: {e}")

        try:
            if 消息类型 == "group":
                结果 = await self.ws.上传群文件(目标ID, 路径)
            else:
                结果 = await self.ws.上传私聊文件(目标ID, 路径)

            if 结果.get("status") == "failed" or 结果.get("retcode", 0) != 0:
                错误 = 结果.get("wording") or 结果.get("msg") or "上传失败"
                return SendResult(success=False, error=错误)
            return SendResult(success=True)
        except Exception as e:
            return SendResult(success=False, error=str(e))
