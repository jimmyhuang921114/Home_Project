from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _load_project_env() -> None:
    env_path = PROJECT_ROOT / ".env"
    if env_path.exists():
        load_dotenv(env_path)


_load_project_env()


@dataclass(frozen=True)
class DatabaseConfig:
    host: str
    port: int
    dbname: str
    user: str
    password: str

    @property
    def dsn(self) -> str:
        return (
            f"host={self.host} "
            f"port={self.port} "
            f"dbname={self.dbname} "
            f"user={self.user} "
            f"password={self.password}"
        )


@dataclass(frozen=True)
class EmbeddingConfig:
    api_url: str
    model_name: str
    api_key: str


@dataclass(frozen=True)
class AgentConfig:
    chat_completions_url: str
    model_name: str
    api_key: str

    @property
    def ollama_url(self) -> str:
        return self.chat_completions_url


def get_database_config() -> DatabaseConfig:
    return DatabaseConfig(
        host=os.getenv("PGHOST", "localhost"),
        port=int(os.getenv("PGPORT", "5432")),
        dbname=os.getenv("PGDATABASE", "robot_db"),
        user=os.getenv("PGUSER", "postgres"),
        password=os.getenv("PGPASSWORD", ""),
    )


def get_embedding_config() -> EmbeddingConfig:
    return EmbeddingConfig(
        api_url=os.getenv(
            "EMBEDDING_API_URL",
            "http://localhost:11434/v1/embeddings",
        ),
        model_name=os.getenv(
            "EMBEDDING_MODEL_NAME",
            "all-minilm",
        ),
        api_key=os.getenv("EMBEDDING_API_KEY", "ollama"),
    )


def get_agent_config() -> AgentConfig:
    return AgentConfig(
        chat_completions_url=os.getenv(
            "LLM_CHAT_COMPLETIONS_URL",
            os.getenv("OLLAMA_URL", "http://localhost:11434/v1/chat/completions"),
        ),
        model_name=os.getenv("AGENT_MODEL", "gemma4:e4b"),
        api_key=os.getenv("LLM_API_KEY", "ollama"),
    )
