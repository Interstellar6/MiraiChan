from typing import Sequence

from melobot import  send_text, get_logger
from melobot.protocols.onebot.v11.adapter.event import MessageEvent
from melobot.protocols.onebot.v11 import on_message
import checker_factory
import little_helper
from melobot.handle import on_command
from melobot.plugin import PluginPlanner
from .. import AliasProvider

plugin = PluginPlanner("0.1.0")

logger = get_logger()

@plugin.use
@on_message()
async def unnmei_modify(event: MessageEvent):
    text = event.text
    print("#####################################\n" + text + "\n###############################")
    perfect_unnmei = """小Elaina为你逆天改命哦！
阁下的今日运势是：
太和（终极祥瑞）
★★★★★★★★
青龙盘柱文武彰，学术竞技破旧章
亥子异梦先祖指，迷津得解镇八方
财运(2)+姻缘(2)+事业(2)+人品(2)
仅供娱乐｜相信科学｜请勿迷信"""
    level = 2
    if text.count('今日运势') == 1 and text.count('★') <= level and text.count('☆') >= 7 - level:
        await send_text(perfect_unnmei)
