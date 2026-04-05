// miniaudio — реализацию включаем один раз здесь
#define MINIAUDIO_IMPLEMENTATION
#include "miniaudio.h"
#include "capture.hpp"

#include <cstring>
#include <iostream>
#include <stdexcept>

// ─────────────────────────────────────────────────────────────
// Платформо-зависимые сокеты
// ─────────────────────────────────────────────────────────────
#ifdef _WIN32
#  include <winsock2.h>
#  include <ws2tcpip.h>
   using socket_t = SOCKET;
#  define INVALID_SOCK  INVALID_SOCKET
#  define CLOSE_SOCK(s) closesocket(s)
#else
#  include <sys/socket.h>
#  include <netinet/in.h>
#  include <arpa/inet.h>
#  include <unistd.h>
#  include <fcntl.h>
   using socket_t = int;
#  define INVALID_SOCK  (-1)
#  define CLOSE_SOCK(s) ::close(s)
#endif

// ─────────────────────────────────────────────────────────────
// miniaudio callback
// ─────────────────────────────────────────────────────────────
static void maDataCallback(ma_device* pDevice, void* /*pOutput*/,
                           const void* pInput, ma_uint32 frameCount)
{
    auto* self = static_cast<AudioCapture*>(pDevice->pUserData);
    if (!self || !pInput) return;
    self->onAudioData(static_cast<const float*>(pInput),
                      static_cast<size_t>(frameCount));
}

// ─────────────────────────────────────────────────────────────
// Конструкторы / деструктор
// ─────────────────────────────────────────────────────────────
AudioCapture::AudioCapture(SampleCallback callback)
    : callback_(std::move(callback)), source_(AudioSource::MICROPHONE)
{
    device_ = new ma_device();
}

AudioCapture::AudioCapture(SampleCallback callback,
                           AudioSource source, uint16_t port)
    : callback_(std::move(callback)), source_(source), udpPort_(port)
{
    if (source_ == AudioSource::MICROPHONE)
        device_ = new ma_device();
}

AudioCapture::~AudioCapture()
{
    stop();
    if (device_) {
        delete static_cast<ma_device*>(device_);
        device_ = nullptr;
    }
}

// ─────────────────────────────────────────────────────────────
// Общий onAudioData — вызывается в обоих режимах
// ─────────────────────────────────────────────────────────────
void AudioCapture::onAudioData(const float* samples, size_t count)
{
    if (running_ && callback_) callback_(samples, count);
}

// ─────────────────────────────────────────────────────────────
// start() — запускает нужный режим
// ─────────────────────────────────────────────────────────────
bool AudioCapture::start(const std::string& deviceName)
{
    if (running_) return true;

    if (source_ == AudioSource::UDP) {
        // ── UDP режим ──────────────────────────────────────────
#ifdef _WIN32
        WSADATA wsa;
        if (WSAStartup(MAKEWORD(2,2), &wsa) != 0) {
            std::cerr << "[AudioCapture] WSAStartup failed\n";
            return false;
        }
#endif
        socket_t sock = socket(AF_INET, SOCK_DGRAM, IPPROTO_UDP);
        if (sock == INVALID_SOCK) {
            std::cerr << "[AudioCapture] Не удалось создать UDP сокет\n";
            return false;
        }

        // Таймаут 100ms — чтобы поток мог проверять running_
#ifdef _WIN32
        DWORD tv = 100;
        setsockopt(sock, SOL_SOCKET, SO_RCVTIMEO,
                   reinterpret_cast<const char*>(&tv), sizeof(tv));
#else
        struct timeval tv{0, 100000};
        setsockopt(sock, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof(tv));
#endif

        sockaddr_in addr{};
        addr.sin_family      = AF_INET;
        addr.sin_addr.s_addr = INADDR_ANY;
        addr.sin_port        = htons(udpPort_);

        if (bind(sock, reinterpret_cast<sockaddr*>(&addr), sizeof(addr)) != 0) {
            std::cerr << "[AudioCapture] Bind UDP port " << udpPort_ << " failed\n";
            CLOSE_SOCK(sock);
            return false;
        }

        udpSocket_ = static_cast<intptr_t>(sock);
        running_   = true;
        accumBuf_.reserve(CHUNK_FRAMES);

        udpThread_ = std::thread(&AudioCapture::udpLoop, this);

        std::cout << "[AudioCapture] UDP режим — слушаю порт " << udpPort_ << "\n";
        std::cout << "[AudioCapture] " << SAMPLE_RATE
                  << " Hz, " << CHANNELS << " ch, "
                  << CHUNK_FRAMES << " frames/chunk\n";
        return true;
    }

    // ── Микрофон (miniaudio) ───────────────────────────────────
    auto* dev = static_cast<ma_device*>(device_);

    ma_device_config config  = ma_device_config_init(ma_device_type_capture);
    config.capture.format    = ma_format_f32;
    config.capture.channels  = CHANNELS;
    config.sampleRate        = SAMPLE_RATE;
    config.periodSizeInFrames = CHUNK_FRAMES;
    config.dataCallback      = maDataCallback;
    config.pUserData         = this;

    if (deviceName != "default") {
        ma_context ctx;
        if (ma_context_init(nullptr, 0, nullptr, &ctx) == MA_SUCCESS) {
            ma_device_info* infos;
            ma_uint32 count = 0;
            if (ma_context_get_devices(&ctx, nullptr, nullptr,
                                       &infos, &count) == MA_SUCCESS) {
                for (ma_uint32 i = 0; i < count; ++i) {
                    if (std::string(infos[i].name).find(deviceName)
                            != std::string::npos) {
                        config.capture.pDeviceID = &infos[i].id;
                        break;
                    }
                }
            }
            ma_context_uninit(&ctx);
        }
    }

    if (ma_device_init(nullptr, &config, dev) != MA_SUCCESS) {
        std::cerr << "[AudioCapture] Ошибка инициализации устройства\n";
        return false;
    }

    std::cout << "[AudioCapture] Устройство: " << dev->capture.name << "\n";
    std::cout << "[AudioCapture] " << SAMPLE_RATE << " Hz, "
              << CHANNELS << " ch, " << CHUNK_FRAMES << " frames/chunk\n";

    if (ma_device_start(dev) != MA_SUCCESS) {
        std::cerr << "[AudioCapture] Ошибка запуска устройства\n";
        ma_device_uninit(dev);
        return false;
    }

    running_ = true;
    return true;
}

// ─────────────────────────────────────────────────────────────
// stop()
// ─────────────────────────────────────────────────────────────
void AudioCapture::stop()
{
    if (!running_) return;
    running_ = false;

    if (source_ == AudioSource::UDP) {
        if (udpThread_.joinable()) udpThread_.join();
        if (udpSocket_ != -1) {
            CLOSE_SOCK(static_cast<socket_t>(udpSocket_));
            udpSocket_ = -1;
        }
#ifdef _WIN32
        WSACleanup();
#endif
        return;
    }

    auto* dev = static_cast<ma_device*>(device_);
    ma_device_stop(dev);
    ma_device_uninit(dev);
}

// ─────────────────────────────────────────────────────────────
// udpLoop() — поток приёма UDP пакетов от ESP32
//
// ESP32 шлёт пакеты: 256 × int16_t (512 байт) при 16kHz
// Конвертируем int16 → float32 (/32768.0f) и накапливаем
// до CHUNK_FRAMES, затем вызываем callback.
// ─────────────────────────────────────────────────────────────
void AudioCapture::udpLoop()
{
    // Максимальный размер пакета (256 int16 = 512 байт)
    constexpr int MAX_PACKET = 4096;
    uint8_t buf[MAX_PACKET];

    while (running_) {
        int n = recv(static_cast<socket_t>(udpSocket_),
                     reinterpret_cast<char*>(buf), MAX_PACKET, 0);
        if (n <= 0) continue;  // таймаут или ошибка — проверяем running_

        // Количество int16_t сэмплов в пакете
        int samples = n / static_cast<int>(sizeof(int16_t));
        auto* pcm   = reinterpret_cast<int16_t*>(buf);

        // Конвертируем int16 → float32 и добавляем в накопитель
        for (int i = 0; i < samples; ++i) {
            accumBuf_.push_back(pcm[i] / 32768.0f);

            if (static_cast<int>(accumBuf_.size()) == CHUNK_FRAMES) {
                onAudioData(accumBuf_.data(), CHUNK_FRAMES);
                accumBuf_.clear();
            }
        }
    }
}

// ─────────────────────────────────────────────────────────────
// listDevices() — только для режима MICROPHONE
// ─────────────────────────────────────────────────────────────
std::vector<std::string> AudioCapture::listDevices()
{
    std::vector<std::string> names;
    if (source_ == AudioSource::UDP) return names;

    ma_context ctx;
    if (ma_context_init(nullptr, 0, nullptr, &ctx) != MA_SUCCESS) return names;

    ma_device_info* infos;
    ma_uint32 count = 0;
    if (ma_context_get_devices(&ctx, nullptr, nullptr, &infos, &count) == MA_SUCCESS) {
        for (ma_uint32 i = 0; i < count; ++i)
            names.emplace_back(infos[i].name);
    }

    ma_context_uninit(&ctx);
    return names;
}
