import json
import random
import time
from typing import NotRequired, TypedDict


class MoonCakeData(TypedDict):
	surface: str
	filling: str
	flavor: str
	effect: str
	# 细节属性
	special_effect: NotRequired[str]
	flavor_combo: NotRequired[str]
	cosmic_effect: NotRequired[str]
	# 记录时间
	time: float


class MoonCakeLot:
	def __init__(self, mooncake_file: str):
		with open(mooncake_file, "r", encoding="utf-8") as fp:
			data = json.load(fp)
		self._mooncake_attrs: dict[str, float] = data["mooncake_attrs"]
		self._d_mooncake_attrs: dict[str, dict[str, float]] = data["detailed_mooncake"]

	@staticmethod
	def random_with_weight(data_dict: dict[str, float]):
		if not data_dict:
			return None
		sum_wt = sum(data_dict.values())
		ra_wt = random.uniform(0, sum_wt)
		cur_wt = 0
		for key in data_dict.keys():
			cur_wt += data_dict[key]
			if ra_wt <= cur_wt:
				return key

	def draw(self) -> MoonCakeData:
		res = {}
		# 抽取主属性
		for attr_type in self._mooncake_attrs.keys():
			res[attr_type] = self.random_with_weight(self._mooncake_attrs[attr_type])

		# 抽取细节属性 - 特殊效果
		if "special_effects" in self._d_mooncake_attrs:
			for req_effect in self._d_mooncake_attrs["special_effects"].keys():
				if req_effect == res.get("effect"):
					res["special_effect"] = self.random_with_weight(
						self._d_mooncake_attrs["special_effects"][req_effect]
					)

		# 抽取细节属性 - 口味组合
		if "flavor_combos" in self._d_mooncake_attrs:
			for req_flavor in self._d_mooncake_attrs["flavor_combos"].keys():
				if req_flavor == res.get("flavor"):
					res["flavor_combo"] = self.random_with_weight(
						self._d_mooncake_attrs["flavor_combos"][req_flavor]
					)

		# 抽取细节属性 - 宇宙级效果
		if "cosmic_effects" in self._d_mooncake_attrs:
			for req_cosmic in self._d_mooncake_attrs["cosmic_effects"].keys():
				if req_cosmic == res.get("effect"):
					res["cosmic_effect"] = self.random_with_weight(
						self._d_mooncake_attrs["cosmic_effects"][req_cosmic]
					)

		# 移除空值
		for k in [k for k, v in res.items() if v in ("普通", "/", "无", None)]:
			if k in res:
				res.pop(k)

		res["time"] = time.time()
		return res

	@staticmethod
	def to_text(mooncakedata: MoonCakeData):
		# 构建基础描述
		text_parts = []

		# 外表描述
		surface_desc = f"表面{mooncakedata['surface']}"
		text_parts.append(surface_desc)

		# 内馅描述
		filling_desc = f"内里却是{mooncakedata['filling']}"
		text_parts.append(filling_desc)

		# 口味描述
		flavor_desc = f"的{mooncakedata['flavor']}月饼"
		text_parts.append(flavor_desc)

		# 组合描述
		if "flavor_combo" in mooncakedata:
			combo_desc = f"，搭配着{mooncakedata['flavor_combo']}"
			text_parts.append(combo_desc)

		# 效果描述
		effect_desc = f"，而且吃了会{mooncakedata['effect']}"
		text_parts.append(effect_desc)

		# 特殊效果描述
		if "special_effect" in mooncakedata:
			special_desc = f"（{mooncakedata['special_effect']}）"
			text_parts.append(special_desc)

		# 宇宙级效果描述
		if "cosmic_effect" in mooncakedata:
			cosmic_desc = f"不过{mooncakedata['cosmic_effect']}"
			text_parts.append(cosmic_desc)

		# 如果没有特殊效果，添加感叹号
		if "special_effect" not in mooncakedata and "cosmic_effect" not in mooncakedata:
			text_parts.append("！")

		return "".join(text_parts)