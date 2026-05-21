from functools import lru_cache
from pathlib import Path
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Autonomous CoreXY Chess Robot"
    host: str = "127.0.0.1"
    port: int = 8000
    debug: bool = True

    serial_port: str = "COM3"
    serial_baud: int = 115200
    serial_mock: bool = True
    command_timeout_s: float = 5.0

    square_size_mm: float = 50.0
    board_origin_x_mm: float = 0.0
    board_origin_y_mm: float = 0.0
    capture_tray_left_x_mm: float = -60.0
    capture_tray_right_x_mm: float = 460.0

    stockfish_path: str = "stockfish"
    engine_move_time_s: float = 1.0

    database_url: str = Field(default="sqlite:///data/db/chess_robot.db")

    lichess_token: str | None = None
    lichess_bot_token: str | None = None

    @property
    def sqlite_path(self) -> Path | None:
        if not self.database_url.startswith("sqlite:///"):
            return None
        return Path(self.database_url.replace("sqlite:///", "", 1))


@lru_cache
def get_settings() -> Settings:
    return Settings()
