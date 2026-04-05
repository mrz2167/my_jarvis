#pragma once

#include <functional>
#include <string>
#include <vector>
#include <deque>
#include <memory>

// Подавляем предупреждения ONNX Runtime
#ifdef _MSC_VER
#pragma warning(push)
#pragma warning(disable: 4996)
#endif
#include <onnxruntime_cxx_api.h>
#ifdef _MSC_VER
#pragma warning(pop)
#endif

// ─────────────────────────────────────────────────────────────
// SileroVAD — низкоуровневый враппер над ONNX моделью.
//
// Silero VAD v4 inputs:
//   input  : float32 [1, 512]   — аудио чанк (512 сэмплов при 16kHz)
//   sr     : int64   [1]        — sample rate (16000)
//   h      : float32 [2, 1, 64] — LSTM hidden state
//   c      : float32 [2, 1, 64] — LSTM cell state
//
// Silero VAD v4 outputs:
//   output : float32 [1, 1]     — вероятность речи 0..1
//   hn     : float32 [2, 1, 64] — новый hidden state
//   cn     : float32 [2, 1, 64] — новый cell state
// ─────────────────────────────────────────────────────────────
class SileroVAD {
public:
    static constexpr int CHUNK_SIZE = 512;   // сэмплов на чанк (16kHz)
    static constexpr int H_SIZE     = 128;   // 2 * 1 * 64 = 128 float (h или c)

    explicit SileroVAD(const std::string& modelPath, int sampleRate = 16000);

    // Обработать один чанк из CHUNK_SIZE сэмплов.
    // Возвращает вероятность речи [0.0, 1.0].
    float process(const float* samples);

    // Сбросить LSTM состояние (при начале новой сессии)
    void resetState();

private:
    Ort::Env env_;
    Ort::SessionOptions sessionOptions_;
    std::unique_ptr<Ort::Session> session_;
    Ort::MemoryInfo memInfo_;

    int sampleRate_;
    int64_t sampleRateI_;

    // LSTM состояние v4: раздельные h и c, каждый [2, 1, 64]
    std::vector<float> h_;   // hidden state
    std::vector<float> c_;   // cell state

    // Имена входов/выходов (читаются из модели при загрузке)
    std::vector<std::string> inputNames_;
    std::vector<std::string> outputNames_;
};

// ─────────────────────────────────────────────────────────────
// Конфигурация VoiceActivityDetector
// ─────────────────────────────────────────────────────────────
struct VadConfig {
    float threshold        = 0.5f;   // порог вероятности речи
    int   minSpeechMs      = 250;    // минимальная длина речи для захвата
    int   silenceTimeoutMs = 1200;   // тишина → конец фразы
    int   preBufferMs      = 150;    // буфер аудио ДО начала речи
    int   sampleRate       = 16000;
    int   chunkSize        = 512;
};

enum class VadState { IDLE, CAPTURING };

// ─────────────────────────────────────────────────────────────
// VoiceActivityDetector — FSM поверх SileroVAD.
//
// Принимает непрерывный поток сэмплов через feed().
// Когда обнаруживает полную фразу — вызывает onSpeech callback
// с буфером float32 аудио (preBuffer + captured audio).
// ─────────────────────────────────────────────────────────────
class VoiceActivityDetector {
public:
    // Вызывается когда фраза завершена. audio — float32 PCM 16kHz
    using SpeechCallback = std::function<void(std::vector<float> audio)>;

    VoiceActivityDetector(SileroVAD& vad, VadConfig config, SpeechCallback onSpeech);

    // Принять сэмплы от AudioCapture (вызывается из аудио-потока)
    void feed(const float* samples, size_t count);

    VadState state() const { return state_; }

private:
    // Обработать ровно один чанк (chunkSize сэмплов)
    void processChunk(const float* chunk);

    SileroVAD&     vad_;
    VadConfig      cfg_;
    SpeechCallback onSpeech_;
    VadState       state_ = VadState::IDLE;

    // Кольцевой пре-буфер (аудио до начала речи)
    std::deque<float> preBuffer_;
    // Буфер накопленной фразы
    std::vector<float> captureBuffer_;
    // Буфер для выравнивания входящих чанков по chunkSize
    std::vector<float> inputBuffer_;

    int speechFrameCount_  = 0;
    int silenceFrameCount_ = 0;

    // Пороги в количестве чанков (вычислены из ms при конструировании)
    int minSpeechChunks_;
    int silenceTimeoutChunks_;
    int preBufferChunks_;
};
