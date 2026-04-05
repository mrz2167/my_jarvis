//  Jarvis Robot — ESP32 Audio Stream + Motor Control
//
//  INMP441 (I2S микрофон):
//    SD  → GPIO32  (data)
//    SCK → GPIO14  (clock)
//    WS  → GPIO15  (word select)
//    L/R → GND     (левый канал)
//    VDD → 3.3V
//    GND → GND
//
//  L298N (драйвер моторов):
//    ENA → GPIO25  (PWM скорость, мотор A — левый)
//    IN1 → GPIO26  (направление мотор A)
//    IN2 → GPIO27  (направление мотор A)
//    ENB → GPIO33  (PWM скорость, мотор B — правый)
//    IN3 → GPIO18  (направление мотор B)
//    IN4 → GPIO19  (направление мотор B)
//    12V → питание моторов
//    GND → общая земля с ESP32

#include <WiFi.h>
#include <WiFiUdp.h>
#include <driver/i2s.h>

// ─── Настройки WiFi ──────────────────────────────────────────
const char* WIFI_SSID = "Comnet4/9";
const char* WIFI_PASS = "Shaislamov1967";

// ─── Адрес ноутбука ──────────────────────────────────────────
const char* LAPTOP_IP  = "192.168.1.104";
const int   AUDIO_PORT = 9720;
const int   CMD_PORT   = 9721;

// ─── Пины I2S (INMP441) ──────────────────────────────────────
#define PIN_I2S_SCK   14
#define PIN_I2S_WS    15
#define PIN_I2S_SD    32

// ─── Пины L298N ──────────────────────────────────────────────
#define PIN_ENA   25   // PWM мотор A (левый)
#define PIN_IN1   26
#define PIN_IN2   27
#define PIN_ENB   33   // PWM мотор B (правый)
#define PIN_IN3   18
#define PIN_IN4   19

// ─── Параметры аудио ─────────────────────────────────────────
#define SAMPLE_RATE     16000
#define BUFFER_SAMPLES  256

// ─── Параметры PWM ───────────────────────────────────────────
#define PWM_FREQ      1000
#define PWM_RES       8       // 8-bit: 0–255
#define DEFAULT_SPEED 180     // 0–255

WiFiUDP udp;

// ═════════════════════════════════════════════════════════════
// МОТОРЫ
// ═════════════════════════════════════════════════════════════

void setupMotors() {
    // ESP32 Arduino core 3.x — новый API: ledcAttach(pin, freq, resolution)
    ledcAttach(PIN_ENA, PWM_FREQ, PWM_RES);
    ledcAttach(PIN_ENB, PWM_FREQ, PWM_RES);

    // Пины направления
    pinMode(PIN_IN1, OUTPUT);
    pinMode(PIN_IN2, OUTPUT);
    pinMode(PIN_IN3, OUTPUT);
    pinMode(PIN_IN4, OUTPUT);

    // Старт — стоп
    motorStop();
    Serial.println("[Motors] L298N инициализирован");
}

// Мотор A (левый)
void motorA(bool forward, int speed) {
    ledcWrite(PIN_ENA, speed);
    digitalWrite(PIN_IN1, forward ? HIGH : LOW);
    digitalWrite(PIN_IN2, forward ? LOW  : HIGH);
}

// Мотор B (правый)
void motorB(bool forward, int speed) {
    ledcWrite(PIN_ENB, speed);
    digitalWrite(PIN_IN3, forward ? HIGH : LOW);
    digitalWrite(PIN_IN4, forward ? LOW  : HIGH);
}

void motorForward(int speed = DEFAULT_SPEED) {
    motorA(true,  speed);
    motorB(true,  speed);
    Serial.println("[Motors] ВПЕРЁД (speed=" + String(speed) + ")");
}

void motorBackward(int speed = DEFAULT_SPEED) {
    motorA(false, speed);
    motorB(false, speed);
    Serial.println("[Motors] НАЗАД (speed=" + String(speed) + ")");
}

void motorLeft(int speed = DEFAULT_SPEED) {
    motorA(false, speed);   // левый назад
    motorB(true,  speed);   // правый вперёд
    Serial.println("[Motors] ВЛЕВО (speed=" + String(speed) + ")");
}

void motorRight(int speed = DEFAULT_SPEED) {
    motorA(true,  speed);   // левый вперёд
    motorB(false, speed);   // правый назад
    Serial.println("[Motors] ВПРАВО (speed=" + String(speed) + ")");
}

void motorStop() {
    ledcWrite(PIN_ENA, 0);
    ledcWrite(PIN_ENB, 0);
    digitalWrite(PIN_IN1, LOW);
    digitalWrite(PIN_IN2, LOW);
    digitalWrite(PIN_IN3, LOW);
    digitalWrite(PIN_IN4, LOW);
    Serial.println("[Motors] СТОП");
}

// ═════════════════════════════════════════════════════════════
// КОМАНДЫ (парсинг JSON без библиотек)
// Формат: {"cmd":"forward","speed":180}
// ═════════════════════════════════════════════════════════════

// Простое извлечение строкового значения из JSON
String jsonGetString(const char* json, const char* key) {
    String s = String(json);
    String k = "\"" + String(key) + "\":\"";
    int i = s.indexOf(k);
    if (i < 0) return "";
    i += k.length();
    int j = s.indexOf("\"", i);
    return s.substring(i, j);
}

// Простое извлечение числового значения из JSON
int jsonGetInt(const char* json, const char* key, int def = DEFAULT_SPEED) {
    String s = String(json);
    String k = "\"" + String(key) + "\":";
    int i = s.indexOf(k);
    if (i < 0) return def;
    i += k.length();
    return s.substring(i).toInt();
}

void handleCommand(const char* json) {
    Serial.print("[CMD] ");
    Serial.println(json);

    String cmd   = jsonGetString(json, "cmd");
    int    speed = jsonGetInt(json, "speed");

    if      (cmd == "forward")  motorForward(speed);
    else if (cmd == "backward") motorBackward(speed);
    else if (cmd == "left")     motorLeft(speed);
    else if (cmd == "right")    motorRight(speed);
    else if (cmd == "stop")     motorStop();
    else {
        Serial.println("[CMD] Неизвестная команда: " + cmd);
    }
}

// ═════════════════════════════════════════════════════════════
// WiFi
// ═════════════════════════════════════════════════════════════

void setupWiFi() {
    Serial.print("[WiFi] Подключение к ");
    Serial.print(WIFI_SSID);
    WiFi.begin(WIFI_SSID, WIFI_PASS);
    while (WiFi.status() != WL_CONNECTED) {
        delay(500);
        Serial.print(".");
    }
    Serial.println();
    Serial.print("[WiFi] Подключено! IP: ");
    Serial.println(WiFi.localIP());
}

// ═════════════════════════════════════════════════════════════
// I2S
// ═════════════════════════════════════════════════════════════

void setupI2S() {
    i2s_config_t cfg = {
        .mode                 = (i2s_mode_t)(I2S_MODE_MASTER | I2S_MODE_RX),
        .sample_rate          = SAMPLE_RATE,
        .bits_per_sample      = I2S_BITS_PER_SAMPLE_32BIT,
        .channel_format       = I2S_CHANNEL_FMT_ONLY_LEFT,
        .communication_format = I2S_COMM_FORMAT_STAND_I2S,
        .intr_alloc_flags     = ESP_INTR_FLAG_LEVEL1,
        .dma_buf_count        = 3,
        .dma_buf_len          = BUFFER_SAMPLES,
        .use_apll             = false,
        .tx_desc_auto_clear   = false,
        .fixed_mclk           = 0
    };
    i2s_pin_config_t pins = {
        .bck_io_num   = PIN_I2S_SCK,
        .ws_io_num    = PIN_I2S_WS,
        .data_out_num = I2S_PIN_NO_CHANGE,
        .data_in_num  = PIN_I2S_SD
    };
    i2s_driver_install(I2S_NUM_0, &cfg, 0, NULL);
    i2s_set_pin(I2S_NUM_0, &pins);
    i2s_zero_dma_buffer(I2S_NUM_0);
    Serial.println("[I2S] Микрофон инициализирован (16kHz, моно)");
}

// ═════════════════════════════════════════════════════════════
// SETUP / LOOP
// ═════════════════════════════════════════════════════════════

void setup() {
    Serial.begin(115200);
    delay(500);
    Serial.println("\n[Jarvis Robot] Старт...");

    setupWiFi();
    setupMotors();
    setupI2S();

    udp.begin(CMD_PORT);
    Serial.println("[UDP] Слушаю команды на порту " + String(CMD_PORT));
    Serial.println("[UDP] Стримлю аудио на " + String(LAPTOP_IP) + ":" + String(AUDIO_PORT));
    Serial.println("[Jarvis Robot] Готов!");
}

void loop() {
    // ─── Аудио: читаем I2S и отправляем UDP ──────────────────
    int32_t raw[BUFFER_SAMPLES];
    size_t  bytesRead = 0;

    i2s_read(I2S_NUM_0, raw, sizeof(raw), &bytesRead, portMAX_DELAY);
    int samplesRead = bytesRead / sizeof(int32_t);

    int16_t pcm[BUFFER_SAMPLES];
    for (int i = 0; i < samplesRead; i++)
        pcm[i] = (int16_t)(raw[i] >> 11);

    udp.beginPacket(LAPTOP_IP, AUDIO_PORT);
    udp.write((uint8_t*)pcm, samplesRead * sizeof(int16_t));
    udp.endPacket();

    // ─── Команды: проверяем входящий UDP ─────────────────────
    int packetSize = udp.parsePacket();
    if (packetSize > 0) {
        char buf[128] = {0};
        udp.read(buf, sizeof(buf) - 1);
        handleCommand(buf);
    }
}
