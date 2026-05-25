"""FastAPI application factory and lifespan."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

# Prefer uvloop in production via uvicorn's --loop uvloop flag.
# We don't call uvloop.install() here; uvicorn picks the loop when it boots.

from host.app.api.routes import router as api_router
from host.app.api.ws import router as ws_router
from host.app.chesscore.engine_service import StockfishService
from host.app.config import get_settings
from host.app.db.session import init_db, make_engine
from host.app.domain.events import Event, EventBus, EventType
from host.app.domain.game_state import GameState
from host.app.hardware.board_sensor import BoardSensorService
from host.app.hardware.motion_service import MotionService
from host.app.hardware.safety_monitor import SafetyMonitor
from host.app.hardware.serial_link import JsonLineSerialClient, MockJsonLineClient

logger = logging.getLogger(__name__)

settings = get_settings()
templates = Jinja2Templates(directory="host/app/ui/templates")


async def handle_hardware_event(app: FastAPI, payload: dict) -> None:
    """Translate a raw serial event into a domain event on the bus."""
    event_type = payload.get("type")
    if event_type == "scan":
        snapshot = app.state.board_sensor.update_from_event(payload)
        await app.state.events.publish(Event(EventType.SCAN_RECEIVED, snapshot.to_payload()))
    elif event_type == "motion_done":
        app.state.safety.robot_busy = False
        app.state.game.robot_busy = False
        await app.state.events.publish(Event(
            EventType.ROBOT_MOVE_COMPLETE,
            {**payload, "state": app.state.game.snapshot()},
        ))
    elif event_type == "fault":
        code = str(payload.get("code", "unknown_fault"))
        app.state.safety.set_fault(code)
        app.state.game.last_error = code
        await app.state.events.publish(Event(EventType.FAULT, payload))
    else:
        await app.state.events.publish(Event(EventType.STATE_CHANGED, {"hardware_event": payload}))


@asynccontextmanager
async def lifespan(app: FastAPI):
    logging.basicConfig(
        level=logging.DEBUG if settings.debug else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    app.state.settings = settings
    app.state.events = EventBus(default_max=settings.ws_max_queue)
    app.state.game = GameState()
    app.state.board_sensor = BoardSensorService()
    app.state.safety = SafetyMonitor()
    app.state.engine = make_engine(settings)
    init_db(app.state.engine)

    # Persistent Stockfish (started lazily on first use to keep boot fast).
    app.state.stockfish = StockfishService(
        stockfish_path=settings.stockfish_path,
        move_time_s=settings.engine_move_time_s,
        threads=settings.engine_threads,
        hash_mb=settings.engine_hash_mb,
        skill_level=settings.engine_skill_level,
    )
    # Do not eagerly start Stockfish during app startup.
    # It starts lazily on the first engine endpoint request.
    # This keeps tests fast and prevents repeated TestClient lifespans from
    # spawning/quitting Stockfish hundreds of times.
    _engine_start = None

    if settings.serial_mock:
        serial = MockJsonLineClient()
    else:
        serial = JsonLineSerialClient(settings.serial_port, settings.serial_baud, settings.command_timeout_s)

    async def callback(payload: dict) -> None:
        await handle_hardware_event(app, payload)

    serial.set_event_callback(callback)
    await serial.start()
    app.state.serial = serial
    app.state.motion = MotionService(serial)

    try:
        yield
    finally:
        with _suppress_all():
            await serial.stop()
        if _engine_start is not None:
            with _suppress_all():
                _engine_start.cancel()
        with _suppress_all():
            await app.state.stockfish.stop()


class _suppress_all:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return True


app = FastAPI(
    title=settings.app_name,
    lifespan=lifespan,
)
app.include_router(api_router, prefix="/api")
app.include_router(ws_router)
app.mount("/static", StaticFiles(directory="host/app/ui/static"), name="static")


@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request=request, name="index.html", context={"settings": settings})
