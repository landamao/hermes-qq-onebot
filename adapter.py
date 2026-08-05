"""
NapCat QQ 适配器 — 注册到 Hermes 插件系统。
实际适配器实现在 main.py 中。
"""

import logging

logger = logging.getLogger(__name__)

# 运行时适配器实例引用（由 _创建适配器 工厂函数设置）
# 工具函数通过此引用直接复用适配器的 WS 连接 / HTTP 调用器 / 发送逻辑
_适配器实例 = None


def _检查依赖() -> bool:
    """检查运行时依赖是否可用。"""
    try:
        import websockets
        return True
    except ImportError:
        return False


def _验证配置(配置) -> bool:
    """检查 NapCat 是否正确配置。"""
    return 配置.enabled


def _是否已连接(配置) -> bool:
    """检查 NapCat 是否已连接/启用。"""
    return 配置.enabled


def _创建适配器(配置):
    """适配器工厂 — 创建实例时存一份引用供 LLM 工具复用。"""
    global _适配器实例
    from .main import NapCat适配器
    _适配器实例 = NapCat适配器(配置)
    return _适配器实例


def register(ctx):
    """插件入口 — 由 Hermes 插件系统调用。

    同时注册：
    1. 平台适配器（QQ 收发消息的网关适配器）
    2. LLM 工具（让 Agent 主动发消息、调用 OneBot API）
    """
    from .llm_tools import 工具列表, _检查可用

    # ── 注册平台适配器 ──
    ctx.register_platform(
        name="napcat",
        label="NapCat (QQ)",
        adapter_factory=_创建适配器,
        check_fn=_检查依赖,
        validate_config=_验证配置,
        is_connected=_是否已连接,
        required_env=[],
        install_hint="pip install websockets",
        # 用户授权环境变量
        allowed_users_env="NAPCAT_ALLOWED_USERS",
        allow_all_env="NAPCAT_ALLOW_ALL_USERS",
        # QQ 没有严格的消息长度限制
        max_message_length=0,
        # 显示
        emoji="🐱",
        # QQ 用户 ID 需要脱敏
        pii_safe=False,
        allow_update_command=True,
        # LLM 提示
        platform_hint=(
            "你正在通过 NapCat (QQ) 对话。"
            "支持文字、图片、语音、文件收发。回复保持简洁自然。"
            "\n\n【CQ码规则】发送图片/文件/语音/视频时必须用CQ码，"
            "格式：[CQ:image,file=/path/to/file]，直接写在消息文本中即可。"
        ),
    )

    # ── 注册 LLM 工具 ──
    for 工具名, schema, handler, emoji in 工具列表:
        ctx.register_tool(
            name=工具名,
            toolset="napcat",
            schema=schema,
            handler=handler,
            check_fn=_检查可用,
            is_async=True,
            emoji=emoji,
        )
