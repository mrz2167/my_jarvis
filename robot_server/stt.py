"""
Vosk STT — потоковое распознавание речи.
Принимает PCM int16 чанки, вызывает callback когда фраза распознана.
"""
import json
import logging
import threading
import queue
from vosk import Model, KaldiRecognizer
import config

log = logging.getLogger(__name__)


class StreamingSTT:
    def __init__(self, on_text):
        """
        on_text(text: str) — вызывается когда распознана фраза.
        """
        self._on_text  = on_text
        self._queue    = queue.Queue()
        self._running  = False
        self._thread   = None
        self._rec      = None

    def start(self):
        log.info(f"Загружаю Vosk модель: {config.VOSK_MODEL_PATH}")
        model = Model(config.VOSK_MODEL_PATH)
        self._rec = KaldiRecognizer(model, config.MIC_RATE)
        self._rec.SetWords(False)
        self._running = True
        self._thread  = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        log.info("STT запущен")

    def feed(self, pcm_bytes: bytes):
        """Отправить PCM int16 bytes на распознавание."""
        if self._running:
            self._queue.put(pcm_bytes)

    def _loop(self):
        while self._running:
            try:
                data = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue

            if self._rec.AcceptWaveform(data):
                result = json.loads(self._rec.Result())
                text   = result.get("text", "").strip()
                if text:
                    log.info(f"[STT] >>> {text}")
                    self._on_text(text)
            else:
                # Частичный результат (опционально)
                partial = json.loads(self._rec.PartialResult())
                p = partial.get("partial", "").strip()
                if p:
                    log.debug(f"[STT] ~{p}")

    def stop(self):
        self._running = False
