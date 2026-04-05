"""
Global Cam — просмотр стрима с Railway relay.
Запуск: python cam_viewer.py
"""
import asyncio
import base64
import json
import logging

import cv2
import numpy as np
import websockets

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("cam_viewer")

RELAY_URL = "wss://sapyorserver-production.up.railway.app/view"


async def receive():
    log.info(f"Подключаюсь к {RELAY_URL} ...")
    async with websockets.connect(RELAY_URL, ping_interval=20, ping_timeout=15) as ws:
        log.info("Подключён. Получаю стрим... (ESC для выхода)")
        cv2.namedWindow("Global Cam", cv2.WINDOW_NORMAL)

        async for raw in ws:
            msg = json.loads(raw)
            if msg.get("type") != "frame":
                continue

            jpg = base64.b64decode(msg["data"])
            arr = np.frombuffer(jpg, dtype=np.uint8)
            frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
            if frame is None:
                continue

            cv2.imshow("Global Cam", frame)
            if cv2.waitKey(1) & 0xFF == 27:
                break

    cv2.destroyAllWindows()


if __name__ == "__main__":
    asyncio.run(receive())
