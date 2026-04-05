"""
Захват кадров с камеры в отдельном потоке.
Кладёт JPEG-байты в очередь для отправки.
"""
import cv2
import time
import logging
import threading
import queue
import config

log = logging.getLogger(__name__)


class Camera:
    def __init__(self):
        self._cap = None
        self._thread = None
        self._running = False
        self._frame_queue = queue.Queue(maxsize=2)  # не накапливаем старые кадры
        self._frame_interval = 1.0 / config.STREAM_FPS

    def start(self):
        self._cap = cv2.VideoCapture(config.CAMERA_ID)
        self._cap.set(cv2.CAP_PROP_FRAME_WIDTH,  config.CAMERA_WIDTH)
        self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, config.CAMERA_HEIGHT)
        self._cap.set(cv2.CAP_PROP_FPS,          config.CAMERA_FPS)

        if not self._cap.isOpened():
            raise RuntimeError(f"Не удалось открыть камеру {config.CAMERA_ID}")

        # Настройка качества изображения
        self._cap.set(cv2.CAP_PROP_BRIGHTNESS,  0.0)   # яркость
        self._cap.set(cv2.CAP_PROP_CONTRAST,    40)    # контраст
        self._cap.set(cv2.CAP_PROP_SATURATION,  60)    # насыщенность
        self._cap.set(cv2.CAP_PROP_SHARPNESS,   3)     # резкость (если поддерживается)
        self._cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 1)   # авто-экспозиция

        self._running = True
        self._thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._thread.start()
        log.info(f"Камера запущена {config.CAMERA_WIDTH}x{config.CAMERA_HEIGHT} → стрим {config.STREAM_FPS} fps")

    def _capture_loop(self):
        encode_params = [cv2.IMWRITE_JPEG_QUALITY, config.JPEG_QUALITY]
        # Ядро повышения резкости (unsharp mask)
        sharpen_kernel = cv2.UMat(
            __import__('numpy').array([[0, -1, 0], [-1, 5, -1], [0, -1, 0]], dtype='float32')
        )
        next_frame_time = time.monotonic()

        while self._running:
            ret, frame = self._cap.read()
            if not ret:
                log.warning("Камера: кадр не получен, переподключение...")
                time.sleep(0.5)
                self._cap.release()
                self._cap = cv2.VideoCapture(config.CAMERA_ID)
                continue

            now = time.monotonic()
            if now < next_frame_time:
                time.sleep(next_frame_time - now)
                continue

            next_frame_time = now + self._frame_interval

            # Повышение резкости
            frame = cv2.filter2D(frame, -1, sharpen_kernel)
            _, jpeg = cv2.imencode('.jpg', frame, encode_params)
            jpeg_bytes = jpeg.tobytes()

            # Вытолкнуть старый кадр если очередь полна
            if self._frame_queue.full():
                try:
                    self._frame_queue.get_nowait()
                except queue.Empty:
                    pass
            self._frame_queue.put(jpeg_bytes)

    def get_frame(self, timeout: float = 0.1):
        """Получить JPEG байты. Возвращает None если нет нового кадра."""
        try:
            return self._frame_queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def stop(self):
        self._running = False
        if self._cap:
            self._cap.release()
        log.info("Камера остановлена")
