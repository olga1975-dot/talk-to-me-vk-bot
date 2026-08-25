from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    vk_group_token: str
    vk_group_id: int
    kie_api_key: str
    kie_chat_url: str
    kie_chat_model: str
    authorized_vk_id: int
    authorized_tg_id: int
    database_path: str
    history_limit: int


def load_settings() -> Settings:
    load_dotenv()
    vk_group_token = (os.getenv("VK_GROUP_TOKEN") or os.getenv("BOT_TOKEN") or "").strip()
    vk_group_id = os.getenv("VK_GROUP_ID", "").strip()
    kie_api_key = os.getenv("KIE_API_KEY", "").strip()
    if not vk_group_token:
        raise RuntimeError("VK_GROUP_TOKEN/BOT_TOKEN is missing. Add the VK community token.")
    if not vk_group_id.isdigit():
        raise RuntimeError("VK_GROUP_ID must be the numeric community ID.")
    if not kie_api_key:
        raise RuntimeError("KIE_API_KEY is missing. Copy .env.example to .env.")
    return Settings(
        vk_group_token=vk_group_token,
        vk_group_id=int(vk_group_id),
        kie_api_key=kie_api_key,
        kie_chat_url=os.getenv("KIE_CHAT_URL", "https://api.kie.ai/gemini-3-5-flash-openai/v1/chat/completions"),
        kie_chat_model=os.getenv("KIE_CHAT_MODEL", "gemini-3-5-flash-thinking"),
        authorized_vk_id=int(os.getenv("AUTHORIZED_VK_ID", "2840329")),
        authorized_tg_id=int(os.getenv("AUTHORIZED_TG_ID", "328761045")),
        database_path=os.getenv("DATABASE_PATH", "talk_to_me.db"),
        history_limit=max(4, int(os.getenv("HISTORY_LIMIT", "14"))),
    )
