from typing import TypedDict, Literal
from pydantic import BaseModel

class Margin(TypedDict):
    to_edge: int
    between_msgs: int
    between_senders: int


class Color(TypedDict):
    title: str
    bubble_bg: str
    bubble_text: str
    tips_bg: str
    tips_text: str


class FontSize(TypedDict):
    text: int
    title: int
    tips: int
    username: int


class DrawingParams(TypedDict):
    margin: Margin
    color: Color
    font_size: FontSize
    padding: int
    border: int
    bubble_corner_radius: int
    wrap_width: int
    spacing: int
    avatar_size: int


default_drawing_params: DrawingParams = {
    "margin": {
        "to_edge": 20,
        "between_msgs": 10,
        "between_senders": 60,
    },
    "color": {
        "title": "#3f444a",
        "bubble_bg": "#4c5b6f",
        "bubble_text": "#ffffff",
        "tips_bg": "#dae5e9",
        "tips_text": "#424f62",
    },
    "font_size": {
        "text": 28,
        "title": 30,
        "tips": 22,
        "username": 26,
    },
    "padding": 12,
    "border": 2,
    "bubble_corner_radius": 10,
    "wrap_width": 512,
    "avatar_size": 90,
    "spacing": 10,
}


class SummaryParams(TypedDict):
    show_banner: bool
    banner_position: Literal["up", "down", "u", "d"]
    show_nickname: bool
    show_id: bool


default_summary_params: SummaryParams = {
    "show_banner": True,
    "banner_position": "up",
    "show_id": True,
    "show_nickname": True,
}


class SummaryConfig(BaseModel):
    ollama_model: str = "deepseek-ri:1.5b"
    ollama_endpoint: str = "http://localhost:11434"
    prompt_template: str = "请对以下群聊对话内容进行简洁的摘要，提取主要话题和关键信息。对话内容如下：\n\n{conversation}\n\n请用中文给出摘要："
    max_conversation_length: int = 4000
    timeout: int = 180