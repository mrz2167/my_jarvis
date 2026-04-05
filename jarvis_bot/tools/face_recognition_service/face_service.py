"""
Face Recognition Service — постоянно смотрит в MJPEG стрим ESP32-CAM,
идентифицирует людей и сообщает Jarvis Core кто в кадре.

Установка:
    pip install face_recognition opencv-python requests numpy

Запуск:
    python face_service.py

Вывод:
    [FACE] Обнаружен: Алексей (уверенность: 87%)
    [FACE] Неизвестный
    [FACE] Никого нет
"""
import cv2
import face_recognition
import numpy as np
import requests
import pickle
import os
import time
import socket
import json

# ─── Настройки ───────────────────────────────────────────────
ESP32_CAM_IP  = "192.168.1.102"
JARVIS_IP     = "127.0.0.1"       # Jarvis Core (локально)
JARVIS_PORT   = 9723              # UDP порт для face events
STREAM_URL    = f"http://{ESP32_CAM_IP}/stream"
DB_FILE       = "faces_db.pkl"

CONFIDENCE_THRESHOLD = 0.55   # ниже = строже (0.4–0.6 норм)
PROCESS_EVERY_N      = 3      # обрабатывать каждый N-й кадр (CPU экономия)
PROCESS_SCALE        = 0.5    # уменьшить кадр для обработки (скорость)

# ─────────────────────────────────────────────────────────────

def load_db():
    if not os.path.exists(DB_FILE):
        print(f"[!] База лиц не найдена: {DB_FILE}")
        print(f"    Сначала запусти: python register_face.py --name 'Имя'")
        return {}, [], []

    with open(DB_FILE, "rb") as f:
        db = pickle.load(f)

    # Разворачиваем в плоские списки для face_recognition
    known_encodings = []
    known_names     = []
    for name, encodings in db.items():
        for enc in encodings:
            known_encodings.append(enc)
            known_names.append(name)

    print(f"[DB] Загружено пользователей: {len(db)}")
    for name, encs in db.items():
        print(f"     {name}: {len(encs)} encodings")

    return db, known_encodings, known_names

class MjpegReader:
    """Читает JPEG кадры из бесконечного MJPEG стрима."""
    def __init__(self, stream):
        self._iter = stream.iter_content(chunk_size=4096)
        self._buf  = b""

    def read_frame(self):
        while True:
            a = self._buf.find(b'\xff\xd8')
            b = self._buf.find(b'\xff\xd9')
            if a != -1 and b != -1 and b > a:
                jpg = self._buf[a:b+2]
                self._buf = self._buf[b+2:]
                arr = np.frombuffer(jpg, dtype=np.uint8)
                img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
                if img is not None:
                    return img
            try:
                self._buf += next(self._iter)
            except StopIteration:
                return None

def send_to_jarvis(sock, event):
    """Отправить событие Jarvis Core по UDP."""
    msg = json.dumps(event).encode()
    try:
        sock.sendto(msg, (JARVIS_IP, JARVIS_PORT))
    except Exception:
        pass

def run():
    db, known_encodings, known_names = load_db()
    if not known_encodings:
        return

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    print(f"\n[Face Service] Подключение к {STREAM_URL}...")
    stream = requests.get(STREAM_URL, stream=True, timeout=10)
    reader = MjpegReader(stream)
    print("[Face Service] Стрим получен. Распознавание запущено...\n")

    frame_count    = 0
    last_seen      = {}    # {name: timestamp} — когда последний раз видели
    ANNOUNCE_DELAY = 5.0   # не спамить — сообщать о человеке раз в N сек

    while True:
        frame = reader.read_frame()
        if frame is None:
            print("[!] Стрим прервался, переподключение...")
            time.sleep(2)
            stream = requests.get(STREAM_URL, stream=True, timeout=10)
            reader = MjpegReader(stream)
            continue

        frame_count += 1
        if frame_count % PROCESS_EVERY_N != 0:
            # Просто показываем кадр без обработки
            cv2.imshow("Jarvis Vision", frame)
            if cv2.waitKey(1) & 0xFF == ord('q'):
                break
            continue

        # Уменьшаем для скорости обработки
        small = cv2.resize(frame, (0, 0), fx=PROCESS_SCALE, fy=PROCESS_SCALE)
        rgb   = cv2.cvtColor(small, cv2.COLOR_BGR2RGB)

        locations  = face_recognition.face_locations(rgb, model="hog")
        encodings  = face_recognition.face_encodings(rgb, locations)

        results = []
        for enc, loc in zip(encodings, locations):
            distances = face_recognition.face_distance(known_encodings, enc)

            if len(distances) == 0:
                results.append(("Unknown", 0.0, loc))
                continue

            best_idx  = np.argmin(distances)
            best_dist = distances[best_idx]
            confidence = 1.0 - best_dist  # 0.0–1.0

            if confidence >= CONFIDENCE_THRESHOLD:
                name = known_names[best_idx]
            else:
                name = "Unknown"

            results.append((name, confidence, loc))

        # Масштабируем координаты обратно
        scale = 1.0 / PROCESS_SCALE
        now = time.time()

        for name, conf, (top, right, bottom, left) in results:
            top    = int(top    * scale)
            right  = int(right  * scale)
            bottom = int(bottom * scale)
            left   = int(left   * scale)

            # Цвет рамки
            color = (0, 255, 0) if name != "Unknown" else (0, 100, 255)
            cv2.rectangle(frame, (left, top), (right, bottom), color, 2)

            label = f"{name} ({conf*100:.0f}%)" if name != "Unknown" else "Unknown"
            cv2.putText(frame, label, (left, top - 10),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)

            # Отправить событие Jarvis если прошло достаточно времени
            last = last_seen.get(name, 0)
            if now - last >= ANNOUNCE_DELAY:
                last_seen[name] = now
                event = {
                    "event": "FaceDetected",
                    "name":  name,
                    "confidence": round(conf, 3)
                }
                send_to_jarvis(sock, event)
                print(f"[FACE] {'Обнаружен: ' + name if name != 'Unknown' else 'Неизвестный'}"
                      f" (уверенность: {conf*100:.0f}%)")

        if not results:
            cv2.putText(frame, "Нет лиц", (10, 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (128, 128, 128), 2)

        cv2.imshow("Jarvis Vision", frame)
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    cv2.destroyAllWindows()
    sock.close()

if __name__ == "__main__":
    run()
