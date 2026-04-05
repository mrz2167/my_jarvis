"""
Тестовый сервер для проверки прошивки грипера.
Запускать: python test_server.py
- Показывает видео с камеры робота
- Печатает телеметрию (батарея, сонар)
- Управление клавишами:
    W/A/S/D  — движение
    Q/E      — вращение
    ПРОБЕЛ   — стоп
    1-6      — сервоприводы (тест)
    ESC      — выход
"""
import asyncio
import base64
import json
import time
import threading
import numpy as np
import cv2
import websockets

HOST = "0.0.0.0"
PORT = 9800

# Последний кадр с камеры (между потоками)
_latest_frame = None
_frame_lock = threading.Lock()
_ws_ref = None  # активное соединение


# ─── WebSocket сервер ──────────────────────────────────────────────────

async def _ping_loop(ws):
    """Шлём ping роботу каждые 2 секунды чтобы сбросить его watchdog."""
    try:
        while True:
            await asyncio.sleep(2.0)
            await ws.send(json.dumps({"type": "ping", "ts": time.time()}))
    except websockets.ConnectionClosed:
        pass


async def handler(ws):
    global _ws_ref
    _ws_ref = ws
    addr = ws.remote_address
    print(f"[+] Робот подключился: {addr}")

    asyncio.create_task(_ping_loop(ws))

    try:
        async for raw in ws:
            msg = json.loads(raw)
            t = msg.get("type")

            if t == "video":
                jpg = base64.b64decode(msg["data"])
                arr = np.frombuffer(jpg, dtype=np.uint8)
                frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
                if frame is not None:
                    with _frame_lock:
                        global _latest_frame
                        _latest_frame = frame

            elif t == "telemetry":
                bat = msg.get("battery_mv", 0) / 1000
                sonar = msg.get("sonar_mm", 0)
                print(f"  Батарея: {bat:.2f}V | Сонар: {sonar} мм")

            elif t == "audio":
                pass  # пока игнорируем аудио в тесте

            elif t == "pong":
                pass

    except websockets.ConnectionClosed:
        print(f"[-] Робот отключился: {addr}")
    finally:
        _ws_ref = None


async def send_cmd(data: dict):
    if _ws_ref:
        await _ws_ref.send(json.dumps(data))


# ─── Видео окно + управление клавишами ────────────────────────────────

def video_loop():
    """Показывает видео и обрабатывает клавиши (в отдельном потоке)."""
    cv2.namedWindow("Gripper Camera", cv2.WINDOW_NORMAL)

    while True:
        with _frame_lock:
            frame = _latest_frame.copy() if _latest_frame is not None else None

        if frame is not None:
            cv2.imshow("Gripper Camera", frame)
        else:
            blank = np.zeros((480, 640, 3), dtype=np.uint8)
            cv2.putText(blank, "Ожидание камеры...", (150, 240),
                        cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
            cv2.imshow("Gripper Camera", blank)

        key = cv2.waitKey(30) & 0xFF

        if key == 27:  # ESC — выход
            print("Выход...")
            break
        elif key == ord(' '):
            asyncio.run_coroutine_threadsafe(
                send_cmd({"type": "cmd_stop"}), _loop)
            print("СТОП")
        elif key == ord('w'):
            print("→ Вперёд")
            asyncio.run_coroutine_threadsafe(
                send_cmd({"type": "cmd_move", "velocity": 50, "direction": 0, "rotation": 0}), _loop)
        elif key == ord('s'):
            print("→ Назад")
            asyncio.run_coroutine_threadsafe(
                send_cmd({"type": "cmd_move", "velocity": 50, "direction": 180, "rotation": 0}), _loop)
        elif key == ord('a'):
            print("→ Влево")
            asyncio.run_coroutine_threadsafe(
                send_cmd({"type": "cmd_move", "velocity": 50, "direction": 270, "rotation": 0}), _loop)
        elif key == ord('d'):
            print("→ Вправо")
            asyncio.run_coroutine_threadsafe(
                send_cmd({"type": "cmd_move", "velocity": 50, "direction": 90, "rotation": 0}), _loop)
        elif key == ord('q'):
            print("→ Вращение влево")
            asyncio.run_coroutine_threadsafe(
                send_cmd({"type": "cmd_move", "velocity": 0, "direction": 0, "rotation": -40}), _loop)
        elif key == ord('e'):
            print("→ Вращение вправо")
            asyncio.run_coroutine_threadsafe(
                send_cmd({"type": "cmd_move", "velocity": 0, "direction": 0, "rotation": 40}), _loop)
        elif key == ord('1'):  # тест захвата
            asyncio.run_coroutine_threadsafe(
                send_cmd({"type": "cmd_servos", "servos": {"1": 1650}, "time_ms": 500}), _loop)
            print("Захват закрыт")
        elif key == ord('2'):
            asyncio.run_coroutine_threadsafe(
                send_cmd({"type": "cmd_servos", "servos": {"1": 1500}, "time_ms": 500}), _loop)
            print("Захват открыт")

    cv2.destroyAllWindows()


# ─── Точка входа ──────────────────────────────────────────────────────

_loop = None

async def main():
    print(f"Сервер запущен на ws://{HOST}:{PORT}")
    print("Жду подключения робота...")
    print("Управление: W/A/S/D=движение, Q/E=вращение, ПРОБЕЛ=стоп, 1/2=захват, ESC=выход")

    async with websockets.serve(handler, HOST, PORT):
        await asyncio.Future()  # работаем вечно


if __name__ == "__main__":
    _loop = asyncio.new_event_loop()

    # Видео в отдельном потоке
    vid_thread = threading.Thread(target=video_loop, daemon=True)
    vid_thread.start()

    # WebSocket сервер в asyncio
    asyncio.set_event_loop(_loop)
    try:
        _loop.run_until_complete(main())
    except KeyboardInterrupt:
        print("Сервер остановлен")
