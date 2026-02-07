import asyncio
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated

import melobot
from melobot import get_logger, send_text
from melobot.di import Reflect
from melobot.handle import on_command
from melobot.plugin import PluginPlanner
from melobot.protocols.onebot.v11.adapter import Adapter
from melobot.protocols.onebot.v11.adapter.event import GroupMessageEvent, MessageEvent
from melobot.protocols.onebot.v11.adapter.segment import ReplySegment, TextSegment
from melobot.session import Rule, enter_session, suspend
from melobot.utils import singleton, unfold_ctx
from sqlmodel import col, select

import checker_factory
import little_helper
from configloader import ConfigLoader, ConfigLoaderMetadata
from lemony_utils.botutils import auto_report_traceback, get_reply
from recorder_models import Message

from .. import Recorder
from .core import SummaryCore
from .params import SummaryConfig as SummaryConfigModel

logger = get_logger()
melobot.set_traceback_style(hide_internal=False)

little_helper.register(
	"GroupMsgSummary",
	{
		"cmd": r".sum(?:mary)? \d+(?: --sender-only)?",
		"text": "生成群聊会话摘要。"
		        "\n使用 .sum M 或 .summary M 对最近M条消息生成摘要。"
		        "\n添加 --sender-only 标志将摘要限制为仅被引用消息发送者的消息。",
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
		from sqlalchemy.orm import joinedload

		msg = (
			await sess.exec(
				select(Message)
				.options(joinedload(Message.sender), joinedload(Message.segments))  # 主动加载关系
				.where(Message.message_id == msg_id, Message.group_id == event.group_id)
				.order_by(col(Message.timestamp).desc())
			)
		).first()
		if msg:
			result = MsgFromDB(
				msg_id=msg_id,
				sender_id=msg.sender_id,
				sender_name=(msg.sender.name if msg.sender else str(msg.sender_id)),  # 直接访问，不需要 awaitable_attrs
			)
			logger.debug(f"Got reply record form db: {result!r}")
			return result


def extract_summary_params(event: GroupMessageEvent):
	"""提取摘要参数 - 新格式: .sum M [--sender-only]"""
	params = event.text.strip()
	logger.debug(f"Raw params: {params}")

	# 解析数字M（最近M条消息）
	count = None
	# 使用更灵活的正则表达式匹配数字
	if match := re.search(r"(\d+)", params):
		count = int(match.group(1))
		logger.debug(f"Parsed count: {count}")

	# 解析--sender-only标志
	sender_only = bool(re.search(r"--sender-only", params, re.IGNORECASE))
	logger.debug(f"Sender only: {sender_only}")

	return count, sender_only


class SameSummaryRule(Rule[GroupMessageEvent]):
	async def compare(self, e1, e2):
		try:
			r1, r2 = get_reply_msg_id(e1), get_reply_msg_id(e2)
		except get_reply.GetReplyException:
			return False
		c1, so1 = extract_summary_params(e1)
		c2, so2 = extract_summary_params(e2)
		return (r1, c1, so1) == (r2, c2, so2)


rule = SameSummaryRule()


@plugin.use
@on_command(
	".",
	" ",
	["summary", "sum"],  # 保留两个别名
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
	count, sender_only = extract_summary_params(event)
	logger.debug(f"Final parsed params - count: {count}, sender_only: {sender_only}")

	# 参数验证
	if count is None:
		await adapter.send_reply("请指定消息数量：使用 .sum M 或 .summary M，其中M为要摘要的消息数量")
		return

	if count <= 0:
		await adapter.send_reply("消息数量必须为正整数")
		return

	# 限制最大消息数量
	if count > 100:
		await adapter.send_reply("消息数量过多，最多支持100条消息的摘要")
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
			logger.debug(f"Using sender_only mode for user {base_sender_id}")
		except get_reply.GetReplyException:
			await adapter.send_reply("使用 --sender-only 时需要回复一条消息以确定发送者")
			return

	# 生成摘要
	await adapter.send_reply(f"正在对最近 {count} 条消息生成会话摘要，请稍候..." +
	                         (" (仅限被引用用户)" if sender_only else ""))

	try:
		# 使用当前.sum指令的消息作为基准消息
		base_msgid = event.message_id

		# 准备摘要数据
		result = await summary_core.prepare_summary_data(
			group_id=event.group_id,
			sender_id=base_sender_id,
			count=count,
			sender_only=sender_only
		)

		# 检查结果是否为None
		if result is None:
			logger.error("result is None, 没有找到符合条件的消息")
			await adapter.send_reply("没有找到符合条件的消息")
			return

		data, resources = result

		# 再次检查data是否为None
		if data is None:
			logger.debug(f"result is {result}")
			logger.error("data is None, 没有找到符合条件的消息")
			await adapter.send_reply("没有找到符合条件的消息")
			return

		# 检查conversation是否存在且不为空
		if not data.get("conversation"):
			await adapter.send_reply("没有找到可摘要的消息内容")
			return

		# 生成摘要
		summary_result = await summary_core.generate_summary(data)

		# 发送摘要结果
		await adapter.send(
			TextSegment(f"💬 会话摘要 (最近 {count} 条消息" +
			            ("，仅限被引用用户" if sender_only else "") +
			            f")：\n\n{summary_result}")
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
