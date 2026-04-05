//  Jarvis Robot — ESP32-CAM Video Stream
//  OV2640 → HTTP MJPEG → Laptop
//
//  Плата: AI Thinker ESP32-CAM
//  В Arduino IDE выбери: Tools → Board → ESP32 Dev Module
//                        Tools → Partition Scheme → Huge APP (3MB No OTA)

#include <WiFi.h>
#include <WebServer.h>
#include "esp_camera.h"

// ─── Настройки WiFi ──────────────────────────────────────────
const char* WIFI_SSID = "Comnet4/9";
const char* WIFI_PASS = "Shaislamov1967";

// ─── Пины камеры AI Thinker ESP32-CAM ────────────────────────
#define CAM_PIN_PWDN    32
#define CAM_PIN_RESET   -1
#define CAM_PIN_XCLK     0
#define CAM_PIN_SIOD    26
#define CAM_PIN_SIOC    27
#define CAM_PIN_D7      35
#define CAM_PIN_D6      34
#define CAM_PIN_D5      39
#define CAM_PIN_D4      36
#define CAM_PIN_D3      21
#define CAM_PIN_D2      19
#define CAM_PIN_D1      18
#define CAM_PIN_D0       5
#define CAM_PIN_VSYNC   25
#define CAM_PIN_HREF    23
#define CAM_PIN_PCLK    22

#define FLASH_LED_PIN    4  // встроенный flash LED

WebServer server(80);

// ═════════════════════════════════════════════════════════════
// Инициализация камеры
// ═════════════════════════════════════════════════════════════

bool setupCamera() {
    camera_config_t config;
    config.ledc_channel = LEDC_CHANNEL_0;
    config.ledc_timer   = LEDC_TIMER_0;
    config.pin_d0       = CAM_PIN_D0;
    config.pin_d1       = CAM_PIN_D1;
    config.pin_d2       = CAM_PIN_D2;
    config.pin_d3       = CAM_PIN_D3;
    config.pin_d4       = CAM_PIN_D4;
    config.pin_d5       = CAM_PIN_D5;
    config.pin_d6       = CAM_PIN_D6;
    config.pin_d7       = CAM_PIN_D7;
    config.pin_xclk     = CAM_PIN_XCLK;
    config.pin_pclk     = CAM_PIN_PCLK;
    config.pin_vsync    = CAM_PIN_VSYNC;
    config.pin_href     = CAM_PIN_HREF;
    config.pin_sccb_sda = CAM_PIN_SIOD;
    config.pin_sccb_scl = CAM_PIN_SIOC;
    config.pin_pwdn     = CAM_PIN_PWDN;
    config.pin_reset    = CAM_PIN_RESET;
    config.xclk_freq_hz = 20000000;
    config.pixel_format = PIXFORMAT_JPEG;

    // VGA (640x480) — достаточно для идентификации лиц
    config.frame_size   = FRAMESIZE_VGA;
    config.jpeg_quality = 10;   // 0–63, меньше = лучше качество
    config.fb_count     = 2;
    config.grab_mode    = CAMERA_GRAB_LATEST;

    esp_err_t err = esp_camera_init(&config);
    if (err != ESP_OK) {
        Serial.printf("[Camera] Ошибка инициализации: 0x%x\n", err);
        return false;
    }

    // Настройки сенсора
    sensor_t* s = esp_camera_sensor_get();
    s->set_brightness(s, 0);
    s->set_contrast(s, 0);
    s->set_saturation(s, 0);
    s->set_whitebal(s, 1);
    s->set_awb_gain(s, 1);
    s->set_exposure_ctrl(s, 1);

    Serial.println("[Camera] OV2640 инициализирована (QVGA 320x240)");
    return true;
}

// ═════════════════════════════════════════════════════════════
// HTTP MJPEG стрим
// ═════════════════════════════════════════════════════════════

void handleStream() {
    WiFiClient client = server.client();

    // MJPEG заголовок
    client.println("HTTP/1.1 200 OK");
    client.println("Content-Type: multipart/x-mixed-replace; boundary=frame");
    client.println("Access-Control-Allow-Origin: *");
    client.println();

    Serial.println("[Stream] Клиент подключился: " + client.remoteIP().toString());

    while (client.connected()) {
        camera_fb_t* fb = esp_camera_fb_get();
        if (!fb) {
            Serial.println("[Stream] Ошибка захвата кадра");
            break;
        }

        client.printf("--frame\r\n");
        client.printf("Content-Type: image/jpeg\r\n");
        client.printf("Content-Length: %u\r\n\r\n", fb->len);
        client.write(fb->buf, fb->len);
        client.printf("\r\n");

        esp_camera_fb_return(fb);

        // ~20 FPS
        delay(50);
    }

    Serial.println("[Stream] Клиент отключился");
}

// Статус страница
void handleRoot() {
    String html = "<html><body>";
    html += "<h2>Jarvis Robot Camera</h2>";
    html += "<img src='/stream' style='width:640px'><br>";
    html += "<p>Stream: <a href='/stream'>http://" + WiFi.localIP().toString() + "/stream</a></p>";
    html += "</body></html>";
    server.send(200, "text/html", html);
}

// Управление flash LED
void handleFlash() {
    if (server.hasArg("on")) {
        digitalWrite(FLASH_LED_PIN, HIGH);
        server.send(200, "text/plain", "flash on");
    } else {
        digitalWrite(FLASH_LED_PIN, LOW);
        server.send(200, "text/plain", "flash off");
    }
}

// ═════════════════════════════════════════════════════════════
// SETUP / LOOP
// ═════════════════════════════════════════════════════════════

void setup() {
    Serial.begin(115200);
    delay(500);
    Serial.println("\n[Jarvis Robot CAM] Старт...");

    pinMode(FLASH_LED_PIN, OUTPUT);
    digitalWrite(FLASH_LED_PIN, LOW);

    if (!setupCamera()) {
        Serial.println("[FATAL] Камера не запустилась — проверь подключение");
        return;
    }

    // WiFi
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

    // HTTP маршруты
    server.on("/",       handleRoot);
    server.on("/stream", handleStream);
    server.on("/flash",  handleFlash);
    server.begin();

    Serial.println("[HTTP] Сервер запущен");
    Serial.println("[Jarvis Robot CAM] Готов!");
    Serial.println("  Браузер: http://" + WiFi.localIP().toString());
    Serial.println("  Стрим:   http://" + WiFi.localIP().toString() + "/stream");
    Serial.println("  Flash:   http://" + WiFi.localIP().toString() + "/flash?on");
}

void loop() {
    server.handleClient();
}
