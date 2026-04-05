"""
Отправка команд на робота через WebSocket.
"""
import asyncio
import json
import logging
import config

log = logging.getLogger(__name__)


class RobotControl:
    def __init__(self):
        self._ws       = None  # активное WebSocket соединение
        self._telemetry = {"battery_mv": 0, "sonar_mm": 5000}

    def set_connection(self, ws):
        self._ws = ws

    def update_telemetry(self, data: dict):
        self._telemetry.update(data)

    @property
    def battery_v(self) -> float:
        return self._telemetry["battery_mv"] / 1000

    @property
    def sonar_mm(self) -> int:
        return self._telemetry["sonar_mm"]

    # ─── Команды движения ─────────────────────────────────────────

    async def move_forward(self):
        await self._send({"type": "cmd_move", "velocity": config.MOVE_SPEED,
                          "direction": 0, "rotation": 0})

    async def move_backward(self):
        await self._send({"type": "cmd_move", "velocity": config.MOVE_SPEED,
                          "direction": 180, "rotation": 0})

    async def move_left(self):
        await self._send({"type": "cmd_move", "velocity": config.MOVE_SPEED,
                          "direction": 270, "rotation": 0})

    async def move_right(self):
        await self._send({"type": "cmd_move", "velocity": config.MOVE_SPEED,
                          "direction": 90, "rotation": 0})

    async def rotate(self, clockwise: bool = True):
        r = config.ROTATE_SPEED if clockwise else -config.ROTATE_SPEED
        await self._send({"type": "cmd_move", "velocity": 0,
                          "direction": 0, "rotation": r})

    async def stop(self):
        await self._send({"type": "cmd_stop"})

    # ─── Команды манипулятора ─────────────────────────────────────

    async def arm_home(self):
        await self._send({"type": "cmd_servos",
                          "servos": config.ARM_HOME,
                          "time_ms": config.MOVE_TIME_MS})

    async def arm_up(self):
        await self._send({"type": "cmd_servos",
                          "servos": config.ARM_UP,
                          "time_ms": config.MOVE_TIME_MS})

    async def arm_down(self):
        await self._send({"type": "cmd_servos",
                          "servos": config.ARM_DOWN,
                          "time_ms": config.MOVE_TIME_MS})

    async def arm_extend(self):
        await self._send({"type": "cmd_servos",
                          "servos": config.ARM_EXTEND,
                          "time_ms": config.MOVE_TIME_MS})

    async def grab(self):
        await self._send({"type": "cmd_servos",
                          "servos": config.ARM_GRAB,
                          "time_ms": config.MOVE_TIME_MS})

    async def release(self):
        await self._send({"type": "cmd_servos",
                          "servos": config.ARM_OPEN,
                          "time_ms": config.MOVE_TIME_MS})

    async def set_servo(self, servo_id: int, pulse: int, time_ms: int = 500):
        await self._send({"type": "cmd_servos",
                          "servos": {str(servo_id): pulse},
                          "time_ms": time_ms})

    async def set_arm(self, servos: dict, time_ms: int = 500):
        """Групповое управление рукой. servos = {id: pulse}"""
        await self._send({"type": "cmd_servos",
                          "servos": servos,
                          "time_ms": time_ms})

    # ─── Выполнение команды по имени ──────────────────────────────

    async def execute(self, command: str, telemetry_callback=None):
        """Выполнить команду по имени (из commands.py)."""
        if command == "move_forward":
            await self.move_forward()
        elif command == "move_backward":
            await self.move_backward()
        elif command == "move_left":
            await self.move_left()
        elif command == "move_right":
            await self.move_right()
        elif command == "rotate":
            await self.rotate()
        elif command == "stop":
            await self.stop()
        elif command == "grab":
            await self.grab()
        elif command == "release":
            await self.release()
        elif command == "arm_home":
            await self.arm_home()
        elif command == "arm_up":
            await self.arm_up()
        elif command == "arm_down":
            await self.arm_down()
        elif command == "arm_extend":
            await self.arm_extend()
        elif command == "status_battery":
            log.info(f"Батарея: {self.battery_v:.2f}V")
            if telemetry_callback:
                telemetry_callback(f"Батарея {self.battery_v:.1f} вольт")
        elif command == "status_sonar":
            log.info(f"Сонар: {self.sonar_mm} мм")
            if telemetry_callback:
                telemetry_callback(f"Расстояние {self.sonar_mm} миллиметров")

    # ─── Внутреннее ───────────────────────────────────────────────

    async def _send(self, data: dict):
        if self._ws:
            try:
                await self._ws.send(json.dumps(data))
            except Exception as e:
                log.warning(f"Ошибка отправки команды: {e}")
        else:
            log.warning("Робот не подключён")
