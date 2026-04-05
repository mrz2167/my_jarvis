# SPEC_CORE.md — Спецификация C++ движка Jarvis Core

## 1. Обзор

Jarvis Core — автономный C++ процесс, который:
- Работает **всегда в фоне**, независимо от GUI и агента
- Требует **только микрофон** для базовой работы
- **Никогда не обращается в интернет** напрямую
- Общается с GUI через **WebSocket IPC**
- Общается с Python агентом через **ZeroMQ**

---

## 2. Компоненты движка

```
┌─────────────────────────────────────────────────────┐
│                   JARVIS CORE (C++)                 │
│                                                     │
│  [Audio] → [VAD] → [Wake-word] → [STT] → [Classify]│
│                                              ↓    ↓ │
│                                          [CMD] [ZMQ]│
│                                              ↓    ↓ │
│                                          [TTS] [WS] │
└─────────────────────────────────────────────────────┘
```

### 2.1 Audio Capture
### 2.2 VAD (Voice Activity Detector) — Silero VAD
### 2.3 Wake-word Engine — openWakeWord
### 2.4 STT (Speech-To-Text) — Whisper.cpp
### 2.5 Classifier — rapidfuzz fuzzy matching
### 2.6 Command Executor
### 2.7 TTS (Text-To-Speech) — Piper
### 2.8 IPC — WebSocket (GUI) + ZeroMQ (Agent)

---

## 3. Детальная спецификация компонентов

---

### 3.1 Audio Capture

**Библиотека:** `miniaudio` (header-only, нет зависимостей)

**Параметры захвата:**
```
Sample rate:  16000 Hz
Channels:     1 (моно)
Format:       PCM 16-bit
Buffer size:  512 фреймов (~32ms)
```

**Поведение:**
- При старте — сканирует доступные устройства ввода
- Устройство по умолчанию берётся из `settings.toml`
- Если устройство недоступно — fallback на системное устройство по умолчанию
- Аудио поток передаётся в VAD непрерывно

**Конфиг (`settings.toml`):**
```toml
[audio]
device = "default"        # имя устройства или "default"
sample_rate = 16000
channels = 1
```

---

### 3.2 VAD — Voice Activity Detector

**Библиотека:** Silero VAD (ONNX модель, ~1.5 MB)

**Почему Silero VAD вместо energy-based:**
- Отличает голос от шума вентилятора, музыки, клавиатуры, ТВ
- Точность >99% в реальных условиях
- Задержка <1ms на inference
- Работает через ONNX Runtime (уже есть в зависимостях)

**Алгоритм:**
```
1. Буферизировать 512 сэмплов (~32ms)
2. Прогнать через Silero VAD → вероятность речи (0.0 - 1.0)
3. Если prob > threshold → голос активен
4. Если голос активен > min_speech_ms → начать захват
5. Если prob < threshold > silence_timeout_ms → конец фразы
6. Передать аудио фрагмент в следующий модуль
```

**Параметры:**
```toml
[vad]
threshold = 0.5           # порог вероятности речи (0.0 - 1.0)
min_speech_ms = 250       # минимальная длина речи
silence_timeout_ms = 1200 # тишина после которой фраза считается законченной
pre_buffer_ms = 150       # буфер до начала речи (не обрезать начало)
model = "silero_vad.onnx" # путь к модели
```

**Состояния VAD:**
```
IDLE → DETECTING → CAPTURING → END_OF_PHRASE
```

**Нагрузка:**
| Метрика | Значение |
|---------|---------|
| Модель (диск) | ~1.5 MB |
| RAM | ~10 MB |
| CPU idle | <0.1% |

---

### 3.3 Wake-word Engine

**Библиотека:** openWakeWord (ONNX модели через ONNX Runtime)

**Почему openWakeWord вместо Whisper.cpp tiny:**
- Whisper — batch-транскрибер, не предназначен для постоянного прослушивания
- Whisper tiny занимает ~150 MB RAM и даёт пик CPU при каждом срабатывании VAD
- openWakeWord: ~5-15 MB RAM, <1% CPU, задержка <30ms
- Специально обучен для wake-word задачи

**Принцип работы:**
```
Аудио поток (непрерывно, 16kHz)
   ↓
[Mel Spectrogram] → mel features (~1ms)
   ↓
[Embedding ONNX model] → audio embeddings (~3ms)
   ↓
[Wake-word ONNX model] → вероятность слова (0.0 - 1.0) (~2ms)
   ↓
Если prob > threshold → активация!
```

**Модели:**
- `melspectrogram.onnx` — общая предобработка (~200 KB)
- `embedding_model.onnx` — аудио эмбеддинги (~1 MB)
- `jarvis_ru.onnx` — детектор wake-word для "Джарвис" (~100 KB)

**Конфиг:**
```toml
[wake_word]
words = ["джарвис", "jarvis"]      # активные wake-word
threshold = 0.5                    # порог вероятности
models_dir = "models/wake_word/"   # директория с ONNX моделями
activation_sound = "sounds/ding.wav"  # звук при активации (опционально)
```

**После активации:**
- Отправить WebSocket событие: `WakeWordDetected`
- Переключиться в режим STT (VAD продолжает накапливать фразу)
- Воспроизвести звук активации (если настроен)

**Нагрузка:**
| Метрика | Значение |
|---------|---------|
| Модели (диск) | ~2 MB |
| RAM | ~15 MB |
| CPU idle (постоянный мониторинг) | <1% |

---

### 3.4 STT — Speech-To-Text

**Библиотека:** Whisper.cpp (base модель)

**Поток работы:**
```
1. Получить аудио от VAD (конец фразы, буферизованный)
2. Прогнать через Whisper base в отдельном потоке
3. Получить текст
4. Передать в Classifier
5. Отправить WebSocket событие: SpeechRecognized { text }
```

**Важно:** STT работает в буферизованном режиме (v1) — накапливает аудио до конца фразы (по VAD), затем обрабатывает. Потоковое распознавание (streaming) — задача для будущей версии.

**Параметры:**
```toml
[stt]
model = "base"            # tiny / base / small
language = "ru"           # язык распознавания
max_duration_sec = 10     # максимальная длина фразы
beam_size = 5             # качество vs скорость
threads = 4               # потоки для inference
```

**Модели и нагрузка:**

| Модель | Размер | RAM | Скорость | Качество |
|--------|--------|-----|----------|---------|
| tiny   | 75 MB  | ~150 MB | очень быстро | среднее |
| base   | 142 MB | ~250 MB | быстро | хорошее |
| small  | 466 MB | ~600 MB | медленно | отличное |

> Рекомендуется **base** — оптимальный баланс для русского языка

**Обработка ошибок:**
- Пустой текст → игнорировать, вернуться в wake-word режим
- Текст слишком короткий (<2 символа) → игнорировать
- Timeout (>10 сек аудио) → обрезать и обработать

---

### 3.5 Classifier — Классификатор команд

**Задача:** определить что делать с распознанным текстом:
1. Выполнить системную команду локально
2. Передать Python агенту (LLM запрос)

**Метод:** rapidfuzz — нечёткое сравнение строк (без ML, без моделей)

**Почему rapidfuzz вместо sentence embeddings:**
- `all-MiniLM-L6-v2` обучен на английском — плохо работает с русским
- Для 20-100 команд ML не нужен — fuzzy matching точнее и быстрее
- 0 MB моделей, ~0.1ms на сравнение, 0 RAM сверх команд

**Алгоритм:**
```
1. При старте: загрузить все фразы из .toml команд в память
2. Нормализовать текст (нижний регистр, убрать пунктуацию)
3. Получить текст от STT
4. Для каждой фразы: вычислить token_set_ratio (rapidfuzz)
5. Найти максимальный score и соответствующую команду
6. Если max_score >= threshold → выполнить команду
7. Если max_score < threshold → передать Python агенту
```

**rapidfuzz `token_set_ratio`** — устойчив к:
- Перестановке слов ("открой хром" == "хром открой")
- Частичным совпадениям ("запусти браузер хром" → "открой браузер")
- Опечаткам и вариациям произношения

**Параметры:**
```toml
[classifier]
threshold = 72            # порог совпадения (0-100)
top_k = 3                 # сколько кандидатов логировать
fallback = "agent"        # "agent" / "tts_error"
```

**Пример работы:**
```
Вход:    "открой хром"
Фразы:   "открой браузер" (85), "закрой браузер" (52), "запусти хром" (78)
Решение: max=85 >= 72 → выполнить команду browser_open

Вход:    "какая погода в москве"
Фразы:   "открой браузер" (18), "выключи пк" (12)
Решение: max=18 < 72 → передать агенту
```

---

### 3.6 Command Executor — Исполнитель команд

**Формат команды (`.toml`):**
```toml
[[commands]]
id = "browser_open"
type = "process"          # тип: process / script / system / ipc / ghost_touch
exe_path = "chrome.exe"   # путь к исполняемому файлу
exe_args = []             # аргументы
tts_confirm.ru = "открываю браузер"  # TTS подтверждение
timeout_ms = 5000

phrases.ru = [
    "открой браузер",
    "запусти хром",
    "открой хром",
]
phrases.en = [
    "open browser",
    "launch chrome",
]

[[commands]]
id = "ghost_touch_enable"
type = "ghost_touch"
action = "start"
tts_confirm.ru = "жест-контроль включён"

phrases.ru = ["включи жест контроль", "запусти жест управление"]
phrases.en = ["enable ghost touch", "start hand control"]

[[commands]]
id = "mode_work"
type = "ipc"
event = "SetMode"
payload = { mode = "work" }
tts_confirm.ru = "рабочий режим"

phrases.ru = ["рабочий режим", "включи работу"]
```

**Типы команд:**

| Тип | Что делает |
|-----|-----------|
| `process` | Запускает внешний .exe / скрипт |
| `script` | Выполняет Python / PowerShell скрипт |
| `system` | Встроенные системные команды (volume, shutdown и т.д.) |
| `ipc` | Отправляет событие через WebSocket (GUI) |
| `ghost_touch` | Управляет Ghost Touch через IPC сигнал |

**Встроенные системные команды (`type = "system"`):**
```
media.play / media.pause / media.stop
media.next / media.prev
media.volume_up / media.volume_down / media.mute
system.shutdown / system.restart / system.sleep / system.lock
display.brightness_up / display.brightness_down
```

**Ghost Touch интеграция (graceful shutdown):**
```
ghost_touch action="start":
  1. Проверить: Ghost Touch уже запущен? → если да, пропустить
  2. Запустить ghost_touch.exe как отдельный процесс
  3. Подождать подключения Ghost Touch к WebSocket (порт 9712)
  4. Отправить WebSocket: GhostTouchEnabled

ghost_touch action="stop":
  1. Отправить WebSocket событие: { "action": "Shutdown" }  ← Ghost Touch слушает
  2. Ждать graceful exit (таймаут 3 сек)
  3. Если не завершился → SIGTERM → ждать 1 сек → SIGKILL
  4. Отправить WebSocket: GhostTouchDisabled
```

> Ghost Touch должен подключиться к WebSocket порту 9712 и слушать `Shutdown` команду для корректного завершения.

**После выполнения команды:**
- Успех → TTS: подтверждение из `tts_confirm` → WebSocket: `CommandExecuted`
- Ошибка → TTS: "не удалось выполнить" → WebSocket: `CommandFailed`

---

### 3.7 TTS — Text-To-Speech

**Библиотека:** Piper TTS

**Использование:**
- Подтверждения команд (короткие фразы)
- Ответы от LLM агента (длинный текст)
- Системные сообщения ("не понял", "нет соединения")

**Конфиг:**
```toml
[tts]
voice = "ru_RU-ruslan-medium"   # голос
speed = 1.0                     # скорость речи
volume = 0.8                    # громкость
models_dir = "models/tts/"      # директория с голосовыми моделями
```

**Очередь воспроизведения:**
- TTS работает через очередь (queue) в отдельном потоке
- Если пришёл новый текст пока говорит → добавить в очередь
- Команда `Stop` очищает очередь и прерывает текущее воспроизведение
- Во время воспроизведения TTS → wake-word отключён (не реагирует на себя)

---

### 3.8 IPC — Межпроцессное взаимодействие

Два отдельных канала с разными протоколами:

```
┌─────────────┐    WebSocket ws://127.0.0.1:9712    ┌─────────┐
│ Jarvis Core │◄──────────────────────────────────► │   GUI   │
│             │                                      └─────────┘
│             │    ZeroMQ PUSH tcp://127.0.0.1:9713  ┌─────────────┐
│             │──────────────────────────────────────►│             │
│             │    ZeroMQ PULL tcp://127.0.0.1:9714  │ Python Agent│
│             │◄─────────────────────────────────────│             │
└─────────────┘                                      └─────────────┘
```

---

#### 3.8.1 WebSocket IPC — GUI канал

**Адрес:** `ws://127.0.0.1:9712`
**Формат:** JSON

**Поведение:**
- Принимает несколько клиентов одновременно (GUI, Ghost Touch, внешние инструменты)
- При подключении нового клиента → отправить текущий статус (`Status`)
- Если клиент отключился → продолжать работу
- Ping/Pong каждые 30 сек

**События Core → GUI:**
```json
{ "event": "WakeWordDetected" }
{ "event": "Listening" }
{ "event": "SpeechRecognized", "text": "открой браузер" }
{ "event": "CommandExecuted", "id": "browser_open", "success": true }
{ "event": "CommandFailed", "id": "browser_open", "error": "Process not found" }
{ "event": "AgentRequest", "text": "какая погода в москве" }
{ "event": "AgentResponse", "text": "В Москве сейчас -5 градусов" }
{ "event": "GhostTouchEnabled" }
{ "event": "GhostTouchDisabled" }
{ "event": "ModeChanged", "mode": "work" }
{ "event": "Idle" }
{ "event": "Error", "message": "STT model not loaded" }
{ "event": "Status", "state": "listening", "wake_word": true, "ghost_touch": false, "mode": "default" }
```

**Команды GUI → Core:**
```json
{ "action": "Stop" }
{ "action": "Ping" }
{ "action": "TextCommand", "text": "открой браузер" }
{ "action": "Speak", "text": "Текст для озвучки" }
{ "action": "SetMuted", "muted": true }
{ "action": "SetLanguage", "language": "ru" }
{ "action": "ReloadCommands" }
{ "action": "SetMode", "mode": "game" }
{ "action": "GetStatus" }
{ "action": "Shutdown" }
```

---

#### 3.8.2 ZeroMQ IPC — Python Agent канал

**Почему ZeroMQ вместо WebSocket для агента:**
- Нет overhead HTTP handshake — минимальная задержка
- Встроенная буферизация и retry
- Надёжнее для долгих LLM запросов (10+ секунд)
- Нативные C++ и Python биндинги

**Паттерн:** PUSH/PULL (асинхронный, non-blocking)

```
Core PUSH → Agent PULL   tcp://127.0.0.1:9713   (запросы к агенту)
Agent PUSH → Core PULL   tcp://127.0.0.1:9714   (ответы от агента)
```

**Формат сообщений:** JSON

**Core → Agent (порт 9713):**
```json
{
  "type": "AgentRequest",
  "request_id": "uuid-1234",
  "text": "какая погода в москве",
  "language": "ru",
  "history": []
}
```

**Agent → Core (порт 9714):**
```json
{
  "type": "AgentResponse",
  "request_id": "uuid-1234",
  "text": "В Москве сейчас -5 градусов и пасмурно",
  "success": true
}
```
```json
{
  "type": "AgentError",
  "request_id": "uuid-1234",
  "error": "LLM API timeout"
}
```

**Reconnect логика (Core):**
```
1. При старте: попытаться подключиться к агенту (PUSH на 9713, PULL на 9714)
2. Если агент недоступен → продолжать работу в офлайн режиме
3. ZMQ PUSH буферизирует сообщения автоматически (до агента дойдут при запуске)
4. Heartbeat: каждые 15 сек отправить { "type": "Ping" }
5. Если нет ответа 30 сек → логировать "Agent unavailable", TTS предупреждение
6. При восстановлении соединения → возобновить автоматически (ZMQ reconnect)
```

---

## 4. Состояния движка

```
┌─────────┐    wake word    ┌───────────┐
│  IDLE   │───────────────►│ LISTENING │
└─────────┘                └───────────┘
     ▲                           │
     │                     распознал
     │                           ▼
     │              ┌────────────────────┐
     │              │    CLASSIFYING     │
     │              └────────────────────┘
     │                    ↙         ↘
     │            команда            агент
     │                ↓                ↓
     │        ┌───────────┐    ┌──────────────┐
     └────────│ EXECUTING │    │ AGENT_REQUEST│
              └───────────┘    └──────────────┘
                    │                  │
                    └──────┬───────────┘
                           ▼
                      ┌─────────┐
                      │ RESPOND │  (TTS воспроизведение)
                      └─────────┘
                           │
                           └──► IDLE
```

---

## 5. Режимы работы

| Режим | Что меняется |
|-------|-------------|
| `work` | wake-word чувствительность снижена, медиа команды ограничены |
| `game` | максимальная скорость отклика, TTS отключён |
| `film` | wake-word отключён (только ручная активация), тихий TTS |
| `relax` | всё включено, мягкий голос, медленная речь |
| `default` | стандартный режим |

---

## 6. Конфигурация — полная схема `settings.toml`

```toml
[general]
language = "ru"
mode = "default"
autostart = true

[audio]
device = "default"
sample_rate = 16000

[vad]
threshold = 0.5
min_speech_ms = 250
silence_timeout_ms = 1200
pre_buffer_ms = 150
model = "models/vad/silero_vad.onnx"

[wake_word]
words = ["джарвис", "jarvis"]
threshold = 0.5
models_dir = "models/wake_word/"
activation_sound = ""         # путь к .wav или "" для отключения

[stt]
model = "base"
language = "ru"
max_duration_sec = 10
beam_size = 5
threads = 4

[classifier]
threshold = 72
fallback = "agent"

[tts]
voice = "ru_RU-ruslan-medium"
speed = 1.0
volume = 0.8
models_dir = "models/tts/"

[ipc]
ws_port = 9712                # WebSocket для GUI
zmq_push_port = 9713          # ZMQ → Agent
zmq_pull_port = 9714          # ZMQ ← Agent
host = "127.0.0.1"
agent_heartbeat_sec = 15

[ghost_touch]
exe_path = "C:/path/to/ghost_touch.exe"
autostart = false
shutdown_timeout_ms = 3000    # graceful exit timeout

[commands]
dir = "config/commands/"      # директория с .toml командами
```

---

## 7. Обработка ошибок

| Ситуация | Поведение |
|----------|-----------|
| Микрофон недоступен | Лог ошибки, WS: Error, ждать устройство |
| VAD модель не найдена | Остановить запуск, вывести путь |
| Wake-word модели не найдены | Остановить запуск, вывести путь |
| STT модель не найдена | Остановить запуск, вывести путь |
| Команда не выполнилась | TTS: "не удалось выполнить", WS: CommandFailed |
| Python агент недоступен | TTS: "нет связи с агентом" (один раз), работать офлайн |
| Ghost Touch не найден | TTS: "Ghost Touch не установлен", WS: Error |
| Ghost Touch зависает при выключении | SIGTERM → ждать 1 сек → SIGKILL |
| Нет совпадения и нет агента | TTS: "не понял команду" |
| LLM запрос завис (>10 сек) | TTS: "агент не отвечает", вернуться в IDLE |

---

## 8. Производительность и нагрузка

**Целевые показатели:**

| Метрика | Цель | Реальность с новым стеком |
|---------|------|--------------------------|
| RAM в idle | < 320 MB | ~290 MB (VAD 10 + Wake 15 + STT 250 + прочее) |
| CPU в idle | < 1% | <0.5% (VAD + Wake постоянно, но лёгкие) |
| CPU во время STT | < 30% | ~25% пик, ~1-2 сек |
| Задержка wake-word | < 50ms | ~30ms (openWakeWord потоковый) |
| Задержка VAD → STT start | < 20ms | <10ms |
| Задержка STT → результат | < 800ms | ~600ms (base модель) |
| Задержка классификатора | < 5ms | <1ms (rapidfuzz) |

**Распределение RAM:**
```
Silero VAD:          ~10 MB
openWakeWord:        ~15 MB
Whisper base (STT):  ~250 MB
Piper TTS:           ~30 MB
Движок + буферы:     ~15 MB
─────────────────────────────
Итого:               ~320 MB
```

**Оптимизации:**
- Whisper работает в отдельном потоке (не блокирует pipeline)
- VAD и Wake-word работают в одном потоке потоковой обработки
- Классификатор кэширует нормализованные фразы при старте
- TTS рендерит аудио асинхронно в отдельном потоке
- ZMQ PUSH/PULL неблокирующий — LLM ответ не блокирует прослушивание

---

## 9. Файловая структура проекта (C++)

```
core/
├── CMakeLists.txt
├── main.cpp
├── audio/
│   ├── capture.hpp / capture.cpp
│   └── miniaudio.h                  ← vendor (header-only)
├── vad/
│   ├── vad.hpp / vad.cpp            ← Silero VAD через ONNX Runtime
│   └── silero_vad.onnx              ← модель (скачивается при сборке)
├── wake/
│   ├── wake_word.hpp / wake_word.cpp ← openWakeWord через ONNX Runtime
│   └── models/                      ← ONNX модели wake-word
│       ├── melspectrogram.onnx
│       ├── embedding_model.onnx
│       └── jarvis_ru.onnx
├── stt/
│   ├── stt.hpp / stt.cpp
│   └── whisper.cpp/                 ← git submodule
├── classifier/
│   ├── classifier.hpp / classifier.cpp ← rapidfuzz fuzzy matching
│   └── rapidfuzz/                   ← vendor (header-only)
├── commands/
│   ├── executor.hpp / executor.cpp
│   ├── loader.hpp / loader.cpp      ← читает .toml команды
│   └── ghost_touch.hpp / ghost_touch.cpp
├── tts/
│   ├── tts.hpp / tts.cpp
│   └── piper/                       ← git submodule
├── ipc/
│   ├── ws_server.hpp / ws_server.cpp   ← WebSocket для GUI
│   ├── zmq_bridge.hpp / zmq_bridge.cpp ← ZeroMQ для Python агента
│   └── websocketpp/                 ← vendor (header-only)
├── config/
│   └── settings.hpp / settings.cpp
└── state/
    └── engine.hpp / engine.cpp      ← FSM состояний
```

---

## 10. Зависимости (C++)

| Библиотека | Назначение | Подключение |
|-----------|-----------|-------------|
| miniaudio | Захват аудио | header-only |
| whisper.cpp | STT | git submodule |
| piper | TTS | git submodule |
| onnxruntime | VAD + Wake-word (ONNX модели) | CMake FetchContent |
| rapidfuzz-cpp | Классификатор команд (fuzzy matching) | header-only |
| libzmq + cppzmq | IPC с Python агентом | CMake FetchContent |
| websocketpp | IPC с GUI | header-only |
| toml++ | Парсинг конфигов | header-only |
| nlohmann/json | JSON для IPC | header-only |

**Сравнение с предыдущим стеком:**

| Что изменилось | Было | Стало |
|---|---|---|
| Wake-word | Whisper tiny (~150 MB RAM) | openWakeWord ONNX (~15 MB RAM) |
| VAD | Energy RMS (ненадёжный) | Silero VAD ONNX (точный) |
| Classifier | all-MiniLM-L6-v2 (английский) | rapidfuzz (русский, быстрее) |
| Agent IPC | WebSocket | ZeroMQ PUSH/PULL |
| GUI IPC | WebSocket | WebSocket (без изменений) |
| Ghost Touch shutdown | kill process | Graceful via WS signal |
