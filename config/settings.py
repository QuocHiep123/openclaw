"""
Configuration settings — loaded from environment variables / .env file.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import List, Optional

from pydantic_settings import BaseSettings
from pydantic import Field
from dotenv import load_dotenv

# Load .env file from project root
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_PROJECT_ROOT / ".env")


class Settings(BaseSettings):
    """Central configuration for the AI-Lab system."""

    # -- LLM --
    llm_provider: str = Field(default="openai", description="openai or google")
    llm_model: str = Field(default="gpt-4o-mini")
    openai_api_key: str = Field(default="")
    google_api_key: str = Field(default="")
    google_api_keys: str = Field(
        default="",
        description="Comma-separated Google API keys for rotation",
    )

    # -- Telegram --
    telegram_bot_token: str = Field(default="")
    telegram_allowed_users: str = Field(
        default="", description="Comma-separated user IDs"
    )

    # -- Chroma --
    chroma_persist_dir: str = Field(default="./data/chroma")

    # -- arXiv --
    arxiv_default_categories: str = Field(default="cs.AI,cs.LG,cs.CL")
    arxiv_max_papers: int = Field(default=20)

    # -- MCP Server --
    mcp_host: str = Field(default="127.0.0.1")
    mcp_port: int = Field(default=8100)

    # -- Proxy (for Telegram in restricted networks) --
    proxy_url: str = Field(default="", description="HTTP/SOCKS5 proxy URL")

    # -- Language --
    bot_language: str = Field(default="vi", description="Bot response language: en or vi")

    # -- Scheduled daily pipeline --
    daily_report_enabled: bool = Field(default=True, description="Enable daily auto report")
    daily_report_hour: int = Field(default=7, description="Hour (UTC) to run daily report")
    daily_report_minute: int = Field(default=0, description="Minute to run daily report")
    daily_report_chat_id: str = Field(default="", description="Telegram chat ID for daily report")

    # -- NLP/LLM daily research report (email) --
    research_report_enabled: bool = Field(default=True, description="Enable NLP/LLM research report pipeline")
    research_report_hour: int = Field(default=7, description="Hour (UTC) for NLP/LLM research report")
    research_report_minute: int = Field(default=30, description="Minute for NLP/LLM research report")
    research_report_recipient: str = Field(
        default="dangquochiep2908@gmail.com",
        description="Recipient email for NLP/LLM report PDF",
    )
    gmail_address: str = Field(default="", description="Gmail sender address for SMTP")
    gmail_app_password: str = Field(default="", description="Gmail app password for SMTP")

    # -- Logging --
    log_level: str = Field(default="INFO")

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

    # ---- helpers ---------------------------------------------------------
    @property
    def allowed_user_ids(self) -> List[int]:
        if not self.telegram_allowed_users:
            return []
        return [int(u.strip()) for u in self.telegram_allowed_users.split(",") if u.strip()]

    @property
    def arxiv_categories(self) -> List[str]:
        return [c.strip() for c in self.arxiv_default_categories.split(",") if c.strip()]

    @property
    def google_api_key_pool(self) -> List[str]:
        keys: List[str] = []
        if self.google_api_key.strip():
            keys.append(self.google_api_key.strip())
        if self.google_api_keys.strip():
            keys.extend(k.strip() for k in self.google_api_keys.split(",") if k.strip())

        # Remove duplicates while preserving order
        unique: List[str] = []
        seen = set()
        for key in keys:
            if key not in seen:
                unique.append(key)
                seen.add(key)
        return unique

    @property
    def project_root(self) -> Path:
        return _PROJECT_ROOT

    @property
    def data_dir(self) -> Path:
        d = _PROJECT_ROOT / "data"
        d.mkdir(parents=True, exist_ok=True)
        return d


# Singleton
settings = Settings()
