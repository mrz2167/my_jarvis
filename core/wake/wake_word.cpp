#include "wake_word.hpp"

#include <algorithm>
#include <iostream>
#include <stdexcept>

// ─────────────────────────────────────────────────────────────
// Helpers
// ─────────────────────────────────────────────────────────────

static std::unique_ptr<Ort::Session> makeSession(Ort::Env& env,
                                                  Ort::SessionOptions& opts,
                                                  const std::string& path)
{
#ifdef _WIN32
    std::wstring wp(path.begin(), path.end());
    return std::make_unique<Ort::Session>(env, wp.c_str(), opts);
#else
    return std::make_unique<Ort::Session>(env, path.c_str(), opts);
#endif
}

static std::vector<std::string> collectNames(Ort::Session& sess, bool inputs)
{
    Ort::AllocatorWithDefaultOptions alloc;
    std::vector<std::string> names;
    size_t n = inputs ? sess.GetInputCount() : sess.GetOutputCount();
    for (size_t i = 0; i < n; ++i) {
        auto ptr = inputs ? sess.GetInputNameAllocated(i, alloc)
                          : sess.GetOutputNameAllocated(i, alloc);
        names.emplace_back(ptr.get());
    }
    return names;
}

// ─────────────────────────────────────────────────────────────
// WakeWordDetector
// ─────────────────────────────────────────────────────────────

WakeWordDetector::WakeWordDetector(const std::string& melPath,
                                   const std::string& embPath,
                                   const std::string& wwPath,
                                   float threshold)
    : env_(ORT_LOGGING_LEVEL_WARNING, "WakeWord")
    , memInfo_(Ort::MemoryInfo::CreateCpu(OrtArenaAllocator, OrtMemTypeDefault))
    , threshold_(threshold)
{
    opts_.SetIntraOpNumThreads(1);
    opts_.SetGraphOptimizationLevel(GraphOptimizationLevel::ORT_ENABLE_ALL);

    melSess_ = makeSession(env_, opts_, melPath);
    embSess_ = makeSession(env_, opts_, embPath);
    wwSess_  = makeSession(env_, opts_, wwPath);

    melIn_  = collectNames(*melSess_, true);
    melOut_ = collectNames(*melSess_, false);
    embIn_  = collectNames(*embSess_, true);
    embOut_ = collectNames(*embSess_, false);
    wwIn_   = collectNames(*wwSess_,  true);
    wwOut_  = collectNames(*wwSess_,  false);

    // Query wake word model sequence length from shape [1, seqLen, 96]
    auto wwShape = wwSess_->GetInputTypeInfo(0)
                            .GetTensorTypeAndShapeInfo()
                            .GetShape();
    if (wwShape.size() >= 2 && wwShape[1] > 0)
        wwSeqLen_ = (int)wwShape[1];

    // Log actual model shapes for diagnostics
    auto logShape = [](const std::string& tag, Ort::Session& sess, bool input, size_t idx) {
        auto info = input ? sess.GetInputTypeInfo(idx).GetTensorTypeAndShapeInfo()
                          : sess.GetOutputTypeInfo(idx).GetTensorTypeAndShapeInfo();
        auto shape = info.GetShape();
        std::cout << "[WakeWord]   " << tag << " shape: [";
        for (size_t i = 0; i < shape.size(); ++i)
            std::cout << (i ? "," : "") << shape[i];
        std::cout << "]\n";
    };

    std::cout << "[WakeWord] mel: \"" << melIn_[0] << "\" → \"" << melOut_[0] << "\"\n";
    logShape("mel_in",  *melSess_, true,  0);
    logShape("mel_out", *melSess_, false, 0);

    std::cout << "[WakeWord] emb: \"" << embIn_[0] << "\" → \"" << embOut_[0] << "\"\n";
    logShape("emb_in",  *embSess_, true,  0);
    logShape("emb_out", *embSess_, false, 0);

    std::cout << "[WakeWord] ww:  \"" << wwIn_[0] << "\" → \"" << wwOut_[0]
              << "\" (seq=" << wwSeqLen_ << ")\n";
    logShape("ww_in",  *wwSess_, true,  0);
    logShape("ww_out", *wwSess_, false, 0);

    int warmupMs = (MEL_FRAMES + wwSeqLen_) * CHUNK / 16;
    std::cout << "[WakeWord] Прогрев ~" << warmupMs << " мс до первой детекции\n";
}

void WakeWordDetector::reset()
{
    audioBuf_.clear();
    melBuf_.clear();
    embBuf_.clear();
}

float WakeWordDetector::feed(const float* samples, size_t count)
{
    float lastScore = 0.0f;
    try {
        audioBuf_.insert(audioBuf_.end(), samples, samples + count);

        while (audioBuf_.size() >= CHUNK) {
            size_t melBefore = melBuf_.size();
            runMelChunk(audioBuf_.data());
            audioBuf_.erase(audioBuf_.begin(), audioBuf_.begin() + CHUNK);

            // One-time log: how many frames does mel produce per chunk?
            static bool melFramesLogged = false;
            if (!melFramesLogged && melBuf_.size() > melBefore) {
                std::cout << "[WakeWord] mel frames per chunk: "
                          << (melBuf_.size() - melBefore) << "\n";
                melFramesLogged = true;
            }

            // One-time log: mel buffer full
            static bool melFullLogged = false;
            if (!melFullLogged && (int)melBuf_.size() >= MEL_FRAMES) {
                std::cout << "[WakeWord] mel buffer full (" << MEL_FRAMES << " frames) — starting embeddings\n";
                melFullLogged = true;
            }

            if ((int)melBuf_.size() >= MEL_FRAMES) {
                runEmbedding();

                // One-time log: emb buffer full
                static bool embFullLogged = false;
                if (!embFullLogged && (int)embBuf_.size() >= wwSeqLen_) {
                    std::cout << "[WakeWord] emb buffer full (" << wwSeqLen_ << ") — wake word active!\n";
                    embFullLogged = true;
                }

                if ((int)embBuf_.size() == wwSeqLen_) {
                    lastScore = runWakeWord();

                    // Log every ~2 sec (every 25 detections) and any score > 0.05
                    static int scoreTick = 0;
                    bool periodic = (++scoreTick % 25 == 0);
                    if (periodic || lastScore > 0.05f) {
                        std::cout << "[WakeWord] score=" << lastScore
                                  << (lastScore >= threshold_ ? " *** DETECTED ***" : "")
                                  << "\n";
                    }
                    if (lastScore >= threshold_ && callback_)
                        callback_(lastScore);
                }
            }
        }
    } catch (const Ort::Exception& e) {
        std::cerr << "[WakeWord] ONNX error: " << e.what() << "\n";
        reset();
    } catch (const std::exception& e) {
        std::cerr << "[WakeWord] Error: " << e.what() << "\n";
        reset();
    }
    return lastScore;
}

// ─────────────────────────────────────────────────────────────
// Stage 1: melspectrogram — [1, samples] → [1, 1, N_frames, 32]
// The model outputs N mel frames per call (N = samples / hop_length).
// All frames are pushed into the sliding window buffer.
//
// NOTE: openWakeWord was trained on int16 audio. We scale float32
// from [-1, 1] to [-32768, 32767] before inference.
// ─────────────────────────────────────────────────────────────
void WakeWordDetector::runMelChunk(const float* chunk)
{
    // Scale to int16 range expected by the model
    std::array<float, CHUNK> scaled;
    for (int i = 0; i < CHUNK; ++i)
        scaled[i] = chunk[i] * 32768.0f;

    std::array<int64_t, 2> shape = {1, CHUNK};
    auto tensor = Ort::Value::CreateTensor<float>(
        memInfo_, scaled.data(), CHUNK,
        shape.data(), shape.size());

    const char* inName  = melIn_[0].c_str();
    const char* outName = melOut_[0].c_str();
    auto out = melSess_->Run(Ort::RunOptions{nullptr}, &inName, &tensor, 1, &outName, 1);

    // Output: [batch, 1, N_frames, 32] — extract all N frames
    const float* data = out[0].GetTensorData<float>();
    size_t total = out[0].GetTensorTypeAndShapeInfo().GetElementCount();
    size_t numFrames = total / MEL_BINS;  // each frame = MEL_BINS floats

    for (size_t f = 0; f < numFrames; ++f) {
        std::array<float, MEL_BINS> frame{};
        std::copy(data + f * MEL_BINS, data + (f + 1) * MEL_BINS, frame.begin());
        melBuf_.push_back(frame);
        if ((int)melBuf_.size() > MEL_FRAMES)
            melBuf_.pop_front();
    }
}

// ─────────────────────────────────────────────────────────────
// Stage 2: embedding — [76, 32, 1] → [1, 1, 1, 96]
// ─────────────────────────────────────────────────────────────
void WakeWordDetector::runEmbedding()
{
    std::vector<float> input;
    input.reserve(MEL_FRAMES * MEL_BINS);
    for (const auto& frame : melBuf_)
        for (float v : frame)
            input.push_back(v);

    // Keras CNN models expect [batch, height, width, channels] = [1, 76, 32, 1]
    std::array<int64_t, 4> shape = {1, MEL_FRAMES, MEL_BINS, 1};
    auto tensor = Ort::Value::CreateTensor<float>(
        memInfo_, input.data(), input.size(),
        shape.data(), shape.size());

    const char* inName  = embIn_[0].c_str();
    const char* outName = embOut_[0].c_str();
    auto out = embSess_->Run(Ort::RunOptions{nullptr}, &inName, &tensor, 1, &outName, 1);

    const float* data = out[0].GetTensorData<float>();
    size_t n = out[0].GetTensorTypeAndShapeInfo().GetElementCount();

    std::array<float, EMB_DIMS> emb{};
    std::copy(data, data + std::min(n, (size_t)EMB_DIMS), emb.begin());

    embBuf_.push_back(emb);
    if ((int)embBuf_.size() > wwSeqLen_)
        embBuf_.pop_front();
}

// ─────────────────────────────────────────────────────────────
// Stage 3: wake word — [1, seqLen, 96] → score
// ─────────────────────────────────────────────────────────────
float WakeWordDetector::runWakeWord()
{
    std::vector<float> input;
    input.reserve(wwSeqLen_ * EMB_DIMS);
    for (const auto& emb : embBuf_)
        for (float v : emb)
            input.push_back(v);

    std::array<int64_t, 3> shape = {1, (int64_t)wwSeqLen_, EMB_DIMS};
    auto tensor = Ort::Value::CreateTensor<float>(
        memInfo_, input.data(), input.size(),
        shape.data(), shape.size());

    const char* inName  = wwIn_[0].c_str();
    const char* outName = wwOut_[0].c_str();
    auto out = wwSess_->Run(Ort::RunOptions{nullptr}, &inName, &tensor, 1, &outName, 1);

    return out[0].GetTensorData<float>()[0];
}
