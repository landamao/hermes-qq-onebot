"""
NapCat 适配器通用工具函数与常量。

包含：
- 常量（消息长度、表情回应 ID 列表、下载限制）
- 简易 LRU 缓存
- 文件大小解析
- 媒体下载
- 消息段构建（OneBot v11 发送方向）
- CQ 码工具（拆分、转字符串）
- 消息解析（接收方向：纯文本提取、完整可读文本构建）
- 智能截断（保留完整媒体标签）
"""
__all__ = [
    # 常量
    "消息最大长度",
    "默认合并转发阈值",
    "默认引用文本最大字数",
    "表情回应ID列表",
    "默认下载限制",

    # 缓存类
    "简易LRU缓存",

    # 工具函数
    "解析文件大小",
    "下载媒体文件",

    # 消息段构建（发送方向）
    "构建文本段",
    "构建图片段",
    "构建语音段",
    "构建回复段",
    "构建艾特段",
    "构建文件段",
    "构建消息段数组",

    # CQ 码工具
    "文本转CQ码字符串",
    "拆分CQ码与纯文本",
    "拆分长文本",

    # 消息解析（接收方向）
    "从消息段提取纯文本",
    "构建完整可读文本",

    # 智能截断
    "智能截断保留媒体标签",

    # @检测
    "提取被艾特的QQ号",

    # 终端打印
    "打印",
]

import logging
import os
import re
import tempfile
import urllib.request
import urllib.parse
from collections import OrderedDict
from typing import Any, List, Optional

from gateway.platforms.base import cache_image_from_bytes

logger = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════════════════
# 常量
# ══════════════════════════════════════════════════════════════════════════

消息最大长度: int = 4500
默认合并转发阈值: int = 800
默认引用文本最大字数: int = 50

表情回应ID列表: list[int] = [66, 76, 124, 144, 147, 192, 201, 282, 297]

默认下载限制: dict[str, str] = {
    "image": "10MB",
    "record": "10MB",
    "video": "10MB",
    "file": "10MB",
}

logger = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════════════════
# 终端彩色打印（Hermes 默认 WARNING 级，info 用户看不到，重要信息同时 print）
# ══════════════════════════════════════════════════════════════════════════

_绿色 = "\033[32m"
_重置 = "\033[0m"


def 打印(消息: str) -> None:
    """绿色 print，不频繁的重要信息用（连接/断开/启动/异常）。"""
    print(f"{_绿色}[NapCat插件] {消息}{_重置}")


# ══════════════════════════════════════════════════════════════════════════
# 简易 LRU 缓存
# ══════════════════════════════════════════════════════════════════════════


class 简易LRU缓存:
    """轻量级 LRU 缓存，超过容量自动淘汰最久未用的条目。

    用 OrderedDict 实现，获取时移到末尾（最近使用），
    超容量时从头部弹出（最久未用）。
    """

    def __init__(self, 最大容量: int = 1000):
        self._缓存字典: OrderedDict[str, Any] = OrderedDict()
        self._最大容量 = 最大容量

    def 获取(self, 键: str, 默认值: Any = None) -> Any:
        """获取缓存值，同时将其标记为最近使用。"""
        if 键 in self._缓存字典:
            self._缓存字典.move_to_end(键)
            return self._缓存字典[键]
        return 默认值

    def 设置(self, 键: str, 值: Any) -> None:
        """设置缓存值，超过容量时淘汰最旧条目。"""
        if 键 in self._缓存字典:
            self._缓存字典.move_to_end(键)
        self._缓存字典[键] = 值
        if len(self._缓存字典) > self._最大容量:
            self._缓存字典.popitem(last=False)

    def 弹出(self, 键: str, 默认值: Any = None) -> Any:
        """弹出并返回指定键的值（删除条目）。"""
        return self._缓存字典.pop(键, 默认值)

    def __contains__(self, 键: str) -> bool:
        return 键 in self._缓存字典

    def __len__(self) -> int:
        return len(self._缓存字典)


# ══════════════════════════════════════════════════════════════════════════
# 文件大小解析
# ══════════════════════════════════════════════════════════════════════════

_单位倍率: dict[str, int] = {
    "B": 1, "K": 1024, "KB": 1024,
    "M": 1024 ** 2, "MB": 1024 ** 2,
    "G": 1024 ** 3, "GB": 1024 ** 3,
}
_单位正则 = re.compile(r'^(\d+\.?\d*)\s*([a-zA-Z]{1,3})$')


def 解析文件大小(原始值) -> int:
    """将带单位的文件大小字符串解析为字节数。

    支持: 1024, "10MB", "1.5GB", "500kb" 等。
    """
    if isinstance(原始值, (int, float)):
        return int(原始值)

    文本 = str(原始值).strip()
    if not 文本:
        return 0

    # 1. 尝试纯数字
    try:
        return int(float(文本))
    except ValueError:
        pass

    # 2. 尝试带单位匹配
    匹配 = _单位正则.match(文本)
    if not 匹配:
        raise ValueError(
            f"「{文本}」无法解析，支持的单位有：{'，'.join(_单位倍率.keys())}"
        )

    数字字符串 = 匹配.group(1)
    单位 = 匹配.group(2).upper()

    if 单位 not in _单位倍率:
        raise ValueError(
            f"「{文本}」不支持单位「{单位}」，支持的单位有：{'，'.join(_单位倍率.keys())}"
        )

    倍率 = _单位倍率[单位]
    return int(float(数字字符串) * 倍率)


# ══════════════════════════════════════════════════════════════════════════
# 媒体下载
# ══════════════════════════════════════════════════════════════════════════


async def 下载媒体文件(
    地址: str, 媒体类型: str = "image", 大小限制字节: int = 0
) -> Optional[str]:
    """下载媒体文件到本地临时目录。

    超过大小限制时不下载，返回 None。
    """
    import asyncio

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

    限制字节 = 大小限制字节 or (10 * 1024 * 1024)
    超时秒数 = 15 if 媒体类型 == "image" else 60

    def _同步下载() -> Optional[str]:
        try:
            # ── 第一步: HEAD 请求预检文件大小 ──
            try:
                头请求 = urllib.request.Request(地址, method="HEAD")
                with urllib.request.urlopen(头请求, timeout=10) as 头响应:
                    内容长度 = 头响应.getheader("Content-Length")
                    if 内容长度 and int(内容长度) > 限制字节:
                        logger.info(f"文件太大 ({内容长度} > {限制字节} bytes)，跳过下载")
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
                        logger.info(f"下载中超过限制 ({len(已下载)} > {限制字节} bytes)，中断")
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
            logger.warning(f"下载失败: {e}")
            return None

    try:
        return await asyncio.to_thread(_同步下载)
    except Exception as e:
        logger.warning(f"下载异常 {地址}: {e}")
        return None


# ══════════════════════════════════════════════════════════════════════════
# 消息段构建 (OneBot v11 格式，发送方向)
# ══════════════════════════════════════════════════════════════════════════


def 构建文本段(文本: str) -> dict:
    """构建文本消息段。"""
    return {"type": "text", "data": {"text": 文本}}


def 构建图片段(地址: str) -> dict:
    """构建图片消息段。"""
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
    """构建回复消息段。"""
    return {"type": "reply", "data": {"id": 消息ID}}


def 构建艾特段(QQ号: str) -> dict:
    """构建 @消息段。"""
    return {"type": "at", "data": {"qq": QQ号}}


def 构建文件段(地址: str) -> dict:
    """构建文件消息段。"""
    return {"type": "file", "data": {"file": 地址}}


def 构建消息段数组(
    文本: str,
    回复目标: Optional[str] = None,
    附件列表: Optional[List[dict]] = None,
) -> List[dict]:
    """构建 OneBot v11 消息数组（发送用）。

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


# ══════════════════════════════════════════════════════════════════════════
# CQ 码工具
# ══════════════════════════════════════════════════════════════════════════

CQ码正则 = re.compile(r'\[CQ:[^]]+]')


def 文本转CQ码字符串(文本: str, 附件列表: Optional[List[dict]] = None) -> str:
    """将文本和附件列表转换为 CQ 码字符串。

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


def 拆分CQ码与纯文本(内容: str) -> List[tuple]:
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


def 拆分长文本(文本: str, 最大长度: int = 1500) -> List[str]:
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


# ══════════════════════════════════════════════════════════════════════════
# 消息解析 (接收方向)
# ══════════════════════════════════════════════════════════════════════════


def 从消息段提取纯文本(消息段列表: list[dict]) -> str:
    """从消息段提取纯文本部分（text + at + face）。"""
    部分: list[str] = []
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


def _格式化媒体标签(标签名: str, 媒体信息: dict, 段数据: dict) -> str:
    """格式化图片/语音/视频媒体标签。"""
    本地路径 = 媒体信息.get("本地路径")
    if 本地路径:
        return f"[{标签名}:file={本地路径}]"
    原始URL = 媒体信息.get("原始URL") or 段数据.get("url", "")
    return f"[{标签名}:url={原始URL}]"


def _格式化文件标签(媒体信息: dict, 段数据: dict) -> str:
    """格式化文件标签，带文件名。"""
    文件名 = 段数据.get("file", "")
    本地路径 = 媒体信息.get("本地路径")
    if 本地路径:
        return f"[文件:name={文件名},file={本地路径}]"
    原始URL = 段数据.get("url", "") or 段数据.get("file", "")
    return f"[文件:name={文件名},url={原始URL}]"


def _追加详细艾特文本(片段列表: list[str], 数据: dict) -> None:
    """将 @ 段带 QQ 号详细信息追加到片段列表。"""
    QQ号 = 数据.get("qq", "")
    昵称 = 数据.get("name", "")
    if QQ号 == "all":
        片段列表.append("@全体成员")
    elif 昵称:
        片段列表.append(f"@{昵称}(QQ:{QQ号})")
    elif QQ号:
        片段列表.append(f"@{QQ号}")


def 构建完整可读文本(消息段列表: list[dict], 媒体信息映射: dict) -> str:
    """从消息段数组构建完整可读文本，每个媒体段都带详细标签。

    媒体标签格式：
      [图片:file=本地路径] 或 [图片:url=远程URL]
      [语音:file=本地路径] 或 [语音:url=远程URL]
      [视频:url=远程URL] 或 [视频:file=本地路径]
      [文件:name=xxx,file=本地路径] 或 [文件:name=xxx,url=远程URL]
      [表情:id=123]
    """
    文本片段: list[str] = []

    for 段索引, 段 in enumerate(消息段列表):
        段类型 = 段.get("type", "")
        数据 = 段.get("data", {})
        媒体信息 = 媒体信息映射.get(段索引, {})

        if 段类型 == "text":
            文本片段.append(数据.get("text", ""))
        elif 段类型 == "at":
            _追加详细艾特文本(文本片段, 数据)
        elif 段类型 == "face":
            表情ID = 数据.get("id", "")
            文本片段.append(f"[表情:id={表情ID}]")
        elif 段类型 == "image":
            文本片段.append(_格式化媒体标签("图片", 媒体信息, 数据))
        elif 段类型 == "record":
            文本片段.append(_格式化媒体标签("语音", 媒体信息, 数据))
        elif 段类型 == "video":
            文本片段.append(_格式化媒体标签("视频", 媒体信息, 数据))
        elif 段类型 == "file":
            文本片段.append(_格式化文件标签(媒体信息, 数据))
        # reply 段不输出文本，由调用方单独处理

    return "".join(文本片段).strip()


# ══════════════════════════════════════════════════════════════════════════
# 智能截断（保留完整媒体标签）
# ══════════════════════════════════════════════════════════════════════════

_媒体标签正则 = re.compile(r'\[(?:图片|语音|视频|文件|表情):[^]]*]')


def 智能截断保留媒体标签(文本: str, 最大字数: int) -> str:
    """按顺序截断到最大字数，如果截断点落在媒体标签内部则延伸到标签结尾。"""
    if len(文本) <= 最大字数:
        return 文本

    截断处 = 文本[:最大字数]
    # 检查截断处是否有未闭合的 [
    最后左括号 = 截断处.rfind("[")
    if 最后左括号 != -1:
        候选 = 文本[最后左括号:]
        匹配 = _媒体标签正则.match(候选)
        if 匹配:
            标签结束 = 最后左括号 + 匹配.end()
            return 文本[:标签结束] + "..."

    return 截断处 + "..."


# ══════════════════════════════════════════════════════════════════════════
# @ 检测
# ══════════════════════════════════════════════════════════════════════════


def 提取被艾特的QQ号(消息段列表: list[dict], 机器人QQ号: str) -> Optional[str]:
    """检查消息中是否 @了指定 QQ 号。"""
    for 段 in 消息段列表:
        if 段.get("type") == "at":
            QQ号 = 段.get("data", {}).get("qq", "")
            if str(QQ号) == 机器人QQ号:
                return str(QQ号)
    return None
