#include "stt.hpp"
#include "vosk_api.h"

#include <algorithm>
#include <iostream>
#include <stdexcept>
#include <cstdint>

// ─────────────────────────────────────────────────────────────
// Извлечь поле "text" из JSON результата Vosk.
// Формат: {"text": "привет мир"}
// ─────────────────────────────────────────────────────────────
static std::string extractText(const char* json)
{
    if (!json) return "";
    const std::string s(json);
    const auto key = s.find("\"text\"");
    if (key == std::string::npos) return "";
    const auto q1 = s.find('"', key + 6);
    if (q1 == std::string::npos) return "";
    const auto q2 = s.find('"', q1 + 1);
    if (q2 == std::string::npos) return "";
    return s.substr(q1 + 1, q2 - q1 - 1);
}

// ─────────────────────────────────────────────────────────────
SpeechToText::SpeechToText(const std::string& modelPath,
                           const std::string& /*language*/)
{
    model_ = vosk_model_new(modelPath.c_str());
    if (!model_)
        throw std::runtime_error("[STT] Не удалось загрузить модель: " + modelPath);

    rec_ = vosk_recognizer_new(
               static_cast<VoskModel*>(model_), 16000.0f);
    if (!rec_) {
        vosk_model_free(static_cast<VoskModel*>(model_));
        throw std::runtime_error("[STT] Не удалось создать Vosk recognizer");
    }

    std::cout << "[STT] Vosk загружен: " << modelPath << "\n";
}

SpeechToText::~SpeechToText()
{
    if (rec_)   vosk_recognizer_free(static_cast<VoskRecognizer*>(rec_));
    if (model_) vosk_model_free(static_cast<VoskModel*>(model_));
}

std::string SpeechToText::transcribe(const std::vector<float>& audio)
{
    if (!rec_ || audio.empty()) return "";

    // float32 → int16
    std::vector<int16_t> pcm(audio.size());
    for (size_t i = 0; i < audio.size(); ++i) {
        const float s = std::clamp(audio[i], -1.0f, 1.0f);
        pcm[i] = static_cast<int16_t>(s * 32767.0f);
    }

    auto* rec = static_cast<VoskRecognizer*>(rec_);

    vosk_recognizer_accept_waveform_s(
        rec, pcm.data(), static_cast<int>(pcm.size()));

    const char* result = vosk_recognizer_final_result(rec);
    vosk_recognizer_reset(rec);  // сбросить состояние для следующей фразы

    return extractText(result);
}
