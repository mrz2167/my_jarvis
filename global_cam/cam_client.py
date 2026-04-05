"""
Global Cam — RPi клиент.
Захватывает камеру и стримит кадры на Railway relay сервер.

Запуск: python cam_client.py
"""
import asyncio
import base64
import json
import logging
import time

import cv2
import websockets

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("cam_client")

RELAY_URL    = "wss://sapyorserver-production.up.railway.app/stream"
CAMERA_INDEX = 0
FPS          = 10
JPEG_QUALITY = 80
RECONNECT_DELAY = 5


def open_camera():
    cap = cv2.VideoCapture(CAMERA_INDEX)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
    cap.set(cv2.CAP_PROP_FPS, FPS)
    return cap


async def stream():
    cap = open_camera()
    if not cap.isOpened():
        log.error("Камера не найдена")
        return

    interval = 1.0 / FPS

    while True:
        try:
            log.info(f"Подключаюсь к {RELAY_URL} ...")
            async with websockets.connect(
                RELAY_URL,
                ping_interval=20,
                ping_timeout=15,
                close_timeout=5,
            ) as ws:
                log.info("Подключён. Стримлю...")

                while True:
                    t0 = time.monotonic()

                    ret, frame = cap.read()
                    if not ret:
                        log.warning("Ошибка чтения кадра, переоткрываю камеру...")
                        cap.release()
                        await asyncio.sleep(1)
                        cap = open_camera()
                        continue

                    _, buf = cv2.imencode(
                        ".jpg", frame,
                        [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY]
                    )
                    data = base64.b64encode(buf.tobytes()).decode()
                    await ws.send(json.dumps({"type": "frame", "data": data}))

                    elapsed = time.monotonic() - t0
                    wait = interval - elapsed
                    if wait > 0:
                        await asyncio.sleep(wait)

        except (websockets.ConnectionClosed, OSError) as e:
            log.warning(f"Соединение потеряно: {e}. Переподключение через {RECONNECT_DELAY}с...")
            await asyncio.sleep(RECONNECT_DELAY)
        except Exception:
            log.exception("Неожиданная ошибка:")
            await asyncio.sleep(RECONNECT_DELAY)


if __name__ == "__main__":
    asyncio.run(stream())
