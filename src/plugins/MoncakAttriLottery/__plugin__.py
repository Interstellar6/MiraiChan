import os
import time

from pydantic import BaseModel

from melobot import get_logger
from melobot.plugin import PluginPlanner
from melobot.log import GenericLogger
from melobot.handle import on_command
from melobot.protocols.onebot.v11.adapter import Adapter
from melobot.protocols.onebot.v11.adapter.event import GroupMessageEvent

from configloader import ConfigLoader, ConfigLoaderMetadata
import checker_factory
import little_helper

from .lottery import MoonCakeLot

MoonCakeLottery = PluginPlanner("0.1.0")
little_helper.register(
    "MoonCakeLottery",
    {
        "cmd": ".啃月饼",
        "text": "抽取今日专属月饼\n各种神奇口味和效果等你发现！",
    },
)


class MoonCakeConfig(BaseModel):
    mooncake_data_file: str = "data/moncak_attrs.json"


os.makedirs("data", exist_ok=True)
cfgloader = ConfigLoader(
    ConfigLoaderMetadata(model=MoonCakeConfig, filename="moncak_conf.json")
)
cfgloader.load_config()
logger = get_logger()
mooncake_lot = MoonCakeLot(cfgloader.config.mooncake_data_file)
mooncake_cd_table: dict[int, str] = {}


@MoonCakeLottery.use
@on_command(".", " ", ["啃月饼", "月饼抽签"])
async def draw_mooncake(event: GroupMessageEvent, adapter: Adapter, logger: GenericLogger):
    if (
        mooncake_cd_table.get(event.sender.user_id, "")
        == (now_date := time.strftime("%Y-%m-%d", time.localtime()))
        and event.sender.user_id != checker_factory.OWNER
    ):
        await adapter.send_reply("今天已经啃过月饼啦，明天再来吧~")
        return
    mooncake_cd_table[event.sender.user_id] = now_date
    mooncake_attr = mooncake_lot.draw()
    logger.debug(f"{mooncake_attr=}")
    await adapter.send_reply(f"啊宝宝宝宝你刚刚吃了一个{mooncake_lot.to_text(mooncake_attr)}")