from typing import Annotated

from melobot import send_text
from melobot.di import Reflect
from melobot.handle import on_command
from melobot.plugin import PluginPlanner
from melobot.protocols.onebot.v11.adapter import Adapter
from melobot.protocols.onebot.v11.adapter.event import GroupMessageEvent
from melobot.session import Rule, enter_session
from melobot.utils import unfold_ctx

plugin = PluginPlanner("0.1.0")

class SameReplyRule(Rule[GroupMessageEvent]):
    async def compare(self, e1, e2):
        return e1==e2


rule = SameReplyRule()


# 复现bug的核心代码
@plugin.use
@on_command(
    ".",
    " ",
    ["bug1"],
    decos=[
        unfold_ctx(
            lambda: enter_session(
                rule, wait=False, nowait_cb=lambda: send_text("bug 正忙, 请稍等")
            )
        ),
    ],
)
async def test_command(
    adapter: Annotated[Adapter, Reflect()],
    event: Annotated[GroupMessageEvent, Reflect()],
):
    """
    当使用Annotated类型注解时，框架会错误地进行类型检查。
    """
    # 以下代码实际上不会执行到，因为在依赖注入阶段就会抛出异常
    await adapter.send_reply(f"收到消息: {event.text}")
