import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"
_DEFAULT_DATA_DIR = "~/dane/inzynierka"


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    anthropic_api_key: str | None

    @property
    def fit_dir(self) -> Path:
        return self.data_dir / "garmin" / "fit"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "db" / "llmrunplanner.sqlite"


def load_settings() -> Settings:
    load_dotenv(_ENV_FILE)
    data_dir = Path(os.environ.get("DATA_DIR") or _DEFAULT_DATA_DIR).expanduser()
    api_key = os.environ.get("ANTHROPIC_API_KEY") or None
    return Settings(data_dir=data_dir, anthropic_api_key=api_key)
