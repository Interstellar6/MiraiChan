import json
import os
import random
import time
from io import StringIO
from typing import Any, TypedDict

import yaml
from melobot.bot import get_bot
from melobot.bot.base import Bot, BotLifeSpan
from melobot.handle.register import on_command, on_event
from melobot.log.base import GenericLogger
from melobot.plugin.base import PluginPlanner
from melobot.protocols.onebot.v11.adapter.base import Adapter
from melobot.protocols.onebot.v11.adapter.event import (
    GroupMessageEvent,
    GroupRecallNoticeEvent,
    MessageEvent,
)
from melobot.protocols.onebot.v11.adapter.segment import (
    ImageSegment,
    JsonSegment,
    ReplySegment,
    TextSegment,
    XmlSegment,
)
from melobot.typ import BetterABC
from melobot.utils.parse.cmd import CmdArgs

import checker_factory
import little_helper
from extended_actions.lagrange import MfaceSegment
from lemony_utils.botutils import get_reply
from lemony_utils.images import text_to_imgseg

REBOOT_INFO_PATH = "data/reboot_info.json"

bot = get_bot()
LemonyUtils = PluginPlanner("0.1.0")
little_helper.register(
    "LemonyUtils",
    {
        "cmd": ".echo",
        "text": "复读回复的消息\n*Owner Only*",
    },
    {
        "cmd": ".{getmsg,get} [--text]",
        "text": "获取回复的消息的数据\n*Owner Only*",
    },
    {
        "cmd": ".withdraw",
        "text": "尝试撤回回复的消息\n*Owner Only*",
    },
    {
        "cmd": ".{reboot,restart,重启}",
        "text": "重启Bot程序\n*Owner Only*",
    },
    {
        "cmd": ".{poweroff,shutdown,关机}",
        "text": "关闭Bot程序\n*Owner Only*",
    },
    {
        "cmd": ".{早安,checkin,签到}",
        "text": "一键签到\n*Owner Only*",
    },
)


@LemonyUtils.use
@on_command(".", " ", "echo")
async def echo(adapter: Adapter, event: MessageEvent):
    try:
        msg = await get_reply(adapter, event)
    except get_reply.GetReplyException:
        await adapter.send_reply("获取消息失败")
        return
    await adapter.send(
        [
            seg
            for seg in msg.data["message"]  # type: ignore
            if not isinstance(seg, (JsonSegment, XmlSegment))
        ]
    )


@LemonyUtils.use
@on_command(
    ".",
    " ",
    ["getface"],
    # checker=checker_factory.get_owner_checker(),
)
async def getface(
    adapter: Adapter,
    event: MessageEvent,
    logger: GenericLogger,
    args: CmdArgs,
):
    try:
        msg = await get_reply(adapter, event)
        if not msg.data:
            raise get_reply.EmptyResponseError()
    except get_reply.GetReplyException:
        await adapter.send_reply("获取消息失败")
        return
    mface: MfaceSegment | None = None

    for seg in msg.data["message"]:
        if seg.type == "mface":
            mface = MfaceSegment(**seg.data)
            break
    else:
        await adapter.send_reply("消息中没有表情")
        return
    info = StringIO()
    yaml.dump(mface.data, info, allow_unicode=True)
    await adapter.send_reply(
        [ImageSegment(file=mface.data["url"]), TextSegment(info.getvalue())]
    )


@LemonyUtils.use
@on_command(
    ".",
    " ",
    ["get", "getmsg"],
    checker=checker_factory.get_owner_checker(),
)
async def getmsg(
    adapter: Adapter,
    event: MessageEvent,
    logger: GenericLogger,
    args: CmdArgs,
):
    try:
        msg = await get_reply(adapter, event)
    except get_reply.GetReplyException:
        await adapter.send_reply("获取消息失败")
        return
    msgdata: dict[str, Any] = msg.raw.get("data", {})
    msgdata.pop("raw_message", None)
    segs: list[dict[str, Any]] = []
    for i, seg in enumerate(msgdata.pop("message", [])):
        segs.append(seg.copy())
        try:
            if seg["type"] == "json":
                segs[i]["data"]["data"] = json.loads(seg["data"]["data"])
        except Exception:
            pass
    msgdata["message"] = segs

    logger.debug(f"get seg: {msg}")
    if args.vals and args.vals[0] == "--text":
        await adapter.send_reply(json.dumps(msgdata, indent=2, ensure_ascii=False))
    else:
        await adapter.send_reply(
            await text_to_imgseg(json.dumps(msgdata, indent=2, ensure_ascii=False))
        )


@LemonyUtils.use
@on_command(".", " ", "withdraw", checker=checker_factory.get_owner_checker())
async def withdraw(event: MessageEvent, adapter: Adapter):
    msg = event.get_segments(ReplySegment)
    if not msg:
        await adapter.send_reply("需要指定尝试撤回的消息")
        return
    await adapter.delete_msg(msg[0].data["id"])


SAYINGS_ON_POWEROFF = [
    "下班啦~",
    "拜拜~",
    "再见~",
]
SAYINGS_ON_REBOOT = [
    "待会儿见w",
    "正在执行重启, 请坐和放宽w",
]


@LemonyUtils.use
@on_command(
    ".",
    " ",
    ["关机", "shutdown", "poweroff"],
    checker=checker_factory.get_owner_checker(),
)
async def stop_bot(adapter: Adapter, bot: Bot) -> None:
    await (await adapter.send(random.choice(SAYINGS_ON_POWEROFF)))[0]
    await bot.close()


class RebootInfo(TypedDict):
    time: float
    uid: int
    gid: int | None


@LemonyUtils.use
@on_command(
    ".",
    " ",
    ["重启", "restart", "reboot"],
    checker=checker_factory.get_owner_checker(),
)
async def restart_bot(event: MessageEvent, adapter: Adapter, bot: Bot):
    if not bot.is_restartable():
        await adapter.send_reply("当前启动方式不支持重启w")
        return
    await (await adapter.send(random.choice(SAYINGS_ON_REBOOT)))[0]
    reboot_info: RebootInfo = {
        "gid": event.group_id if isinstance(event, GroupMessageEvent) else None,
        "uid": event.user_id,
        "time": time.time(),
    }
    with open(REBOOT_INFO_PATH, "w+", encoding="utf-8") as fp:
        json.dump(reboot_info, fp)
    await bot.restart()


@bot.on_started
async def startup_check(adapter: Adapter):
    if not os.path.isfile(REBOOT_INFO_PATH):
        return
    try:
        with open(REBOOT_INFO_PATH, "r", encoding="utf-8") as fp:
            info: RebootInfo = json.load(fp)
        start_time = bot._hook_bus.get_evoke_time(BotLifeSpan.STARTED)
        interval = (start_time if start_time > 0 else time.time()) - info["time"]
        await adapter.send_custom(
            f"重启已完成, 耗时 {interval:.3f}s", info["uid"], info["gid"]
        )
    finally:
        os.remove(REBOOT_INFO_PATH)


@on_event()
async def auto_withdraw_reply(adapter: Adapter, event: GroupRecallNoticeEvent):
    raise NotImplementedError

@LemonyUtils.use
@on_command(
    ".",
    " ",
    ["早安", "签到", "checkin"],
    checker=checker_factory.get_owner_checker(),
)
async def checkin(adapter: Adapter, event: MessageEvent):
    SAYINGS_ON_CHECKIN = [
        "~今日运势",
        "~吃什么",
        ".waifu",
        ".今日人设",
        ".今天听什么",
        "🦌",
    ]
    for i in SAYINGS_ON_CHECKIN:
        await adapter.send_reply(i)
