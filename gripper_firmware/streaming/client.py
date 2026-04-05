"""
WebSocket клиент — подключается к Jarvis серверу на ПК.
Стримит видео и аудио, получает и выполняет команды.
"""
import asyncio
import base64
import json
import logging
import time
import RPi.GPIO as GPIO
import websockets
import config
from hardware.board import Board
from hardware.camera import Camera
from hardware.audio import AudioInput, AudioOutput
from hardware.sonar import Sonar

log = logging.getLogger(__name__)

URI = f"ws://{config.SERVER_IP}:{config.SERVER_PORT}"


class RobotClient:
    def __init__(self, board: Board, camera: Camera,
                 audio_in: AudioInput, audio_out: AudioOutput, sonar: Sonar):
        self._board = board
        self._camera = camera
        self._audio_in = audio_in
        self._audio_out = audio_out
        self._sonar = sonar
        self._ws = None
        self._running = True
        self._last_msg_time = time.monotonic()
        self._watchdog_task = None

    # ─── Основной цикл ────────────────────────────────────────────────

    async def run(self):
        while self._running:
            try:
                log.info(f"Подключение к {URI} ...")
                async with websockets.connect(URI, ping_interval=20, ping_timeout=15,
                                             close_timeout=5, max_size=2**23) as ws:
                    self._ws = ws
                    self._last_msg_time = time.monotonic()
                    log.info("Подключено к серверу")
                    self._board.beep(True)
                    await asyncio.sleep(0.1)
                    self._board.beep(False)

                    # Запускаем все задачи параллельно
                    self._watchdog_task = asyncio.create_task(self._watchdog())
                    await asyncio.gather(
                        self._send_video(),
                        self._send_audio(),
                        self._send_telemetry(),
                        self._receive_commands(),
                        self._watchdog_task,
                    )

            except (websockets.ConnectionClosed, OSError, asyncio.TimeoutError) as e:
                log.warning(f"Соединение потеряно: {e}")
            except Exception as e:
                log.error(f"Неожиданная ошибка: {e}")
            finally:
                self._board.stop_all()
                self._ws = None
                if self._running:
                    log.info(f"Переподключение через {config.RECONNECT_DELAY}с...")
                    await asyncio.sleep(config.RECONNECT_DELAY)

    def stop(self):
        self._running = False
        if self._watchdog_task:
            self._watchdog_task.cancel()

    # ─── Стриминг видео ───────────────────────────────────────────────

    async def _send_video(self):
        while self._ws:
            frame = await asyncio.get_event_loop().run_in_executor(
                None, self._camera.get_frame, 0.1
            )
            if frame:
                await self._send({
                    "type": "video",
                    "data": base64.b64encode(frame).decode(),
                    "ts": time.time(),
                })
            else:
                await asyncio.sleep(0.01)

    # ─── Стриминг микрофона ───────────────────────────────────────────

    async def _send_audio(self):
        while self._ws:
            chunk = await asyncio.get_event_loop().run_in_executor(
                None, self._audio_in.get_chunk, 0.05
            )
            if chunk:
                await self._send({
                    "type": "audio",
                    "data": base64.b64encode(chunk).decode(),
                    "rate": config.MIC_RATE,
                    "ts": time.time(),
                })

    # ─── Телеметрия ───────────────────────────────────────────────────

    async def _send_telemetry(self):
        while self._ws:
            battery = await asyncio.get_event_loop().run_in_executor(
                None, self._board.get_battery_mv
            )
            sonar = await asyncio.get_event_loop().run_in_executor(
                None, self._sonar.get_distance_mm
            )
            await self._send({
                "type": "telemetry",
                "battery_mv": battery,
                "sonar_mm": sonar,
                "ts": time.time(),
            })
            await asyncio.sleep(config.TELEMETRY_INTERVAL)

    # ─── Приём и обработка команд ─────────────────────────────────────

    async def _receive_commands(self):
        async for raw in self._ws:
            self._last_msg_time = time.monotonic()
            try:
                msg = json.loads(raw)
                await self._handle(msg)
            except json.JSONDecodeError:
                log.warning("Получено невалидное JSON сообщение")
            except Exception as e:
                log.error(f"Ошибка обработки команды: {e}")

    async def _handle(self, msg: dict):
        t = msg.get("type")

        if t == "cmd_servos":
            # {"type": "cmd_servos", "servos": {"1": 1500, ...}, "time_ms": 500}
            self._board.set_servos(msg["servos"], msg.get("time_ms", 500))

        elif t == "cmd_motors":
            # {"type": "cmd_motors", "m1": 0, "m2": 0, "m3": 0, "m4": 0}
            self._board.set_motors(
                msg.get("m1", 0), msg.get("m2", 0),
                msg.get("m3", 0), msg.get("m4", 0)
            )

        elif t == "cmd_move":
            # {"type": "cmd_move", "velocity": 50, "direction": 90, "rotation": 0}
            self._board.move(
                msg.get("velocity", 0),
                msg.get("direction", 0),
                msg.get("rotation", 0)
            )

        elif t == "cmd_stop":
            self._board.stop_all()

        elif t == "cmd_audio":
            # {"type": "cmd_audio", "data": "<base64 pcm16le>"}
            pcm = base64.b64decode(msg["data"])
            self._audio_out.play(pcm)

        elif t == "ping":
            await self._send({"type": "pong", "ts": time.time()})

        else:
            log.warning(f"Неизвестный тип команды: {t}")

    # ─── Watchdog ─────────────────────────────────────────────────────

    async def _watchdog(self):
        """
        Останавливает моторы если сервер полностью молчит дольше WATCHDOG_TIMEOUT.
        Ping от сервера сбрасывает таймер — моторы останавливаются только при
        полной потере связи, а не при отсутствии команд движения.
        """
        _triggered = False
        while self._ws:
            await asyncio.sleep(1.0)
            silent = time.monotonic() - self._last_msg_time
            if silent > config.WATCHDOG_TIMEOUT:
                if not _triggered:
                    log.warning(f"Watchdog: нет связи {silent:.0f}с — стоп")
                    self._board.stop_all()
                    _triggered = True
            else:
                _triggered = False  # связь восстановлена

    # ─── Отправка ─────────────────────────────────────────────────────

    async def _send(self, data: dict):
        if self._ws:
            try:
                await self._ws.send(json.dumps(data))
            except websockets.ConnectionClosed:
                pass
