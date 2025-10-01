import asyncio
import functools
import os
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated

from melobot import get_logger, send_text
from melobot.di import Reflect
from melobot.handle import on_command
from melobot.plugin import PluginPlanner
from melobot.protocols.onebot.v11.adapter import Adapter
from melobot.protocols.onebot.v11.adapter.event import GroupMessageEvent, MessageEvent
from melobot.protocols.onebot.v11.adapter.segment import ReplySegment, TextSegment
from melobot.session import Rule, enter_session, suspend
from melobot.utils import singleton, unfold_ctx
from pydantic import BaseModel
from sqlmodel import col, select

import checker_factory
import little_helper
from configloader import ConfigLoader, ConfigLoaderMetadata
from lemony_utils.botutils import auto_report_traceback, get_reply
from recorder_models import Message

from .. import Recorder
from .core import SummaryCore, SummaryConfig, extract_text_from_segments
from .params import SummaryConfig as SummaryConfigModel

logger = get_logger()

little_helper.register(
	"GroupMsgSummary",
	{
		"cmd": r".summary [\d] [[\d, \d]] [sender_?only]",
		"text": "生成群聊会话摘要。"
		        "\n使用数字N表示对最近N条消息生成摘要。"
		        "\n使用区间[Start,End]表示对指定范围内的消息生成摘要。"
		        "\n添加 'sender_only' flag 将摘要限制为仅指定发送者的消息。",
	},
)

# 配置加载
cfgloader = ConfigLoader(
	ConfigLoaderMetadata(model=SummaryConfigModel, filename="summary_conf.json")
)
cfgloader.load_config()

summary_core = SummaryCore(cfgloader.config)

plugin = PluginPlanner("0.1.0")


@singleton
class _GetReplyIdWithCache:
	reply_relation_cache: dict[int, int] = {}

	@classmethod
	def _get_reply_id(cls, event: MessageEvent) -> int:
		if event.message_id in cls.reply_relation_cache:
			return cls.reply_relation_cache[event.message_id]
		if _ := event.get_segments(ReplySegment):
			msg_id = _[0].data["id"]
		else:
			raise get_reply.TargetNotSpecifiedError()
		cls.reply_relation_cache[event.message_id] = msg_id
		return msg_id

	def __call__(self, event: MessageEvent):
		return self._get_reply_id(event)


get_reply_msg_id = _GetReplyIdWithCache()


@dataclass(frozen=True)
class MsgFromDB:
	msg_id: int
	sender_id: int
	sender_name: str


async def get_reply_from_db(event: GroupMessageEvent):
	msg_id = get_reply_msg_id(event)
	async with Recorder.database.get_session() as sess:
		msg = (
			await sess.exec(
				select(Message)
				.where(Message.message_id == msg_id, Message.group_id == event.group_id)
				.order_by(col(Message.timestamp).desc())
			)
		).first()
		if msg:
			result = MsgFromDB(
				msg_id=msg_id,
				sender_id=msg.sender_id,
				sender_name=(await msg.awaitable_attrs.sender).name
				            or str(msg.sender_id),
			)
			logger.debug(f"Got reply record form db: {result!r}")
			return result


def extract_summary_params(event: GroupMessageEvent):
	"""提取摘要参数"""
	params = event.text.strip()

	# 解析数字N（最近N条消息）
	count = None
	if match := re.search(r"^\s*(\d+)\s*", params):
		count = int(match.group(1))
		params = params[match.end():]

	# 解析区间[Start,End]
	start, end = None, None
	if match := re.search(r"\[\s*(\d+)\s*\,\s*(\d+)\s*\]", params, re.IGNORECASE):
		start, end = map(int, match.group(1, 2))
		params = params.replace(match.group(), "")

	# 解析sender_only标志
	sender_only = bool(re.search(r"sender[\s_\-]only", params, re.IGNORECASE))

	return count, (start, end), sender_only


class SameSummaryRule(Rule[GroupMessageEvent]):
	async def compare(self, e1, e2):
		try:
			r1, r2 = get_reply_msg_id(e1), get_reply_msg_id(e2)
		except get_reply.GetReplyException:
			return False
		c1, rng1, so1 = extract_summary_params(e1)
		c2, rng2, so2 = extract_summary_params(e2)
		return (r1, c1, rng1, so1) == (r2, c2, rng2, so2)


rule = SameSummaryRule()


@plugin.use
@on_command(
	".",
	" ",
	["summary"],
	decos=[
		auto_report_traceback,
		unfold_ctx(
			lambda: enter_session(
				rule, wait=False, nowait_cb=lambda: send_text("GroupMsgSummary 正忙, 请稍等")
			)
		),
	],
)
async def generate_summary(
	adapter: Annotated[Adapter, Reflect()],
	event: Annotated[GroupMessageEvent, Reflect()],
):
	"""生成会话摘要"""
	if not Recorder.database.started.is_set():
		await adapter.send_reply("数据库还未就绪")
		return

	# 解析参数
	count, (start, end), sender_only = extract_summary_params(event)

	# 参数验证
	if count is None and (start is None or end is None):
		await adapter.send_reply("请指定消息范围：使用数字N（最近N条）或区间[Start,End]")
		return

	if count is not None and count <= 0:
		await adapter.send_reply("消息数量必须为正数")
		return

	if start is not None and end is not None:
		if start < 0 or end < 0:
			await adapter.send_reply("区间索引必须为非负数")
			return
		if start > end:
			await adapter.send_reply("区间起始索引不能大于结束索引")
			return

	# 获取基准消息（用于sender_only）
	base_sender_id = None
	if sender_only:
		try:
			target = await get_reply_from_db(event)
			if not target:
				echo = await get_reply(adapter, event)
				target = MsgFromDB(
					msg_id=echo.data["message_id"],
					sender_id=echo.data["sender"].user_id,
					sender_name=echo.data["sender"].nickname,
				)
			base_sender_id = target.sender_id
		except get_reply.GetReplyException:
			await adapter.send_reply("需要指定基准消息以使用sender_only功能")
			return

	# 生成摘要
	await adapter.send_reply("正在生成会话摘要，请稍候...")

	try:
		# 准备摘要数据
		data, resources = await summary_core.prepare_summary_data(
			base_msgid=0,  # 对于summary，不需要基准消息ID
			group_id=event.group_id,
			sender_id=base_sender_id,
			count=count,
			start=start or 0,
			end=end or 0,
			sender_only=sender_only
		)

		if not data:
			await adapter.send_reply("没有找到符合条件的消息")
			return

		# 生成摘要
		summary_result = await summary_core.generate_summary(data)

		# 发送摘要结果
		await adapter.send(
			TextSegment(f"💬 会话摘要：\n\n{summary_result}")
		)

		logger.info(f"Generated summary for group {event.group_id}: {len(data['conversation'])} messages")

	except Exception as e:
		logger.error(f"Failed to generate summary: {e}")
		await adapter.send_reply(f"生成摘要时发生错误: {str(e)}")

	# 频率限制
	completime = time.perf_counter()
	gap = 0
	while True:
		if (wait_time := (60 - gap)) <= 0:  # 1分钟限制
			return
		if not await suspend(wait_time):
			return
		gap = time.perf_counter() - completime
		await adapter.send_reply("生成摘要过于频繁, 请稍候再试")