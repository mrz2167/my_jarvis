"""
Ультразвуковой датчик расстояния (I2C 0x77).
"""
import logging
from smbus2 import SMBus, i2c_msg
import config

log = logging.getLogger(__name__)


class Sonar:
    def __init__(self):
        self._i2c = config.I2C_BUS
        self._addr = config.SONAR_ADDR

    def get_distance_mm(self) -> int:
        """Расстояние в мм. Максимум 5000 мм."""
        try:
            with SMBus(self._i2c) as bus:
                msg = i2c_msg.write(self._addr, [0])
                bus.i2c_rdwr(msg)
                read = i2c_msg.read(self._addr, 2)
                bus.i2c_rdwr(read)
                dist = int.from_bytes(bytes(list(read)), byteorder='little', signed=False)
                return min(dist, 5000)
        except Exception as e:
            log.warning(f"Ошибка сонара: {e}")
            return 5000
