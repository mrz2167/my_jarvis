# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Build System

**Platform:** Windows 11, MSVC v143 (VS 2022 Build Tools), Ninja, C++17.
**Must use:** "x64 Native Tools Command Prompt for VS 2022" — regular CMD won't find cmake/ninja.

```cmd
cd C:\Projects\my_jarvis\core

# First build (downloads dependencies + model):
cmake -B build -G Ninja
cmake --build build

# Subsequent builds (no re-configure needed unless CMakeLists.txt changed):
cmake --build build

# Run:
cd build
jarvis_core.exe
```

**Full clean rebuild** (required when model URL changes or deps are stale):
```cmd
rmdir /s /q build
cmake -B build -G Ninja
cmake --build build
```

The configure step (`cmake -B build`) auto-downloads:
- `miniaudio.h` — into `audio/`
- ONNX Runtime 1.20.1 zip — into `build/onnxruntime/`
- `silero_vad.onnx` — into `models/vad/`

Post-build copies `onnxruntime.dll` and `silero_vad.onnx` next to the `.exe`.

## Architecture

The project is a voice assistant with three planned components:
- **`core/`** — C++ engine (this directory, in development)
- **`agent/`** — Python LLM agent (not yet started)
- **`gui/`** — Tauri + Svelte desktop app (not yet started)

### C++ Core Pipeline

```
Microphone → AudioCapture → VoiceActivityDetector → [phrase buffer]
                                                          ↓
                                               [next: Wake-word → STT → Classifier → TTS]
```

**Audio flow:** `AudioCapture` calls a `SampleCallback` every 512 frames (~32ms) from a miniaudio audio thread. `VoiceActivityDetector::feed()` accumulates these into 512-sample chunks, runs `SileroVAD::process()` on each, and fires `SpeechCallback` with the complete audio buffer when a phrase ends.

### Key classes

**`AudioCapture`** (`audio/capture.hpp`)
- miniaudio device is stored as `void*` to avoid pulling `miniaudio.h` into headers
- `onAudioData()` must be public — called from a free-function C callback (`maDataCallback` in capture.cpp)
- `MINIAUDIO_IMPLEMENTATION` is defined only in `capture.cpp`

**`SileroVAD`** (`vad/vad.hpp`)
- Wraps ONNX Runtime session for Silero VAD **v4** model
- Model: `https://github.com/snakers4/silero-vad/raw/v4.0/files/silero_vad.onnx`
- **v4 interface** — 4 inputs: `"input"[1,512]`, `"sr"[1] int64`, `"h"[2,1,64]`, `"c"[2,1,64]`; 3 outputs: `"output"`, `"hn"`, `"cn"` — do NOT use v5 (master branch returns ~0 for all audio)
- `H_SIZE = 128` (2×1×64); two separate state vectors `h_` and `c_`
- Input tensors are assembled in model-name order (not hardcoded positional order)

**`VoiceActivityDetector`** (`vad/vad.hpp`)
- FSM: `IDLE` → `CAPTURING` → (fires callback) → `IDLE`
- Maintains a rolling `preBuffer_` (audio before speech starts) and `captureBuffer_`
- All thresholds converted from ms to chunk counts at construction time

### IPC Design (planned)
- **WebSocket port 9712** — GUI communication
- **ZeroMQ PUSH/PULL ports 9713/9714** — Python agent communication
- Ghost Touch shutdown: send `{"action": "Shutdown"}` over WebSocket, then SIGTERM → SIGKILL after timeout

## Dependencies

All managed via CMake FetchContent / file(DOWNLOAD) — no manual installation needed.

| Library | Version | How |
|---|---|---|
| miniaudio | master | Single header, FetchContent into `audio/` |
| ONNX Runtime | 1.20.1 | Prebuilt Windows x64 zip, FetchContent |
| Silero VAD model | v4.0 | file(DOWNLOAD) into `models/vad/` |

Planned (not yet added to CMakeLists.txt): whisper.cpp (STT), Piper (TTS), openWakeWord ONNX models, rapidfuzz-cpp, libzmq+cppzmq, websocketpp, toml++, nlohmann/json.

## Current Implementation Status

| Module | Status |
|---|---|
| Audio Capture (miniaudio) | Done — 16kHz mono float32, 512 frames/chunk |
| Silero VAD v4 | Done — detects speech with prob 0.97–0.99 |
| Wake-word (openWakeWord) | Not started |
| STT (whisper.cpp base) | Not started |
| Classifier (rapidfuzz) | Not started |
| TTS (Piper) | Not started |
| IPC (WebSocket + ZeroMQ) | Not started |
| Python Agent | Not started |
| GUI (Tauri + Svelte) | Not started |

## Common Pitfalls

- **Wrong architecture:** Building x86 against x64 ONNX Runtime causes LNK4272 linker error. Always use "x64 Native Tools Command Prompt".
- **Stale model:** If `silero_vad.onnx` is 0 bytes or corrupted, `cmake --build` won't re-download it — must `rmdir /s /q build` and re-run `cmake -B build`.
- **Wrong model version:** Silero VAD v5 (master branch) returns near-zero probabilities for all audio. Only v4.0 release tag works with this codebase.
- **Model not found at runtime:** Run `jarvis_core.exe` from the `build/` directory where `silero_vad.onnx` was copied.
