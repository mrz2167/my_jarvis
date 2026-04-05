#include <iostream>
#include <string>
#include <thread>
#include <chrono>
#include <atomic>
#include <csignal>
#include <filesystem>
#include <cmath>
#include <queue>
#include <mutex>
#include <condition_variable>

#ifdef _WIN32
#include <winsock2.h>
#include <windows.h>
#endif

#include "audio/capture.hpp"
#include "vad/vad.hpp"
#include "wake/wake_word.hpp"
#include "stt/stt.hpp"
#include "config.h"

namespace fs = std::filesystem;

static std::atomic<bool> g_running{true};

// ─── Jarvis IPC — отправка текста в robot_server по UDP ──────────────
static constexpr uint16_t IPC_PORT = 9712;

static void sendIpc(const std::string& text) {
#ifdef _WIN32
    static bool wsaInited = false;
    if (!wsaInited) {
        WSADATA wsa{};
        WSAStartup(MAKEWORD(2, 2), &wsa);
        wsaInited = true;
    }
    SOCKET sock = socket(AF_INET, SOCK_DGRAM, IPPROTO_UDP);
    if (sock == INVALID_SOCKET) return;

    sockaddr_in addr{};
    addr.sin_family      = AF_INET;
    addr.sin_port        = htons(IPC_PORT);
    addr.sin_addr.s_addr = inet_addr("127.0.0.1");

    // Экранируем кавычки в тексте
    std::string safe = text;
    for (size_t i = 0; i < safe.size(); ++i) {
        if (safe[i] == '"') { safe.insert(i, "\\"); i++; }
    }
    std::string json = "{\"type\":\"stt\",\"text\":\"" + safe + "\"}";
    sendto(sock, json.c_str(), (int)json.size(), 0,
           reinterpret_cast<sockaddr*>(&addr), sizeof(addr));
    closesocket(sock);
#endif
}

static void signalHandler(int) {
    std::cout << "\n[Jarvis] Завершение...\n";
    g_running = false;
}

int main(int argc, char* argv[])
try
{
    std::signal(SIGINT,  signalHandler);
    std::signal(SIGTERM, signalHandler);

#ifdef _WIN32
    SetConsoleOutputCP(CP_UTF8);
    SetConsoleCP(CP_UTF8);
#endif

    // ─── Пути к моделям ──────────────────────────────────────
    std::string vadModel  = "silero_vad.onnx";
    std::string melModel  = "melspectrogram.onnx";
    std::string embModel  = "embedding_model.onnx";
    std::string wwModel   = "hey_jarvis_v0.1.onnx";
    std::string sttModel  = VOSK_MODEL_PATH;  // абсолютный путь из config.h

    for (const auto& p : {vadModel, melModel, embModel, wwModel}) {
        if (!fs::exists(p)) {
            std::cerr << "[Jarvis] Модель не найдена: " << p << "\n";
            std::cerr << "         Запускайте из директории build/\n";
            return 1;
        }
    }
    if (!fs::exists(sttModel)) {
        std::cerr << "[Jarvis] Vosk модель не найдена: " << sttModel << "\n";
        return 1;
    }

    // ─── STT очередь ─────────────────────────────────────────
    std::queue<std::vector<float>> sttQueue;
    std::mutex                     sttMutex;
    std::condition_variable        sttCv;
    bool                           sttStop = false;

    std::cout << "[Jarvis] STT модель: " << sttModel << "\n";
    std::cout << "[Jarvis] Загружаю Vosk STT...\n";
    std::cout.flush();

    // STT поток: загружает модель и обрабатывает аудио из очереди
    std::thread sttThread([&]() {
        try {
            SpeechToText stt(sttModel, "ru");

            while (true) {
                std::unique_lock<std::mutex> lock(sttMutex);
                sttCv.wait(lock, [&]{ return !sttQueue.empty() || sttStop; });

                if (sttStop && sttQueue.empty()) break;

                auto audio = std::move(sttQueue.front());
                sttQueue.pop();
                lock.unlock();

                float sec = static_cast<float>(audio.size()) / 16000.0f;
                std::cout << "[STT] Распознаю " << sec << " сек...\n";
                std::cout.flush();

                std::string text = stt.transcribe(audio);

                if (!text.empty()) {
                    std::cout << "[STT] >>> " << text << "\n\n";
                    sendIpc(text);   // → robot_server UDP 9712
                } else {
                    std::cout << "[STT] (пусто)\n\n";
                }
                std::cout.flush();
            }
        } catch (const std::exception& e) {
            std::cerr << "[STT] ОШИБКА: " << e.what() << "\n";
            std::cerr.flush();
            std::lock_guard<std::mutex> lock(sttMutex);
            sttStop = true;
            sttCv.notify_one();
        } catch (...) {
            std::cerr << "[STT] НЕИЗВЕСТНАЯ ОШИБКА В ПОТОКЕ\n";
            std::cerr.flush();
            std::lock_guard<std::mutex> lock(sttMutex);
            sttStop = true;
            sttCv.notify_one();
        }
        std::cout << "[STT] Поток завершён\n";
        std::cout.flush();
    });

    // ─── Инициализация Silero VAD ─────────────────────────────
    std::cout << "[Jarvis] Загружаю Silero VAD...\n";
    SileroVAD sileroVad(vadModel);

    VadConfig vadCfg;
    vadCfg.threshold        = 0.5f;
    vadCfg.minSpeechMs      = 250;
    vadCfg.silenceTimeoutMs = 1200;
    vadCfg.preBufferMs      = 150;

    int phraseCount = 0;

    VoiceActivityDetector vad(sileroVad, vadCfg,
        [&](std::vector<float> audio) {
            ++phraseCount;
            float sec = static_cast<float>(audio.size()) / 16000.0f;
            std::cout << "[VAD] Фраза #" << phraseCount << " — "
                      << sec << " сек → STT\n";

            // Передаём аудио в STT поток
            {
                std::lock_guard<std::mutex> lock(sttMutex);
                sttQueue.push(std::move(audio));
            }
            sttCv.notify_one();
        }
    );

    // ─── Инициализация Wake Word ──────────────────────────────
    std::cout << "[Jarvis] Загружаю Wake Word (hey Jarvis)...\n";
    WakeWordDetector wakeWord(melModel, embModel, wwModel, /*threshold=*/0.5f);

    int wakeCount = 0;
    wakeWord.setCallback([&](float score) {
        ++wakeCount;
        std::cout << "\n*** WAKE WORD #" << wakeCount
                  << " detected! score=" << score << " ***\n\n";
    });

    // ─── Быстрый тест VAD модели ─────────────────────────────
    {
        const float PI = 3.14159265f;
        std::vector<float> synth(512);

        std::fill(synth.begin(), synth.end(), 0.0f);
        sileroVad.resetState();
        float pSilence = sileroVad.process(synth.data());

        sileroVad.resetState();
        float pSpeechMax = 0.0f;
        for (int j = 0; j < 30; j++) {
            for (int i = 0; i < 512; i++) {
                float t = (float)(j * 512 + i) / 16000.0f;
                synth[i] = 0.5f * std::sin(2.0f * PI * 200.0f * t);
            }
            pSpeechMax = std::max(pSpeechMax, sileroVad.process(synth.data()));
        }
        sileroVad.resetState();

        std::cout << "\n[VAD test] Тишина=" << pSilence
                  << " Синусоида=" << pSpeechMax << "\n\n";
    }

    // ─── Режим захвата (--udp → ESP32, иначе микрофон) ───────
    bool useUdp = false;
    for (int i = 1; i < argc; ++i)
        if (std::string(argv[i]) == "--udp") useUdp = true;

    constexpr uint16_t UDP_PORT = 9720;

    // Список устройств (только в режиме микрофона)
    if (!useUdp) {
        AudioCapture probe([](const float*, size_t){});
        auto devices = probe.listDevices();
        std::cout << "[Jarvis] Доступные микрофоны:\n";
        for (size_t i = 0; i < devices.size(); ++i)
            std::cout << "  [" << i << "] " << devices[i] << "\n";
    } else {
        std::cout << "[Jarvis] Режим UDP — ожидаю ESP32 на порту "
                  << UDP_PORT << "\n";
    }

    // ─── Запуск захвата ───────────────────────────────────────
    static int audioTick = 0;

    auto audioCallback = [&](const float* samples, size_t count) {
        wakeWord.feed(samples, count);
        vad.feed(samples, count);

        if (++audioTick % 63 == 0) {
            float peak = 0.0f;
            for (size_t i = 0; i < count; ++i)
                peak = std::max(peak, std::abs(samples[i]));
            std::cout << "[Audio] peak=" << peak
                      << (peak < 0.001f ? " (тишина)" : " (сигнал)") << "\n";
        }
    };

    // Создаём нужный тип захвата
    std::unique_ptr<AudioCapture> capturePtr;
    if (useUdp)
        capturePtr = std::make_unique<AudioCapture>(audioCallback,
                                                    AudioSource::UDP, UDP_PORT);
    else
        capturePtr = std::make_unique<AudioCapture>(audioCallback);

    if (!capturePtr->start()) {
        std::cerr << "[Jarvis] Не удалось запустить захват аудио\n";
        return 1;
    }

    std::cout << "[Jarvis] Слушаю... Скажи \"Hey Jarvis\" (Ctrl+C для выхода)\n";
    std::cout << "[Jarvis] Примечание: прогрев wake word ~7 сек\n\n";

    while (g_running) {
        std::this_thread::sleep_for(std::chrono::milliseconds(100));
    }

    capturePtr->stop();

    // Завершаем STT поток
    {
        std::lock_guard<std::mutex> lock(sttMutex);
        sttStop = true;
    }
    sttCv.notify_one();
    sttThread.join();

    std::cout << "[Jarvis] Wake word срабатываний: " << wakeCount << "\n";
    std::cout << "[Jarvis] Всего фраз обнаружено:  " << phraseCount << "\n";
    return 0;
}
catch (const Ort::Exception& e) {
    std::cerr << "\n[FATAL] ONNX Runtime: " << e.what() << "\n";
    return 1;
}
catch (const std::exception& e) {
    std::cerr << "\n[FATAL] " << e.what() << "\n";
    return 1;
}
