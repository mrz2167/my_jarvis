"""
Jarvis Robot Server — точка входа.

Запуск: python server.py

Принимает подключение от грипера по WebSocket (порт 9800).
Стримит аудио в Vosk STT, распознаёт команды, управляет роботом.
Опционально показывает видео с камеры.
"""
import asyncio
import base64
import json
import logging
import threading
import time
import sys

import numpy as np
import cv2
import websockets

import config
import commands
from stt import StreamingSTT
from robot_control import RobotControl
from mic import LocalMic

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("server")

# Глобальные объекты
robot   = RobotControl()
_latest_frame = None
_frame_lock   = threading.Lock()
_loop         = None   # asyncio event loop


# ─── Callback'и ───────────────────────────────────────────────────────

def on_text_recognized(text: str):
    """Вызывается когда STT распознал фразу."""
    command = commands.parse(text)
    if command and _loop:
        asyncio.run_coroutine_threadsafe(
            robot.execute(command), _loop
        )


# ─── WebSocket обработчик ─────────────────────────────────────────────

async def _ping_loop(ws):
    """Шлём ping роботу каждые 2 сек чтобы сбросить watchdog."""
    try:
        while True:
            await asyncio.sleep(2.0)
            await ws.send(json.dumps({"type": "ping", "ts": time.time()}))
    except websockets.ConnectionClosed:
        pass


async def handler(ws):
    global _latest_frame
    addr = ws.remote_address
    log.info(f"[+] Робот подключился: {addr}")
    robot.set_connection(ws)

    asyncio.create_task(_ping_loop(ws))

    try:
        async for raw in ws:
            msg = json.loads(raw)
            t   = msg.get("type")

            if t == "video":
                jpg   = base64.b64decode(msg["data"])
                arr   = np.frombuffer(jpg, dtype=np.uint8)
                frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
                if frame is not None:
                    with _frame_lock:
                        _latest_frame = frame

            elif t == "audio":
                pcm = base64.b64decode(msg["data"])
                stt.feed(pcm)

            elif t == "telemetry":
                robot.update_telemetry(msg)
                log.debug(f"Батарея: {robot.battery_v:.2f}V | Сонар: {robot.sonar_mm}мм")

            elif t == "pong":
                pass

    except websockets.ConnectionClosed:
        log.info(f"[-] Робот отключился: {addr}")
    finally:
        robot.set_connection(None)


# ─── Видео окно ───────────────────────────────────────────────────────

def video_loop():
    """Показывает видео с камеры робота (в отдельном потоке)."""
    if not config.SHOW_VIDEO:
        return

    cv2.namedWindow("Jarvis — Robot View", cv2.WINDOW_NORMAL)

    while True:
        with _frame_lock:
            frame = _latest_frame.copy() if _latest_frame is not None else None

        if frame is not None:
            # HUD: батарея и сонар
            bat   = f"BAT: {robot.battery_v:.1f}V"
            sonar = f"SONAR: {robot.sonar_mm}mm"
            cv2.putText(frame, bat,   (10, 25),  cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0,255,0), 2)
            cv2.putText(frame, sonar, (10, 50),  cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0,255,0), 2)
            cv2.imshow("Jarvis — Robot View", frame)
        else:
            blank = np.zeros((480, 640, 3), dtype=np.uint8)
            cv2.putText(blank, "Ожидание робота...", (150, 240),
                        cv2.FONT_HERSHEY_SIMPLEX, 1, (0,200,0), 2)
            cv2.imshow("Jarvis — Robot View", blank)

        key = cv2.waitKey(30) & 0xFF
        if key == 27:  # ESC
            break

    cv2.destroyAllWindows()


# ─── Главный цикл ─────────────────────────────────────────────────────

async def main():
    log.info(f"Jarvis Robot Server запущен на ws://{config.HOST}:{config.PORT}")
    log.info(f"Vosk модель: {config.VOSK_MODEL_PATH}")
    log.info("Ожидаю подключения робота...")
    log.info("Команды: вперёд / назад / влево / вправо / стоп / возьми / отпусти / домой")

    async with websockets.serve(handler, config.HOST, config.PORT,
                                ping_interval=None,
                                max_size=2**23):
        await asyncio.Future()  # работаем вечно


if __name__ == "__main__":
    # STT инициализация
    stt = StreamingSTT(on_text_recognized)
    stt.start()

    # Микрофон ПК → STT
    mic = LocalMic(on_chunk=stt.feed)
    mic.start()

    # Видео в отдельном потоке
    if config.SHOW_VIDEO:
        vid_thread = threading.Thread(target=video_loop, daemon=True)
        vid_thread.start()

    # Asyncio
    _loop = asyncio.new_event_loop()
    asyncio.set_event_loop(_loop)

    try:
        _loop.run_until_complete(main())
    except KeyboardInterrupt:
        log.info("Сервер остановлен")
    except OSError as e:
        if "10048" in str(e) or "already in use" in str(e).lower():
            log.error(f"Порт {config.PORT} уже занят! Закрой предыдущий сервер и перезапусти.")
        else:
            log.exception("Ошибка сервера:")
    except Exception:
        log.exception("Критическая ошибка:")
    finally:
        mic.stop()
        stt.stop()
        sys.exit(0)
