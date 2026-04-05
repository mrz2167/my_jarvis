#pragma once

#include <string>
#include <vector>

// ─────────────────────────────────────────────────────────────
// SpeechToText — синхронный транскрибер на базе Vosk.
//
// modelPath — путь к директории модели (vosk-model-ru-0.42/)
// Аудио: float32 PCM 16kHz моно (конвертируется в int16 внутри).
// ─────────────────────────────────────────────────────────────
class SpeechToText {
public:
    explicit SpeechToText(const std::string& modelPath,
                          const std::string& language = "ru");
    ~SpeechToText();

    SpeechToText(const SpeechToText&)            = delete;
    SpeechToText& operator=(const SpeechToText&) = delete;

    // Транскрибировать float32 PCM 16kHz.
    // Блокирующий вызов. Возвращает распознанный текст.
    std::string transcribe(const std::vector<float>& audio);

private:
    void* model_ = nullptr;  // VoskModel*
    void* rec_   = nullptr;  // VoskRecognizer*
};
