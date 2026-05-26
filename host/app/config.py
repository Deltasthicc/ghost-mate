"""Application settings."""
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    app_name: str = "Autonomous CoreXY Chess Robot"
    host: str = "127.0.0.1"
    port: int = 8000
    # APP_DEBUG (not DEBUG) so PlatformIO / shells don't poison the value with
    # non-boolean strings like "release".
    debug: bool = Field(default=False, validation_alias="APP_DEBUG")

    # SQLite "echo" is extremely chatty and slow in dev. Tie it to a dedicated
    # env so debug=True doesn't print every SQL statement.
    sql_echo: bool = Field(default=False, validation_alias="SQL_ECHO")

    # Serial / Teensy 4.0 link
    serial_port: str = "/dev/serial/by-id/usb-Teensyduino_USB_Serial_6634680-if00"
    serial_baud: int = 115200
    serial_mock: bool = True
    command_timeout_s: float = 5.0

    # Board geometry
    square_size_mm: float = 50.0
    board_origin_x_mm: float = 0.0
    board_origin_y_mm: float = 0.0
    capture_tray_left_x_mm: float = -60.0
    capture_tray_right_x_mm: float = 460.0

    # Chess engine
    stockfish_path: str = "stockfish"
    engine_move_time_s: float = 1.0
    engine_eval_time_s: float = 0.12  # fast eval used by WS pushes
    engine_live_push_enabled: bool = True
    engine_live_interval_s: float = 1.0
    engine_live_multipv: int = 5
    engine_live_max_depth: int = 15
    engine_threads: int | None = None  # None => CPU count - 1
    engine_hash_mb: int = 128
    engine_skill_level: int | None = None  # 0..20 to weaken Stockfish; None = full

    # Optional OpenAI-compatible LLM coach. The LLM receives only chess state,
    # Stockfish lines, and robot status; it never directly commands motion.
    llm_coach_enabled: bool = False
    llm_api_base: str = "https://api.openai.com/v1"
    llm_api_key: str | None = Field(default=None, validation_alias="LLM_API_KEY")
    llm_model: str = "gpt-4o-mini"
    llm_timeout_s: float = 20.0
    llm_max_tokens: int = 700

    database_url: str = Field(default="sqlite:///data/db/chess_robot.db")

    lichess_token: str | None = None
    lichess_bot_token: str | None = None

    # WebSocket / event bus tuning
    ws_max_queue: int = 256
    state_throttle_ms: int = 16  # max one push per ~60 fps

    @property
    def capped_engine_live_max_depth(self) -> int:
        return max(1, min(15, int(self.engine_live_max_depth)))

    @property
    def sqlite_path(self) -> Path | None:
        if not self.database_url.startswith("sqlite:///"):
            return None
        return Path(self.database_url.replace("sqlite:///", "", 1))


@lru_cache
def get_settings() -> Settings:
    return Settings()
