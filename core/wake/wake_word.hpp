#pragma once

#include <functional>
#include <string>
#include <vector>
#include <array>
#include <deque>
#include <memory>

#ifdef _MSC_VER
#pragma warning(push)
#pragma warning(disable: 4996)
#endif
#include <onnxruntime_cxx_api.h>
#ifdef _MSC_VER
#pragma warning(pop)
#endif

// ─────────────────────────────────────────────────────────────
// WakeWordDetector — openWakeWord ONNX three-stage pipeline:
//
//   Stage 1: melspectrogram.onnx
//     Input:  [1, 1280] float32  — 80ms of raw audio @ 16kHz
//     Output: [1, 1, 32] float32 — one mel frame (32 bins)
//
//   Stage 2: embedding_model.onnx
//     Input:  [76, 32, 1] float32 — sliding window of 76 mel frames
//     Output: [1, 1, 1, 96] float32 — 96-dim audio embedding
//
//   Stage 3: wake_word.onnx (e.g. hey_jarvis_v0.1.onnx)
//     Input:  [1, seqLen, 96] float32 — sliding window of embeddings
//     Output: score float32 in [0, 1]
//
// Sliding windows: after warmup (~7s), a new score is produced
// every 80ms (one per mel frame processed).
// ─────────────────────────────────────────────────────────────
class WakeWordDetector {
public:
    using WakeCallback = std::function<void(float score)>;

    WakeWordDetector(const std::string& melPath,
                     const std::string& embPath,
                     const std::string& wwPath,
                     float threshold = 0.5f);

    // Feed raw audio (16kHz mono float32).
    // Fires callback when score >= threshold. Returns latest score (0 if not yet warmed up).
    float feed(const float* samples, size_t count);

    void setCallback(WakeCallback cb) { callback_ = std::move(cb); }
    void setThreshold(float t)        { threshold_ = t; }

    // Clear internal buffers (start fresh listening session)
    void reset();

private:
    void  runMelChunk(const float* chunk1280);  // mel stage: accumulates into melBuf_
    void  runEmbedding();                        // emb stage: melBuf_ → push to embBuf_
    float runWakeWord();                         // ww stage: embBuf_ → score

    Ort::Env            env_;
    Ort::SessionOptions opts_;
    Ort::MemoryInfo     memInfo_;

    std::unique_ptr<Ort::Session> melSess_, embSess_, wwSess_;

    // Tensor names (queried from models at load time)
    std::vector<std::string> melIn_, melOut_;
    std::vector<std::string> embIn_, embOut_;
    std::vector<std::string> wwIn_,  wwOut_;

    // Wake word model input sequence length (from model shape, usually 16)
    int wwSeqLen_ = 16;

    // Audio accumulation (aligns incoming samples to CHUNK boundaries)
    std::vector<float> audioBuf_;

    static constexpr int CHUNK      = 1280;  // samples per mel inference (80ms @ 16kHz)
    static constexpr int MEL_FRAMES = 76;    // embedding model window size
    static constexpr int MEL_BINS   = 32;    // mel frequency bins
    static constexpr int EMB_DIMS   = 96;    // embedding dimensions

    std::deque<std::array<float, MEL_BINS>> melBuf_;  // sliding window of mel frames
    std::deque<std::array<float, EMB_DIMS>> embBuf_;  // sliding window of embeddings

    float        threshold_;
    WakeCallback callback_;
};
