# PLAN.md — Jarvis Robot

## Железо

| Устройство | Роль |
|-----------|------|
| Laptop (Kali Linux) | Jarvis Core — весь AI, обработка, принятие решений |
| ESP32 #2 | Микрофон (INMP441) + моторы (движение) |
| ESP32-CAM (#1) | Камера (OV2640) — только видео стрим |

---

## Сетевая архитектура (локальная сеть, WiFi)

```
[Laptop Kali Linux — Jarvis Core]
        ↑ UDP audio (16kHz PCM)      ← ESP32 #2
        ↓ UDP commands (JSON)        → ESP32 #2
        ↑ HTTP MJPEG stream          ← ESP32-CAM
```

### Протоколы

| Канал | Протокол | Порт | Почему |
|-------|----------|------|--------|
| Аудио ESP32 → Laptop | UDP raw PCM | 9720 | Минимальная задержка, потери не критичны |
| Команды Laptop → ESP32 | UDP JSON | 9721 | Простота, нет overhead |
| Статус ESP32 → Laptop | UDP JSON | 9722 | Состояние моторов, батарея |
| Видео ESP32-CAM → Laptop | HTTP MJPEG | 80 | Стандарт для ESP32-CAM |

---

## ESP32 #2 — Микрофон + Движение

### Микрофон
- **Модель:** INMP441 (I2S, цифровой, хорошее качество)
- **Подключение I2S:**
  ```
  INMP441  →  ESP32
  VDD      →  3.3V
  GND      →  GND
  SD       →  GPIO32  (data)
  SCK      →  GPIO14  (clock)
  WS       →  GPIO15  (word select / LRC)
  L/R      →  GND     (моно, левый канал)
  ```
- **Параметры:** 16kHz, моно, 16-bit PCM → отправляем как float32

### Моторы
- **Драйвер:** L298N или TB6612FNG
- **Команды (JSON по UDP):**
  ```json
  {"cmd": "move", "dir": "forward", "speed": 150}
  {"cmd": "move", "dir": "backward", "speed": 150}
  {"cmd": "move", "dir": "left", "speed": 100}
  {"cmd": "move", "dir": "right", "speed": 100}
  {"cmd": "stop"}
  {"cmd": "speak", "text": "готов"}
  ```

### Прошивка ESP32 #2 (план)
```
setup():
  - WiFi.begin(SSID, PASS)
  - I2S init (16kHz, моно)
  - UDP начать слушать порт 9721 (команды)
  - Моторы init

loop():
  - Читать I2S буфер (512 samples)
  - Конвертировать int16 → float32
  - UDP отправить на LAPTOP_IP:9720
  - Проверить UDP команды → выполнить движение
```

---

## ESP32-CAM (#1) — Видео

### Подключение
- Стандартная плата ESP32-CAM (AI-Thinker)
- OV2640 встроена
- Питание 5V (важно — 3.3V не хватает)

### Параметры стрима
- Разрешение: 320×240 (QVGA) — баланс качество/скорость
- FPS: 15-20
- Формат: MJPEG (встроенная поддержка в ESP32-CAM)

### Прошивка ESP32-CAM (план)
```
- WiFi.begin(SSID, PASS)
- Камера init (OV2640, QVGA, JPEG quality 10)
- Запустить HTTP MJPEG сервер на порту 80
- Laptop подключается: http://ESP32_CAM_IP/stream
```

---

## Laptop (Kali Linux) — Jarvis Core

### Что меняется в C++ коде

| Модуль | Изменение |
|--------|-----------|
| AudioCapture | Добавить режим UDP receiver вместо miniaudio mic |
| Jarvis Core | Добавить UDP command sender (порт 9721) |
| Видео | Опционально: OpenCV MJPEG клиент |

### AudioCapture — два режима
```cpp
// Режим 1: локальный микрофон (текущий)
AudioCapture capture(callback);

// Режим 2: UDP стрим от ESP32 (новый)
AudioCapture capture(callback, AudioSource::UDP, 9720);
```

---

## Статус реализации

### ESP32 #2 (mic + movement)
- [ ] Прошивка I2S микрофона (UDP audio sender)
- [ ] Прошивка моторов (UDP command receiver)
- [ ] Тест аудио качества

### ESP32-CAM
- [ ] Прошивка MJPEG стрима
- [ ] Тест стабильности

### Jarvis Core (Linux)
- [ ] Портировать CMakeLists.txt на Linux (ORT Linux build)
- [ ] UDP AudioCapture режим
- [ ] UDP command sender
- [ ] Тест сквозного пайплайна (ESP32 mic → VAD → STT)

---

## Зависимости для ESP32 (Arduino/PlatformIO)

```ini
; platformio.ini
[env:esp32]
platform = espressif32
board = esp32dev
framework = arduino
lib_deps =
    ; нет внешних библиотек — только ESP32 Arduino core
```

I2S и UDP встроены в ESP32 Arduino core — внешние библиотеки не нужны.

---

## IP адреса (пример конфига)

```cpp
// Задать статические IP в прошивках
#define LAPTOP_IP     "192.168.1.100"  // Jarvis Core
#define ESP32_IP      "192.168.1.101"  // mic + motors
#define ESP32_CAM_IP  "192.168.1.102"  // camera

#define AUDIO_PORT    9720
#define CMD_PORT      9721
#define STATUS_PORT   9722
```
