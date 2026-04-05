"""
Аудио ввод (INMP441 I2S микрофон) и вывод (MAX98357A I2S динамик).
"""
import logging
import queue
import threading
import numpy as np
import sounddevice as sd
import config

log = logging.getLogger(__name__)

_MIC_CHUNK_SAMPLES = int(config.MIC_RATE * config.MIC_CHUNK_MS / 1000)  # 320 сэмплов


class AudioInput:
    """Захват с микрофона. Кладёт PCM int16 chunks в очередь."""

    def __init__(self):
        self._queue = queue.Queue(maxsize=20)
        self._stream = None

    def start(self):
        def callback(indata, frames, time_info, status):
            if status:
                log.warning(f"Микрофон: {status}")
            pcm = (indata[:, 0] * 32767).astype(np.int16)
            if self._queue.full():
                try:
                    self._queue.get_nowait()
                except queue.Empty:
                    pass
            self._queue.put(pcm.tobytes())

        try:
            self._stream = sd.InputStream(
                samplerate=config.MIC_RATE,
                channels=config.MIC_CHANNELS,
                dtype='float32',
                blocksize=_MIC_CHUNK_SAMPLES,
                device=config.MIC_DEVICE,
                callback=callback,
            )
            self._stream.start()
            log.info(f"Микрофон запущен: {config.MIC_RATE}Hz, {_MIC_CHUNK_SAMPLES} сэмплов/чанк")
        except Exception as e:
            log.warning(f"Микрофон недоступен (I2S не подключён?): {e}")

    def get_chunk(self, timeout: float = 0.05):
        """Получить PCM int16 bytes. None если нет данных."""
        try:
            return self._queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def stop(self):
        if self._stream:
            self._stream.stop()
            self._stream.close()
        log.info("Микрофон остановлен")


class AudioOutput:
    """Воспроизведение PCM через динамик (MAX98357A)."""

    def __init__(self):
        self._stream = None
        self._buffer = queue.Queue(maxsize=50)
        self._thread = None
        self._running = False

    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self._play_loop, daemon=True)
        self._thread.start()
        log.info(f"Динамик запущен: {config.SPEAKER_RATE}Hz")

    def _check_device(self) -> bool:
        try:
            sd.query_devices(config.SPEAKER_DEVICE)
            return True
        except Exception:
            return False

    def _play_loop(self):
        while self._running:
            try:
                pcm_bytes = self._buffer.get(timeout=0.1)
                samples = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32) / 32767.0
                sd.play(samples, samplerate=config.SPEAKER_RATE, device=config.SPEAKER_DEVICE, blocking=True)
            except queue.Empty:
                continue
            except Exception as e:
                log.warning(f"Динамик недоступен (I2S не подключён?): {e}")
                self._buffer.queue.clear()

    def play(self, pcm_bytes: bytes):
        """Поставить PCM int16 bytes в очередь на воспроизведение."""
        if self._buffer.full():
            try:
                self._buffer.get_nowait()
            except queue.Empty:
                pass
        self._buffer.put(pcm_bytes)

    def stop(self):
        self._running = False
        sd.stop()
        log.info("Динамик остановлен")
