# Сборка Jarvis Core на Kali Linux (без GPU)

## Системные зависимости

```bash
sudo apt update
sudo apt install -y \
    build-essential \
    cmake \
    ninja-build \
    git \
    unzip \
    curl \
    wget
```

> CMake должен быть >= 3.20. Проверить: `cmake --version`
> На старых Kali может быть 3.18 — обновить через snap:
> ```bash
> sudo snap install cmake --classic
> ```

## Клонировать репозиторий

```bash
git clone https://github.com/<твой-юзер>/my_jarvis.git
cd my_jarvis
```

## Сборка

```bash
cd core

# Первая сборка — скачает все зависимости автоматически:
#   - ONNX Runtime linux-x64-1.20.1 (~10 MB)
#   - Vosk linux-x86_64-0.3.45 (~20 MB)
#   - vosk-model-ru-0.42 (~1.8 GB) ← долго!
cmake -B build -G Ninja
cmake --build build
```

Прогресс сборки и скачивания видно в терминале.

## Запуск

```bash
cd build

# Режим микрофон:
./jarvis_core

# Режим UDP (ESP32 робот на порту 9720):
./jarvis_core --udp
```

> Первый старт медленный — Vosk грузит RNNLM модель ~60-90 секунд.
> Последующие запуски такие же (модель не кешируется в памяти между запусками).

## Ожидаемый вывод

```
[Jarvis] STT модель: /path/to/my_jarvis/core/models/stt/vosk-model-ru-0.42
[Jarvis] Загружаю Vosk STT...
LOG (VoskAPI:ReadDataFiles()...) Decoding params beam=13 ...
... (много логов Vosk ~60 сек) ...
[Jarvis] Загружаю Silero VAD...
[SileroVAD] Входы (4): "input" "sr" "h" "c"
[Jarvis] Загружаю Wake Word (hey Jarvis)...
[VAD test] Тишина=0.04 Синусоида=0.08

[Jarvis] Доступные микрофоны:
  [0] default
  [1] ...
[Jarvis] Слушаю... Скажи "Hey Jarvis" (Ctrl+C для выхода)
```

## Проблемы

### Нет звука / `[Audio] peak=0 (тишина)` всегда

Проверить доступные устройства:
```bash
arecord -l          # список ALSA устройств
pactl list sources  # список PulseAudio устройств
```

Если нет PulseAudio, miniaudio переключится на ALSA автоматически.

### libvosk.so: cannot open shared object file

Убедись что запускаешь из директории `build/` — там лежит скопированный `libvosk.so`.
Или явно:
```bash
cd core/build
LD_LIBRARY_PATH=. ./jarvis_core
```

### cmake: command not found (версия < 3.20)

```bash
sudo snap install cmake --classic
hash -r  # обновить PATH
cmake --version
```

### Медленная загрузка модели (>2 мин)

Нормально для vosk-model-ru-0.42 (1.8 GB RNNLM). Если слишком медленно —
можно использовать малую модель (добавить в будущем):
- `vosk-model-small-ru-0.22` (~50 MB, загрузка ~3 сек, хуже качество)

## Полная пересборка (при смене CMakeLists.txt)

```bash
cd core
rm -rf build
cmake -B build -G Ninja
cmake --build build
```

Модели НЕ перекачиваются — они хранятся в `core/models/` (вне `build/`).

## Структура после сборки

```
core/
├── build/
│   ├── jarvis_core          ← исполняемый файл
│   ├── libvosk.so           ← скопировано POST_BUILD
│   ├── libonnxruntime.so    ← скопировано POST_BUILD
│   ├── silero_vad.onnx      ← скопировано POST_BUILD
│   ├── melspectrogram.onnx
│   ├── embedding_model.onnx
│   └── hey_jarvis_v0.1.onnx
└── models/
    ├── stt/vosk-model-ru-0.42/   ← скачано CMake (~1.8 GB)
    ├── vad/silero_vad.onnx        ← в git
    └── wake_word/*.onnx            ← в git
```
