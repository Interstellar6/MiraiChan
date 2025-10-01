from collections.abc import Iterable
from typing import TypedDict

from PIL import Image, ImageDraw
from lemony_utils.images import FontCache, _ColorT, wrap_text_by_width


class SummaryDisplayParams(TypedDict):
	font_size: int
	padding: int
	line_spacing: int
	max_width: int
	bg_color: str
	text_color: str
	border_radius: int


default_display_params: SummaryDisplayParams = {
	"font_size": 16,
	"padding": 20,
	"line_spacing": 8,
	"max_width": 600,
	"bg_color": "#f8f9fa",
	"text_color": "#333333",
	"border_radius": 10
}


class SummaryRenderer:
	def __init__(
			self,
			font: FontCache,
			display_params: SummaryDisplayParams | None = None
	):
		self._font = font
		self._params = default_display_params if display_params is None else display_params

	def render_summary_as_image(self, summary_data: dict, summary_text: str) -> Image.Image:
		"""将摘要渲染为图片（可选功能）"""
		# 计算图片尺寸
		font = self._font.use(self._params["font_size"])
		draw = ImageDraw.Draw(Image.new("RGBA", (1, 1)))

		# 包装文本
		wrapped_lines = wrap_text_by_width(
			summary_text,
			self._params["max_width"] - self._params["padding"] * 2,
			font
		)

		# 计算文本高度
		line_height = self._params["font_size"] + self._params["line_spacing"]
		text_height = len(wrapped_lines) * line_height

		# 计算图片总高度
		height = (self._params["padding"] * 2 + text_height +
		          self._params["line_spacing"] * 2)

		# 创建画布
		width = self._params["max_width"]
		img = Image.new("RGB", (width, height), color=self._params["bg_color"])
		draw = ImageDraw.Draw(img)

		# 绘制圆角矩形背景
		if self._params["border_radius"] > 0:
			self._draw_rounded_rectangle(
				draw,
				(0, 0, width, height),
				self._params["border_radius"],
				fill=self._params["bg_color"]
			)

		# 绘制摘要文本
		y = self._params["padding"]
		for line in wrapped_lines:
			draw.text(
				(self._params["padding"], y),
				line,
				fill=self._params["text_color"],
				font=font
			)
			y += line_height

		return img

	def _draw_rounded_rectangle(self, draw, xy, radius, **kwargs):
		"""绘制圆角矩形"""
		x1, y1, x2, y2 = xy
		draw.rectangle([x1 + radius, y1, x2 - radius, y2], **kwargs)
		draw.rectangle([x1, y1 + radius, x2, y2 - radius], **kwargs)
		draw.pieslice([x1, y1, x1 + 2 * radius, y1 + 2 * radius], 180, 270, **kwargs)
		draw.pieslice([x2 - 2 * radius, y1, x2, y1 + 2 * radius], 270, 360, **kwargs)
		draw.pieslice([x1, y2 - 2 * radius, x1 + 2 * radius, y2], 90, 180, **kwargs)
		draw.pieslice([x2 - 2 * radius, y2 - 2 * radius, x2, y2], 0, 90, **kwargs)