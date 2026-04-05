#include "vad.hpp"

#include <algorithm>
#include <cstring>
#include <iostream>
#include <stdexcept>

// ═══════════════════════════════════════════════════════════════
// SileroVAD
// ═══════════════════════════════════════════════════════════════

SileroVAD::SileroVAD(const std::string& modelPath, int sampleRate)
    : env_(ORT_LOGGING_LEVEL_WARNING, "SileroVAD")
    , memInfo_(Ort::MemoryInfo::CreateCpu(OrtArenaAllocator, OrtMemTypeDefault))
    , sampleRate_(sampleRate)
    , sampleRateI_((int64_t)sampleRate)
{
    sessionOptions_.SetIntraOpNumThreads(1);
    sessionOptions_.SetGraphOptimizationLevel(GraphOptimizationLevel::ORT_ENABLE_ALL);

#ifdef _WIN32
    std::wstring wPath(modelPath.begin(), modelPath.end());
    session_ = std::make_unique<Ort::Session>(env_, wPath.c_str(), sessionOptions_);
#else
    session_ = std::make_unique<Ort::Session>(env_, modelPath.c_str(), sessionOptions_);
#endif

    // Читаем имена входов/выходов из модели
    Ort::AllocatorWithDefaultOptions alloc;
    size_t numInputs  = session_->GetInputCount();
    size_t numOutputs = session_->GetOutputCount();

    std::cout << "[SileroVAD] Входы (" << numInputs << "): ";
    for (size_t i = 0; i < numInputs; ++i) {
        auto name = session_->GetInputNameAllocated(i, alloc);
        inputNames_.push_back(std::string(name.get()));
        std::cout << "\"" << name.get() << "\" ";
    }
    std::cout << "\n";

    std::cout << "[SileroVAD] Выходы (" << numOutputs << "): ";
    for (size_t i = 0; i < numOutputs; ++i) {
        auto name = session_->GetOutputNameAllocated(i, alloc);
        outputNames_.push_back(std::string(name.get()));
        std::cout << "\"" << name.get() << "\" ";
    }
    std::cout << "\n";

    resetState();
}

void SileroVAD::resetState()
{
    h_.assign(H_SIZE, 0.0f);  // [2, 1, 64]
    c_.assign(H_SIZE, 0.0f);  // [2, 1, 64]
}

float SileroVAD::process(const float* samples)
{
    // ─── Создаём все возможные тензоры заранее ──────────────

    // input: float32 [1, 512]
    std::array<int64_t, 2> inputShape = {1, CHUNK_SIZE};
    auto t_input = Ort::Value::CreateTensor<float>(
        memInfo_, const_cast<float*>(samples), CHUNK_SIZE,
        inputShape.data(), inputShape.size());

    // sr: int64 [1]
    std::array<int64_t, 1> srShape = {1};
    auto t_sr = Ort::Value::CreateTensor<int64_t>(
        memInfo_, &sampleRateI_, 1,
        srShape.data(), srShape.size());

    // h: float32 [2, 1, 64]
    std::array<int64_t, 3> hShape = {2, 1, 64};
    auto t_h = Ort::Value::CreateTensor<float>(
        memInfo_, h_.data(), H_SIZE,
        hShape.data(), hShape.size());

    // c: float32 [2, 1, 64]
    std::array<int64_t, 3> cShape = {2, 1, 64};
    auto t_c = Ort::Value::CreateTensor<float>(
        memInfo_, c_.data(), H_SIZE,
        cShape.data(), cShape.size());

    // ─── Собираем входы в порядке, который задаёт модель ────
    // Это критично: inNames[i] должен соответствовать inputs[i]
    std::vector<const char*> inNames;
    std::vector<Ort::Value>  inputs;

    for (const auto& name : inputNames_) {
        inNames.push_back(name.c_str());
        if      (name == "input") inputs.push_back(std::move(t_input));
        else if (name == "sr")    inputs.push_back(std::move(t_sr));
        else if (name == "h")     inputs.push_back(std::move(t_h));
        else if (name == "c")     inputs.push_back(std::move(t_c));
        else {
            std::cerr << "[SileroVAD] Неизвестный вход: \"" << name << "\"\n";
            return 0.0f;
        }
    }

    std::vector<const char*> outNames;
    for (const auto& name : outputNames_)
        outNames.push_back(name.c_str());

    // ─── Инференс ───────────────────────────────────────────
    auto outputs = session_->Run(
        Ort::RunOptions{nullptr},
        inNames.data(),  inputs.data(),  inNames.size(),
        outNames.data(), outNames.size()
    );

    // ─── Результат: первый выход — вероятность речи ─────────
    float probability = outputs[0].GetTensorMutableData<float>()[0];

    // ─── Обновить LSTM состояние по именам hn / cn ──────────
    for (size_t i = 0; i < outputNames_.size(); ++i) {
        const std::string& name = outputNames_[i];
        if (name == "hn") {
            const float* ptr = outputs[i].GetTensorMutableData<float>();
            std::copy(ptr, ptr + H_SIZE, h_.begin());
        } else if (name == "cn") {
            const float* ptr = outputs[i].GetTensorMutableData<float>();
            std::copy(ptr, ptr + H_SIZE, c_.begin());
        }
    }

    return probability;
}


// ═══════════════════════════════════════════════════════════════
// VoiceActivityDetector
// ═══════════════════════════════════════════════════════════════

VoiceActivityDetector::VoiceActivityDetector(SileroVAD& vad,
                                             VadConfig config,
                                             SpeechCallback onSpeech)
    : vad_(vad)
    , cfg_(config)
    , onSpeech_(std::move(onSpeech))
{
    float msPerChunk = (float)cfg_.chunkSize / (float)cfg_.sampleRate * 1000.f;

    minSpeechChunks_      = std::max(1, (int)(cfg_.minSpeechMs      / msPerChunk));
    silenceTimeoutChunks_ = std::max(1, (int)(cfg_.silenceTimeoutMs / msPerChunk));
    preBufferChunks_      = std::max(1, (int)(cfg_.preBufferMs      / msPerChunk));

    std::cout << "[VAD] threshold=" << cfg_.threshold
              << " minSpeech=" << minSpeechChunks_ << " chunks"
              << " silenceTimeout=" << silenceTimeoutChunks_ << " chunks"
              << " preBuffer=" << preBufferChunks_ << " chunks\n";
}

void VoiceActivityDetector::feed(const float* samples, size_t count)
{
    inputBuffer_.insert(inputBuffer_.end(), samples, samples + count);

    while (inputBuffer_.size() >= (size_t)cfg_.chunkSize) {
        try {
            processChunk(inputBuffer_.data());
        } catch (const Ort::Exception& e) {
            std::cerr << "[VAD] ONNX Runtime ошибка: " << e.what() << "\n";
        } catch (const std::exception& e) {
            std::cerr << "[VAD] Ошибка: " << e.what() << "\n";
        }
        inputBuffer_.erase(inputBuffer_.begin(),
                           inputBuffer_.begin() + cfg_.chunkSize);
    }
}

void VoiceActivityDetector::processChunk(const float* chunk)
{
    float prob = vad_.process(chunk);
    bool isSpeech = (prob >= cfg_.threshold);

    static int debugTick = 0;
    if (++debugTick % 31 == 0 || isSpeech) {
        float peak = 0.0f;
        for (int i = 0; i < cfg_.chunkSize; i++)
            peak = std::max(peak, std::abs(chunk[i]));
        std::cout << "[VAD] peak=" << peak
                  << " prob=" << prob
                  << " (" << (isSpeech ? "SPEECH" : "silence") << ")\n";
    }

    switch (state_) {

    case VadState::IDLE: {
        preBuffer_.insert(preBuffer_.end(), chunk, chunk + cfg_.chunkSize);
        while ((int)preBuffer_.size() > preBufferChunks_ * cfg_.chunkSize) {
            preBuffer_.erase(preBuffer_.begin(),
                             preBuffer_.begin() + cfg_.chunkSize);
        }

        if (isSpeech) {
            speechFrameCount_++;
            if (speechFrameCount_ >= minSpeechChunks_) {
                state_ = VadState::CAPTURING;
                silenceFrameCount_ = 0;
                captureBuffer_.assign(preBuffer_.begin(), preBuffer_.end());
                std::cout << "[VAD] SPEECH START (prob=" << prob << ")\n";
            }
        } else {
            speechFrameCount_ = 0;
        }
        break;
    }

    case VadState::CAPTURING: {
        captureBuffer_.insert(captureBuffer_.end(), chunk, chunk + cfg_.chunkSize);

        if (isSpeech) {
            silenceFrameCount_ = 0;
        } else {
            silenceFrameCount_++;
            if (silenceFrameCount_ >= silenceTimeoutChunks_) {
                float durationSec = (float)captureBuffer_.size() / (float)cfg_.sampleRate;
                std::cout << "[VAD] SPEECH END — " << durationSec << " сек, "
                          << captureBuffer_.size() << " сэмплов\n";

                if (onSpeech_) onSpeech_(std::move(captureBuffer_));
                captureBuffer_.clear();

                speechFrameCount_  = 0;
                silenceFrameCount_ = 0;
                preBuffer_.clear();
                state_ = VadState::IDLE;
                vad_.resetState();
            }
        }
        break;
    }

    } // switch
}
