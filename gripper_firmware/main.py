"""
Gripper Firmware — точка входа.
Запускать: python3 main.py
"""
import asyncio
import logging
import signal
import sys
import RPi.GPIO as GPIO
import config
from hardware.board import Board
from hardware.camera import Camera
from hardware.audio import AudioInput, AudioOutput
from hardware.sonar import Sonar
from streaming.client import RobotClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("main")

board = None


def _setup_buttons(board: Board):
    """Настройка кнопок: KEY1 = аварийная остановка."""
    try:
        GPIO.setup(config.PIN_BTN_STOP, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        GPIO.setup(config.PIN_BTN_MODE, GPIO.IN, pull_up_down=GPIO.PUD_UP)

        def on_emergency_stop(channel):
            log.warning("KEY1 нажата — аварийная остановка!")
            board.stop_all()

        GPIO.add_event_detect(
            config.PIN_BTN_STOP,
            GPIO.FALLING,
            callback=on_emergency_stop,
            bouncetime=300,
        )
        log.info("Кнопки настроены")
    except Exception as e:
        log.warning(f"Кнопки недоступны: {e}")


async def main():
    global board

    log.info("=== Gripper Firmware запускается ===")

    # Инициализация железа
    board  = Board()
    camera = Camera()
    audio_in  = AudioInput()
    audio_out = AudioOutput()
    sonar  = Sonar()

    _setup_buttons(board)

    # Запуск стримеров
    camera.start()
    audio_in.start()
    audio_out.start()

    log.info(f"Сервер: ws://{config.SERVER_IP}:{config.SERVER_PORT}")

    client = RobotClient(board, camera, audio_in, audio_out, sonar)

    # Graceful shutdown по Ctrl+C / SIGTERM
    loop = asyncio.get_event_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, lambda: asyncio.create_task(_shutdown(client, board, camera, audio_in, audio_out)))

    await client.run()


async def _shutdown(client: RobotClient, board: Board, camera: Camera,
                    audio_in: AudioInput, audio_out: AudioOutput):
    log.info("Завершение работы...")
    client.stop()
    board.stop_all()
    camera.stop()
    audio_in.stop()
    audio_out.stop()
    board.cleanup()
    asyncio.get_event_loop().stop()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("Остановлено пользователем")
    except Exception:
        log.exception("КРИТИЧЕСКАЯ ОШИБКА:")
    finally:
        if board:
            board.stop_all()
            board.cleanup()
        log.info("Выход")
