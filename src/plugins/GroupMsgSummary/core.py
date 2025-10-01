import asyncio
import json
import time
from collections.abc import Iterable
from dataclasses import dataclass
from typing import TypedDict, cast

from melobot.protocols.onebot.v11.adapter.segment import (
	AtSegment,
	FaceSegment,
	ImageSegment,
	Segment,
	TextSegment,
)
from pydantic import BaseModel
from sqlmodel import col, select
from yarl import URL

from lemony_utils.asyncutils import gather_with_concurrency
from lemony_utils.botutils import cached_avatar_source
from lemony_utils.consts import http_headers
from lemony_utils.templates import async_http
from recorder_models import Message

from .params import SummaryConfig


@dataclass(frozen=True)
class ConversationMessage:
	sender_id: int
	sender_name: str
	content: str
	timestamp: int


class SummaryData(TypedDict):
	group_id: int
	group_name: str | None
	summary_time: float
	conversation: list[ConversationMessage]
	summary_result: str | None


def extract_text_from_segments(segments: list[Segment]) -> str:
	"""从消息段中提取纯文本内容"""
	text_parts = []
	text_genby_mface = set()

	for seg in segments:
		if isinstance(seg, TextSegment):
			text_parts.append(seg.data["text"])
		elif isinstance(seg, AtSegment):
			text_parts.append(f"@{seg.data.get('name', seg.data['qq'])}")
		elif seg.type == "mface":
			if mftext := seg.data.get("summary"):
				text_genby_mface.add(mftext)
		elif isinstance(seg, ImageSegment):
			text_parts.append("[图片]")
		elif isinstance(seg, FaceSegment):
			text_parts.append("[表情]")
		else:
			text_parts.append(f"[{seg.type}]")

	# 添加由mface生成但未被包含的文本
	for mftext in text_genby_mface:
		if mftext not in text_parts:
			text_parts.append(mftext)

	return " ".join(text_parts)


def prepare_conversation_data(
		msgs: list[Message], banned_sticker_sets: Iterable[int] = ()
) -> tuple[list[ConversationMessage], set[URL | str]]:
	"""准备会话数据，提取文本内容"""
	resources = set[URL | str]()
	conversation = []

	for msg in msgs:
		# 获取发送者信息
		sender_name = msg.sender.name if msg.sender else str(msg.sender_id)
		resources.add(cached_avatar_source.get_url(msg.sender_id))

		# 提取消息文本内容
		segments = []
		for seg in msg.segments:
			qseg = Segment.resolve(seg.type, seg.data)
			segments.append(qseg)

		content = extract_text_from_segments(segments)

		conversation.append(ConversationMessage(
			sender_id=msg.sender_id,
			sender_name=sender_name,
			content=content,
			timestamp=msg.timestamp
		))

	return conversation, resources


class SummaryGenerator:
	def __init__(self, config: SummaryConfig):
		self.config = config

	async def generate_summary(self, conversation: list[ConversationMessage]) -> str:
		"""调用ollama生成会话摘要"""
		# 构建对话文本
		conversation_text = self._format_conversation(conversation)

		# 构建提示词
		prompt = self.config.prompt_template.format(conversation=conversation_text)

		# 调用ollama API
		return await self._call_ollama(prompt)

	def _format_conversation(self, conversation: list[ConversationMessage]) -> str:
		"""格式化对话内容"""
		lines = []
		for msg in conversation:
			timestamp = time.strftime("%H:%M:%S", time.localtime(msg.timestamp))
			lines.append(f"{msg.sender_name}({msg.sender_id}) [{timestamp}]: {msg.content}")

		conversation_text = "\n".join(lines)

		# 如果对话过长，进行截断
		if len(conversation_text) > self.config.max_conversation_length:
			conversation_text = conversation_text[:self.config.max_conversation_length] + "\n[...对话内容过长，已截断...]"

		return conversation_text

	async def _call_ollama(self, prompt: str) -> str:
		"""调用ollama API"""
		payload = {
			"model": self.config.ollama_model,
			"prompt": prompt,
			"stream": False
		}

		try:
			async with async_http(
					f"{self.config.ollama_endpoint}/api/generate",
					"post",
					headers={"Content-Type": "application/json"},
					data=json.dumps(payload),
					timeout=self.config.timeout
			) as resp:
				if resp.status == 200:
					result = await resp.json()
					return result.get("response", "生成摘要失败").strip()
				else:
					return f"调用ollama失败: HTTP {resp.status}"
		except asyncio.TimeoutError:
			return "生成摘要超时，请稍后重试"
		except Exception as e:
			return f"生成摘要时发生错误: {str(e)}"


class SummaryCore:
	def __init__(self, config: SummaryConfig):
		self.config = config
		self.generator = SummaryGenerator(config)

	async def prepare_summary_data(
			self,
			base_msgid: int,
			group_id: int,
			sender_id: int | None,
			count: int | None,
			start: int,
			end: int,
			sender_only: bool
	) -> tuple[SummaryData | None, set[URL | str]]:
		"""准备摘要数据"""
		from .. import Recorder

		async with Recorder.database.get_session() as sess:
			# 构建查询
			query = select(Message).where(
				Message.group_id == group_id
			).order_by(col(Message.timestamp).desc())

			# 根据参数类型获取消息
			if count is not None:
				# 获取最近N条消息
				messages = (await sess.exec(query.limit(count))).all()
				messages.reverse()  # 按时间顺序排列
			else:
				# 获取指定区间的消息
				all_messages = (await sess.exec(query)).all()
				all_messages.reverse()

				if start < 0 or end >= len(all_messages):
					return None, set()

				messages = all_messages[start:end + 1]

			# 如果指定了sender_only，过滤消息
			if sender_only and sender_id:
				messages = [msg for msg in messages if msg.sender_id == sender_id]

			if not messages:
				return None, set()

			# 准备会话数据
			conversation, resources = prepare_conversation_data(messages)

			data: SummaryData = {
				"group_id": group_id,
				"group_name": messages[0].group.name if messages[0].group else None,
				"summary_time": time.time(),
				"conversation": conversation,
				"summary_result": None
			}

			return data, resources

	async def generate_summary(self, data: SummaryData) -> str:
		"""生成摘要"""
		summary = await self.generator.generate_summary(data["conversation"])
		return summary