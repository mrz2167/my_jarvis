"""
Управление железом через I2C плату (0x7A).
Моторы (1-4), сервоприводы (1-6), батарея, зуммер.
"""
import math
import logging
import RPi.GPIO as GPIO
from smbus2 import SMBus, i2c_msg
import config

log = logging.getLogger(__name__)

# Регистры платы
_ADC_BAT_ADDR  = 0
_SERVO_ADDR    = 21   # одиночный сервопривод по углу
_MOTOR_ADDR    = 31   # моторы 1-4
_SERVO_CMD     = 40   # групповое управление по импульсу с временем

# Моторы инвертируются для синхронизации направления
_MOTOR_INVERT = {1: True, 2: False, 3: True, 4: False}


class Board:
    def __init__(self):
        GPIO.setwarnings(False)
        GPIO.setmode(GPIO.BCM)
        try:
            GPIO.setup(config.PIN_BUZZER, GPIO.OUT)
            GPIO.output(config.PIN_BUZZER, 0)
        except Exception as e:
            log.warning(f"Зуммер недоступен: {e}")
        self._motor_speed = [0, 0, 0, 0]
        self._servo_pulse = [1500] * 6
        self._i2c_ok = self._check_i2c()
        log.info(f"Board инициализирован (I2C: {'OK' if self._i2c_ok else 'недоступен'})")

    def _check_i2c(self) -> bool:
        try:
            with SMBus(config.I2C_BUS) as bus:
                bus.write_byte(config.BOARD_ADDR, 0)
            return True
        except Exception as e:
            log.warning(f"I2C плата недоступна (0x{config.BOARD_ADDR:02X}): {e}")
            return False

    # ─── Сервоприводы ─────────────────────────────────────────────────

    def set_servo(self, servo_id: int, pulse: int, time_ms: int = 500):
        if not self._i2c_ok: return
        """Переместить один сервопривод. pulse: 500-2500, time_ms: время движения."""
        if not 1 <= servo_id <= 6:
            raise ValueError(f"servo_id вне диапазона: {servo_id}")
        pulse += config.SERVO_DEVIATION.get(servo_id, 0)
        pulse = max(500, min(2500, pulse))
        time_ms = max(0, min(30000, time_ms))
        buf = [_SERVO_CMD, 1] + list(time_ms.to_bytes(2, 'little')) + \
              [servo_id] + list(pulse.to_bytes(2, 'little'))
        self._i2c_write(buf)
        self._servo_pulse[servo_id - 1] = pulse

    def set_servos(self, servos: dict, time_ms: int = 500):
        """Групповое управление. servos = {id: pulse, ...}"""
        if not self._i2c_ok or not servos:
            return
        time_ms = max(0, min(30000, time_ms))
        buf = [_SERVO_CMD, len(servos)] + list(time_ms.to_bytes(2, 'little'))
        for sid, pulse in servos.items():
            sid = int(sid)
            pulse += config.SERVO_DEVIATION.get(sid, 0)
            pulse = max(500, min(2500, pulse))
            buf += [sid] + list(pulse.to_bytes(2, 'little'))
            self._servo_pulse[sid - 1] = pulse
        self._i2c_write(buf)

    # ─── Моторы ───────────────────────────────────────────────────────

    def set_motor(self, index: int, speed: int):
        """Один мотор. index: 1-4, speed: -100..100."""
        if not self._i2c_ok: return
        if not 1 <= index <= 4:
            raise ValueError(f"motor index вне диапазона: {index}")
        speed = max(-100, min(100, speed))
        if _MOTOR_INVERT[index]:
            speed = -speed
        reg = _MOTOR_ADDR + (index - 1)
        self._i2c_write([reg, speed.to_bytes(1, 'little', signed=True)[0]])
        self._motor_speed[index - 1] = speed

    def set_motors(self, m1: int, m2: int, m3: int, m4: int):
        """Все 4 мотора сразу."""
        for i, spd in enumerate([m1, m2, m3, m4], start=1):
            self.set_motor(i, spd)

    def move(self, velocity: float, direction: float, rotation: float):
        """
        Mecanum движение.
        velocity:  0-100 (мм/с условно)
        direction: 0-360 градусов (0=вперёд, 90=вправо, 180=назад, 270=влево)
        rotation:  -100..100 (вращение по часовой = положительное)
        """
        rad = math.radians(direction)
        vx = velocity * math.sin(rad)
        vy = velocity * math.cos(rad)
        vp = rotation

        v1 = int(vy + vx - vp)   # передний-левый
        v2 = int(vy - vx + vp)   # передний-правый
        v3 = int(vy - vx - vp)   # задний-левый
        v4 = int(vy + vx + vp)   # задний-правый

        self.set_motors(v1, v2, v3, v4)

    # ─── Стоп / безопасность ──────────────────────────────────────────

    def stop_all(self):
        """Аварийная остановка: все моторы на 0."""
        if not self._i2c_ok:
            return
        try:
            for i in range(1, 5):
                reg = _MOTOR_ADDR + (i - 1)
                self._i2c_write([reg, 0])
            self._motor_speed = [0, 0, 0, 0]
            log.info("Все моторы остановлены")
        except Exception as e:
            log.error(f"Ошибка stop_all: {e}")

    # ─── Батарея ──────────────────────────────────────────────────────

    def get_battery_mv(self) -> int:
        """Напряжение батареи в мВ."""
        try:
            with SMBus(config.I2C_BUS) as bus:
                msg = i2c_msg.write(config.BOARD_ADDR, [_ADC_BAT_ADDR])
                bus.i2c_rdwr(msg)
                read = i2c_msg.read(config.BOARD_ADDR, 2)
                bus.i2c_rdwr(read)
                return int.from_bytes(bytes(list(read)), 'little')
        except Exception as e:
            log.warning(f"Ошибка чтения батареи: {e}")
            return 0

    # ─── Зуммер ───────────────────────────────────────────────────────

    def beep(self, state: bool = True):
        GPIO.output(config.PIN_BUZZER, int(state))

    # ─── Внутреннее ───────────────────────────────────────────────────

    def _i2c_write(self, buf: list):
        with SMBus(config.I2C_BUS) as bus:
            try:
                msg = i2c_msg.write(config.BOARD_ADDR, buf)
                bus.i2c_rdwr(msg)
            except Exception:
                msg = i2c_msg.write(config.BOARD_ADDR, buf)
                bus.i2c_rdwr(msg)

    def cleanup(self):
        self.stop_all()
        GPIO.cleanup()
