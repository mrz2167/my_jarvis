"""
Захват аудио с микрофона ПК и передача в STT.
"""
import logging
import numpy as np
import sounddevice as sd
import config

log = logging.getLogger(__name__)


class LocalMic:
    def __init__(self, on_chunk):
        """on_chunk(pcm_bytes: bytes) — вызывается каждые 20мс."""
        self._on_chunk = on_chunk
        self._stream   = None
        self._chunk    = int(config.MIC_RATE * 0.02)  # 320 сэмплов = 20мс

    def start(self):
        def callback(indata, frames, time_info, status):
            if status:
                log.warning(f"Mic: {status}")
            pcm = (indata[:, 0] * 32767).astype(np.int16)
            self._on_chunk(pcm.tobytes())

        self._stream = sd.InputStream(
            samplerate=config.MIC_RATE,
            channels=1,
            dtype='float32',
            blocksize=self._chunk,
            callback=callback,
        )
        self._stream.start()

        # Покажем какое устройство используется
        info = sd.query_devices(sd.default.device[0])
        log.info(f"Микрофон ПК: {info['name']} @ {config.MIC_RATE}Hz")

    def stop(self):
        if self._stream:
            self._stream.stop()
            self._stream.close()
