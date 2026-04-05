"""
Регистрация нового пользователя в базе лиц.
Делает 20 снимков с ESP32-CAM и сохраняет в базу.

Установка:
    pip install face_recognition opencv-python requests numpy

Запуск:
    python register_face.py --name "Имя"
"""
import cv2
import face_recognition
import numpy as np
import requests
import os
import pickle
import argparse
import time

ESP32_CAM_IP = "192.168.1.102"
STREAM_URL   = f"http://{ESP32_CAM_IP}/stream"
DB_FILE      = "faces_db.pkl"
PHOTOS_NEEDED = 50

def load_db():
    if os.path.exists(DB_FILE):
        with open(DB_FILE, "rb") as f:
            return pickle.load(f)
    return {}  # {name: [encoding1, encoding2, ...]}

def save_db(db):
    with open(DB_FILE, "wb") as f:
        pickle.dump(db, f)
    print(f"[DB] Сохранено в {DB_FILE}")

class MjpegReader:
    """Читает JPEG кадры из бесконечного MJPEG стрима."""
    def __init__(self, stream):
        self._iter  = stream.iter_content(chunk_size=4096)
        self._buf   = b""

    def read_frame(self):
        while True:
            # Ищем полный JPEG в буфере
            a = self._buf.find(b'\xff\xd8')
            b = self._buf.find(b'\xff\xd9')
            if a != -1 and b != -1 and b > a:
                jpg = self._buf[a:b+2]
                self._buf = self._buf[b+2:]
                arr = np.frombuffer(jpg, dtype=np.uint8)
                img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
                if img is not None:
                    return img
            # Нужно больше данных
            try:
                self._buf += next(self._iter)
            except StopIteration:
                return None

def register(name):
    db = load_db()
    if name in db:
        print(f"[!] '{name}' уже в базе ({len(db[name])} encodings). Добавляю ещё.")
    else:
        db[name] = []

    print(f"\nРегистрирую: {name}")
    print(f"Смотри в камеру. Нужно {PHOTOS_NEEDED} удачных снимков...\n")

    stream = requests.get(STREAM_URL, stream=True, timeout=10)
    reader = MjpegReader(stream)
    collected = 0

    last_capture   = 0.0   # время последнего сохранённого снимка
    CAPTURE_INTERVAL = 0.3  # минимум 0.3с между снимками для разнообразия

    # Последний известный результат — рисуем поверх каждого кадра
    last_locations = []
    last_label     = ""
    last_color     = (128, 128, 128)

    while collected < PHOTOS_NEEDED:
        frame = reader.read_frame()
        if frame is None:
            continue

        now = time.time()
        if now - last_capture >= CAPTURE_INTERVAL:
            # Уменьшаем для скорости HOG
            small = cv2.resize(frame, (0, 0), fx=0.5, fy=0.5)
            rgb   = cv2.cvtColor(small, cv2.COLOR_BGR2RGB)
            locations = face_recognition.face_locations(rgb, model="hog")

            if len(locations) == 1:
                encoding = face_recognition.face_encodings(rgb, locations)[0]
                db[name].append(encoding)
                collected += 1
                last_capture = now
                # Масштабируем координаты обратно
                top, right, bottom, left = locations[0]
                last_locations = [(top*2, right*2, bottom*2, left*2)]
                last_label = f"{name} [{collected}/{PHOTOS_NEEDED}]"
                last_color = (0, 255, 0)
                print(f"  Снимок {collected}/{PHOTOS_NEEDED}")
            elif len(locations) > 1:
                last_locations = []
                last_label = "Одно лицо в кадре!"
                last_color = (0, 0, 255)
                last_capture = now
            else:
                last_locations = []
                last_label = "Лицо не найдено"
                last_color = (0, 100, 255)
                last_capture = now

        # Рисуем последний результат на каждом кадре → плавное видео
        for (top, right, bottom, left) in last_locations:
            cv2.rectangle(frame, (left, top), (right, bottom), last_color, 2)
        if last_label:
            pos = (last_locations[0][3], last_locations[0][0] - 10) if last_locations else (10, 30)
            cv2.putText(frame, last_label, pos,
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, last_color, 2)

        cv2.imshow(f"Регистрация: {name}", frame)
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    cv2.destroyAllWindows()
    save_db(db)

    users = {k: len(v) for k, v in db.items()}
    print(f"\nБаза лиц: {users}")
    print(f"[OK] '{name}' зарегистрирован!")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", required=True, help="Имя пользователя")
    parser.add_argument("--cam",  default=ESP32_CAM_IP, help="IP ESP32-CAM")
    args = parser.parse_args()

    if args.cam != ESP32_CAM_IP:
        STREAM_URL = f"http://{args.cam}/stream"

    register(args.name)
