#pragma once

#include <functional>
#include <string>
#include <vector>
#include <atomic>
#include <thread>
#include <cstdint>

// Источник аудио
enum class AudioSource { MICROPHONE, UDP };

// ─────────────────────────────────────────────────────────────
// AudioCapture — два режима:
//   MICROPHONE — miniaudio (локальный микрофон)
//   UDP        — приём int16 PCM от ESP32 по UDP (порт 9720)
//
// В обоих случаях вызывает SampleCallback каждые CHUNK_FRAMES
// сэмплов float32 PCM 16kHz моно.
// ─────────────────────────────────────────────────────────────
class AudioCapture {
public:
    static constexpr int CHUNK_FRAMES = 512;
    static constexpr int SAMPLE_RATE  = 16000;
    static constexpr int CHANNELS     = 1;

    using SampleCallback = std::function<void(const float* samples, size_t count)>;

    // Режим 1: локальный микрофон (miniaudio)
    explicit AudioCapture(SampleCallback callback);

    // Режим 2: UDP стрим от ESP32
    AudioCapture(SampleCallback callback, AudioSource source, uint16_t port = 9720);

    ~AudioCapture();

    AudioCapture(const AudioCapture&)            = delete;
    AudioCapture& operator=(const AudioCapture&) = delete;

    // MICROPHONE: deviceName = "default" или имя из listDevices()
    // UDP: deviceName игнорируется
    bool start(const std::string& deviceName = "default");
    void stop();

    bool isRunning() const { return running_; }

    // Список доступных микрофонов (только в режиме MICROPHONE)
    std::vector<std::string> listDevices();

    // Вызывается из miniaudio callback (должен быть public)
    void onAudioData(const float* samples, size_t count);

private:
    void udpLoop();   // поток приёма UDP

    SampleCallback    callback_;
    std::atomic<bool> running_{false};
    AudioSource       source_  = AudioSource::MICROPHONE;
    uint16_t          udpPort_ = 9720;

    // Microphone mode: ma_device хранится как void*
    void* device_ = nullptr;

    // UDP mode
    std::thread        udpThread_;
    intptr_t           udpSocket_ = -1;
    std::vector<float> accumBuf_;  // накапливает сэмплы до CHUNK_FRAMES
};
