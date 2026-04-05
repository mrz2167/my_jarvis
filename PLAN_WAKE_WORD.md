# PLAN_WAKE_WORD.md — Тренировка кастомной wake word модели

## Статус
**ПРОПУЩЕНО** — английская `hey_jarvis_v0.1.onnx` не реагирует на голос.
C++ wrapper написан и работает корректно (подтверждено Python-тестом).
Нужна только своя ONNX модель — подключается без изменений кода.

---

## Цель
Натренировать модель `jarvis_ru.onnx` на слово **"Джарвис"** (или любое другое)
и положить её в `core/build/` — C++ подхватит автоматически.

---

## Шаг 1 — Записать позитивные примеры

Нужно **200–500 записей** произношения wake word (больше = лучше).

```
core/training/
└── positive/
    ├── jarvis_001.wav
    ├── jarvis_002.wav
    └── ...
```

**Требования к записям:**
- Формат: WAV, моно, 16kHz, 16-bit PCM
- Длительность: 0.5–2 секунды каждая (только само слово)
- Разнообразие: разная громкость, скорость, интонация, расстояние от микрофона
- Окружение: дома в тишине, с фоновым шумом, с работающим ПК

**Инструмент для записи — Python скрипт:**
```bash
pip install sounddevice soundfile numpy
python record_samples.py  # см. ниже
```

Скрипт записи (сохни в `core/training/record_samples.py`):
```python
import sounddevice as sd
import soundfile as sf
import os, time

OUT_DIR = "positive"
os.makedirs(OUT_DIR, exist_ok=True)
existing = len([f for f in os.listdir(OUT_DIR) if f.endswith(".wav")])

print(f"Уже записано: {existing} сэмплов")
print("Нажми Enter → говори слово → Enter снова для следующего. Ctrl+C для выхода.\n")

i = existing
while True:
    input(f"[{i+1}] Нажми Enter и скажи слово...")
    rec = sd.rec(int(2 * 16000), samplerate=16000, channels=1, dtype='int16')
    sd.wait()
    path = f"{OUT_DIR}/jarvis_{i+1:03d}.wav"
    sf.write(path, rec, 16000)
    print(f"  Сохранено: {path}")
    i += 1
```

---

## Шаг 2 — Установить openWakeWord

```bash
pip install openwakeword
```

> openWakeWord автоматически генерирует негативные примеры (фоновая речь, шум, музыка) — вручную записывать не нужно.

---

## Шаг 3 — Натренировать модель

```bash
cd core/training

python -m openwakeword.train \
  --training_service "local" \
  --model_name "jarvis_ru" \
  --positive_reference_clips "positive/" \
  --output_dir "output/"
```

Тренировка займёт **20–60 минут** в зависимости от железа.
Результат: `output/jarvis_ru.onnx`

**Для лучшего качества** (опционально, нужно больше RAM/GPU):
```bash
python -m openwakeword.train \
  --training_service "local" \
  --model_name "jarvis_ru" \
  --positive_reference_clips "positive/" \
  --n_samples 10000 \
  --output_dir "output/"
```

---

## Шаг 4 — Протестировать модель на Python

Скопируй `jarvis_ru.onnx` в `core/build/`, затем:

```python
# test_custom_model.py — скопируй в build/
import onnxruntime as ort
import sounddevice as sd
import numpy as np
from collections import deque

CHUNK = 1280
mel_sess = ort.InferenceSession("melspectrogram.onnx")
emb_sess = ort.InferenceSession("embedding_model.onnx")
ww_sess  = ort.InferenceSession("jarvis_ru.onnx")  # ← своя модель

ww_in  = ww_sess.get_inputs()[0].name
ww_out = ww_sess.get_outputs()[0].name
ww_seq = ww_sess.get_inputs()[0].shape[1]

mel_buf = deque(maxlen=76)
emb_buf = deque(maxlen=ww_seq)

def process(chunk):
    x = (chunk * 32768).astype(np.float32).reshape(1, -1)
    mel = mel_sess.run(None, {"input": x})[0]
    for i in range(mel.shape[2]):
        mel_buf.append(mel[0, 0, i, :])
    if len(mel_buf) < 76: return
    ei = np.array(list(mel_buf), dtype=np.float32).reshape(1, 76, 32, 1)
    emb = emb_sess.run(None, {"input_1": ei})[0]
    emb_buf.append(emb.flatten()[:96])
    if len(emb_buf) < ww_seq: return
    wi = np.array(list(emb_buf), dtype=np.float32).reshape(1, ww_seq, 96)
    score = ww_sess.run(None, {ww_in: wi})[0].flat[0]
    if score > 0.3:
        print(f"DETECTED! score={score:.3f}")

print("Говори 'Джарвис'... Ctrl+C для выхода")
with sd.InputStream(samplerate=16000, channels=1, dtype='float32',
                    blocksize=CHUNK) as stream:
    while True:
        data, _ = stream.read(CHUNK)
        process(data[:, 0])
```

Ожидаемый результат: `DETECTED! score=0.7+` при произношении wake word.

---

## Шаг 5 — Подключить к Jarvis

```cmd
copy core\training\output\jarvis_ru.onnx core\build\jarvis_ru.onnx
```

Затем в `core/main.cpp` изменить одну строку:
```cpp
// было:
std::string wwModel  = "hey_jarvis_v0.1.onnx";
// стало:
std::string wwModel  = "jarvis_ru.onnx";
```

Собрать и запустить — готово.

---

## Ориентиры по качеству

| Кол-во сэмплов | Ожидаемое качество |
|---|---|
| 100 | Базово работает, много ложных срабатываний |
| 250 | Нормально для домашнего использования |
| 500 | Хорошо — редкие ложные срабатывания |
| 1000+ | Отлично |

---

## Полезные ссылки

- [openWakeWord — тренировка кастомных моделей](https://github.com/dscripka/openWakeWord/blob/main/docs/custom_models.md)
- [openWakeWord — примеры тренировки (Colab)](https://github.com/dscripka/openWakeWord/blob/main/notebooks/automatic_model_training.ipynb)
- [Форматы аудио для тренировки](https://github.com/dscripka/openWakeWord#training-new-models)

---

## Что уже готово в C++ (ничего менять не нужно)

- `core/wake/wake_word.hpp` — интерфейс WakeWordDetector
- `core/wake/wake_word.cpp` — полный ONNX pipeline (mel → emb → ww)
- `core/main.cpp` — интеграция в аудио поток
- `core/CMakeLists.txt` — авто-скачивание mel и emb моделей

Нужна только `jarvis_ru.onnx` — остальное работает.
