cmake_minimum_required(VERSION 3.20)
project(jarvis_core VERSION 0.1.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# ─────────────────────────────────────────────
# Platform detection
# ─────────────────────────────────────────────
if(WIN32)
    add_definitions(-D_WIN32_WINNT=0x0601)
    add_definitions(-DNOMINMAX)
    add_definitions(-DWIN32_LEAN_AND_MEAN)
    set(PLATFORM_NAME "win64")
elseif(UNIX)
    set(PLATFORM_NAME "linux-x86_64")
    # RPATH: look for .so in the same directory as the exe
    set(CMAKE_BUILD_RPATH "$ORIGIN")
    set(CMAKE_INSTALL_RPATH "$ORIGIN")
endif()

include(FetchContent)

# ─────────────────────────────────────────────
# miniaudio (header-only)
# ─────────────────────────────────────────────
FetchContent_Declare(
    miniaudio
    URL https://raw.githubusercontent.com/mackron/miniaudio/master/miniaudio.h
    DOWNLOAD_NO_EXTRACT TRUE
    DOWNLOAD_DIR ${CMAKE_CURRENT_SOURCE_DIR}/audio
)
FetchContent_MakeAvailable(miniaudio)

# ─────────────────────────────────────────────
# ONNX Runtime (prebuilt binary)
# ─────────────────────────────────────────────
set(ORT_VERSION "1.20.1")

if(WIN32)
    set(ORT_DIR_NAME "onnxruntime-win-x64-${ORT_VERSION}")
    set(ORT_ARCHIVE_NAME "${ORT_DIR_NAME}.zip")
    set(ORT_URL "https://github.com/microsoft/onnxruntime/releases/download/v${ORT_VERSION}/${ORT_ARCHIVE_NAME}")
elseif(UNIX)
    set(ORT_DIR_NAME "onnxruntime-linux-x64-${ORT_VERSION}")
    set(ORT_ARCHIVE_NAME "${ORT_DIR_NAME}.tgz")
    set(ORT_URL "https://github.com/microsoft/onnxruntime/releases/download/v${ORT_VERSION}/${ORT_ARCHIVE_NAME}")
endif()

set(ORT_DOWNLOAD_DIR "${CMAKE_BINARY_DIR}/onnxruntime_download")
set(ORT_EXTRACT_DIR "${CMAKE_BINARY_DIR}/onnxruntime")
set(ORT_ROOT "${ORT_EXTRACT_DIR}/${ORT_DIR_NAME}")

if(NOT EXISTS "${ORT_ROOT}/include/onnxruntime_cxx_api.h")
    message(STATUS "Downloading ONNX Runtime ${ORT_VERSION}...")
    file(DOWNLOAD
        "${ORT_URL}"
        "${ORT_DOWNLOAD_DIR}/${ORT_ARCHIVE_NAME}"
        SHOW_PROGRESS
        STATUS ORT_DOWNLOAD_STATUS
    )
    list(GET ORT_DOWNLOAD_STATUS 0 ORT_DOWNLOAD_STATUS_CODE)
    if(NOT ORT_DOWNLOAD_STATUS_CODE EQUAL 0)
        message(FATAL_ERROR "Failed to download ONNX Runtime: ${ORT_DOWNLOAD_STATUS}")
    endif()
    file(ARCHIVE_EXTRACT
        INPUT "${ORT_DOWNLOAD_DIR}/${ORT_ARCHIVE_NAME}"
        DESTINATION "${ORT_EXTRACT_DIR}"
    )
    message(STATUS "ONNX Runtime extracted to ${ORT_EXTRACT_DIR}")
endif()

set(ORT_INCLUDE_DIR "${ORT_ROOT}/include")
set(ORT_LIB_DIR "${ORT_ROOT}/lib")

# ─────────────────────────────────────────────
# Silero VAD ONNX модель
# ─────────────────────────────────────────────
set(SILERO_MODEL_URL "https://github.com/snakers4/silero-vad/raw/v4.0/files/silero_vad.onnx")
set(SILERO_MODEL_DST "${CMAKE_CURRENT_SOURCE_DIR}/models/vad/silero_vad.onnx")

if(NOT EXISTS "${SILERO_MODEL_DST}")
    message(STATUS "Downloading Silero VAD model...")
    file(DOWNLOAD
        "${SILERO_MODEL_URL}"
        "${SILERO_MODEL_DST}"
        SHOW_PROGRESS
        STATUS SILERO_DOWNLOAD_STATUS
    )
    list(GET SILERO_DOWNLOAD_STATUS 0 SILERO_DOWNLOAD_STATUS_CODE)
    if(NOT SILERO_DOWNLOAD_STATUS_CODE EQUAL 0)
        message(FATAL_ERROR "Failed to download Silero VAD model: ${SILERO_DOWNLOAD_STATUS}")
    endif()
    message(STATUS "Silero VAD model saved to ${SILERO_MODEL_DST}")
endif()

# ─────────────────────────────────────────────
# openWakeWord ONNX модели
# ─────────────────────────────────────────────
set(OWW_VERSION "v0.5.1")
set(OWW_BASE_URL "https://github.com/dscripka/openWakeWord/releases/download/${OWW_VERSION}")
set(OWW_MODEL_DIR "${CMAKE_CURRENT_SOURCE_DIR}/models/wake_word")

file(MAKE_DIRECTORY "${OWW_MODEL_DIR}")

foreach(OWW_MODEL IN ITEMS melspectrogram.onnx embedding_model.onnx hey_jarvis_v0.1.onnx)
    set(OWW_DST "${OWW_MODEL_DIR}/${OWW_MODEL}")
    if(NOT EXISTS "${OWW_DST}")
        message(STATUS "Downloading openWakeWord model: ${OWW_MODEL}...")
        file(DOWNLOAD
            "${OWW_BASE_URL}/${OWW_MODEL}"
            "${OWW_DST}"
            SHOW_PROGRESS
            STATUS OWW_DL_STATUS
        )
        list(GET OWW_DL_STATUS 0 OWW_DL_CODE)
        if(NOT OWW_DL_CODE EQUAL 0)
            message(FATAL_ERROR "Failed to download ${OWW_MODEL}: ${OWW_DL_STATUS}")
        endif()
        message(STATUS "Saved: ${OWW_DST}")
    endif()
endforeach()

# ─────────────────────────────────────────────
# Vosk (STT) — prebuilt binary
# ─────────────────────────────────────────────
set(VOSK_VERSION "0.3.45")

if(WIN32)
    set(VOSK_DIR_NAME "vosk-win64-${VOSK_VERSION}")
elseif(UNIX)
    set(VOSK_DIR_NAME "vosk-linux-x86_64-${VOSK_VERSION}")
endif()

set(VOSK_ZIP_NAME "${VOSK_DIR_NAME}.zip")
set(VOSK_URL "https://github.com/alphacep/vosk-api/releases/download/v${VOSK_VERSION}/${VOSK_ZIP_NAME}")
set(VOSK_EXTRACT_DIR "${CMAKE_BINARY_DIR}/vosk")
set(VOSK_ROOT "${VOSK_EXTRACT_DIR}/${VOSK_DIR_NAME}")

if(NOT EXISTS "${VOSK_ROOT}/vosk_api.h")
    message(STATUS "Downloading Vosk ${VOSK_VERSION} for ${PLATFORM_NAME}...")
    file(DOWNLOAD
        "${VOSK_URL}"
        "${CMAKE_BINARY_DIR}/vosk_download/${VOSK_ZIP_NAME}"
        SHOW_PROGRESS
        STATUS VOSK_DL_STATUS
    )
    list(GET VOSK_DL_STATUS 0 VOSK_DL_CODE)
    if(NOT VOSK_DL_CODE EQUAL 0)
        message(FATAL_ERROR "Failed to download Vosk: ${VOSK_DL_STATUS}")
    endif()
    file(ARCHIVE_EXTRACT
        INPUT "${CMAKE_BINARY_DIR}/vosk_download/${VOSK_ZIP_NAME}"
        DESTINATION "${VOSK_EXTRACT_DIR}"
    )
    message(STATUS "Vosk extracted to ${VOSK_ROOT}")
endif()

# ─────────────────────────────────────────────
# Vosk Russian model (~1.8 GB)
# ─────────────────────────────────────────────
set(VOSK_MODEL_NAME "vosk-model-ru-0.42")
set(VOSK_MODEL_DIR  "${CMAKE_CURRENT_SOURCE_DIR}/models/stt")
set(VOSK_MODEL_PATH "${VOSK_MODEL_DIR}/${VOSK_MODEL_NAME}")

file(MAKE_DIRECTORY "${VOSK_MODEL_DIR}")

if(NOT EXISTS "${VOSK_MODEL_PATH}/am/final.mdl")
    message(STATUS "Downloading Vosk Russian model (~1.8 GB) — подожди...")
    file(DOWNLOAD
        "https://alphacephei.com/vosk/models/${VOSK_MODEL_NAME}.zip"
        "${VOSK_MODEL_DIR}/${VOSK_MODEL_NAME}.zip"
        SHOW_PROGRESS
        STATUS VOSK_MODEL_DL_STATUS
    )
    list(GET VOSK_MODEL_DL_STATUS 0 VOSK_MODEL_DL_CODE)
    if(NOT VOSK_MODEL_DL_CODE EQUAL 0)
        message(FATAL_ERROR "Failed to download Vosk model: ${VOSK_MODEL_DL_STATUS}")
    endif()
    file(ARCHIVE_EXTRACT
        INPUT "${VOSK_MODEL_DIR}/${VOSK_MODEL_NAME}.zip"
        DESTINATION "${VOSK_MODEL_DIR}"
    )
    message(STATUS "Vosk model extracted to ${VOSK_MODEL_PATH}")
endif()

# Генерируем config.h с путём к модели
configure_file(
    "${CMAKE_CURRENT_SOURCE_DIR}/config.h.in"
    "${CMAKE_BINARY_DIR}/config.h"
)

# ─────────────────────────────────────────────
# Исполняемый файл
# ─────────────────────────────────────────────
add_executable(jarvis_core
    main.cpp
    audio/capture.cpp
    vad/vad.cpp
    wake/wake_word.cpp
    stt/stt.cpp
)

target_include_directories(jarvis_core PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}
    ${ORT_INCLUDE_DIR}
    ${VOSK_ROOT}           # vosk_api.h
    ${CMAKE_BINARY_DIR}    # config.h
)

# ONNX Runtime import library
find_library(ORT_LIBRARY
    NAMES onnxruntime
    PATHS "${ORT_LIB_DIR}"
    NO_DEFAULT_PATH
    REQUIRED
)

# Vosk import library
find_library(VOSK_LIBRARY
    NAMES vosk libvosk
    PATHS "${VOSK_ROOT}"
    NO_DEFAULT_PATH
    REQUIRED
)

target_link_libraries(jarvis_core PRIVATE ${ORT_LIBRARY} ${VOSK_LIBRARY})

# Platform-specific system libraries
if(WIN32)
    target_link_libraries(jarvis_core PRIVATE ole32 winmm ksuser ws2_32)
elseif(UNIX)
    target_link_libraries(jarvis_core PRIVATE dl pthread m)
endif()

# ─────────────────────────────────────────────
# POST_BUILD: копируем runtime файлы рядом с .exe
# ─────────────────────────────────────────────

# ONNX Runtime runtime
if(WIN32)
    add_custom_command(TARGET jarvis_core POST_BUILD
        COMMAND ${CMAKE_COMMAND} -E copy_if_different
            "${ORT_LIB_DIR}/onnxruntime.dll"
            "$<TARGET_FILE_DIR:jarvis_core>/onnxruntime.dll"
        COMMENT "Copying onnxruntime.dll"
    )
elseif(UNIX)
    add_custom_command(TARGET jarvis_core POST_BUILD
        COMMAND ${CMAKE_COMMAND} -E copy_if_different
            "${ORT_LIB_DIR}/libonnxruntime.so.${ORT_VERSION}"
            "$<TARGET_FILE_DIR:jarvis_core>/libonnxruntime.so.${ORT_VERSION}"
        COMMENT "Copying libonnxruntime.so"
    )
    add_custom_command(TARGET jarvis_core POST_BUILD
        COMMAND ${CMAKE_COMMAND} -E create_symlink
            "libonnxruntime.so.${ORT_VERSION}"
            "$<TARGET_FILE_DIR:jarvis_core>/libonnxruntime.so"
        COMMENT "Creating libonnxruntime.so symlink"
    )
endif()

# VAD model
add_custom_command(TARGET jarvis_core POST_BUILD
    COMMAND ${CMAKE_COMMAND} -E copy_if_different
        "${SILERO_MODEL_DST}"
        "$<TARGET_FILE_DIR:jarvis_core>/silero_vad.onnx"
    COMMENT "Copying Silero VAD model"
)

# openWakeWord models
foreach(OWW_MODEL IN ITEMS melspectrogram.onnx embedding_model.onnx hey_jarvis_v0.1.onnx)
    add_custom_command(TARGET jarvis_core POST_BUILD
        COMMAND ${CMAKE_COMMAND} -E copy_if_different
            "${OWW_MODEL_DIR}/${OWW_MODEL}"
            "$<TARGET_FILE_DIR:jarvis_core>/${OWW_MODEL}"
        COMMENT "Copying ${OWW_MODEL}"
    )
endforeach()

# Vosk runtime
if(WIN32)
    foreach(VOSK_DLL IN ITEMS libvosk.dll libgcc_s_seh-1.dll libstdc++-6.dll libwinpthread-1.dll)
        add_custom_command(TARGET jarvis_core POST_BUILD
            COMMAND ${CMAKE_COMMAND} -E copy_if_different
                "${VOSK_ROOT}/${VOSK_DLL}"
                "$<TARGET_FILE_DIR:jarvis_core>/${VOSK_DLL}"
            COMMENT "Copying ${VOSK_DLL}"
        )
    endforeach()
elseif(UNIX)
    add_custom_command(TARGET jarvis_core POST_BUILD
        COMMAND ${CMAKE_COMMAND} -E copy_if_different
            "${VOSK_ROOT}/libvosk.so"
            "$<TARGET_FILE_DIR:jarvis_core>/libvosk.so"
        COMMENT "Copying libvosk.so"
    )
endif()

message(STATUS "")
message(STATUS "=== Jarvis Core (${PLATFORM_NAME}) ===")
message(STATUS "  ORT include:  ${ORT_INCLUDE_DIR}")
message(STATUS "  ORT lib:      ${ORT_LIBRARY}")
message(STATUS "  VAD model:    ${SILERO_MODEL_DST}")
message(STATUS "  WakeWord dir: ${OWW_MODEL_DIR}")
message(STATUS "  STT model:    ${VOSK_MODEL_PATH}")
message(STATUS "  Vosk lib:     ${VOSK_LIBRARY}")
message(STATUS "")
