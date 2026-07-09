import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    google_api_key: str | None
    gcp_project: str | None
    agent_model: str
    guard_model: str
    fallback_model: str
    bq_dataset: str
    max_bytes_billed: int
    max_result_rows: int
    sqlite_path: str


def load_settings() -> Settings:
    return Settings(
        google_api_key=os.getenv("GOOGLE_API_KEY") or None,
        gcp_project=os.getenv("GOOGLE_CLOUD_PROJECT") or None,
        agent_model=os.getenv("AGENT_MODEL", "gemini-2.5-flash"),
        guard_model=os.getenv("GUARD_MODEL", "gemini-2.5-flash"),
        fallback_model=os.getenv("FALLBACK_MODEL", "gemini-2.5-flash-lite"),
        bq_dataset=os.getenv("BQ_DATASET", "bigquery-public-data.thelook_ecommerce"),
        max_bytes_billed=int(os.getenv("MAX_BYTES_BILLED", "200000000")),
        max_result_rows=int(os.getenv("MAX_RESULT_ROWS", "50")),
        sqlite_path=os.getenv("SQLITE_PATH", ".data/agent.sqlite"),
    )
