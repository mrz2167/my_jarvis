"""
Тест получения UDP аудио от ESP32.
Принимает int16 PCM 16kHz, проигрывает в реальном времени.

Установка:
    pip install sounddevice numpy
"""
import socket
import numpy as np
import sounddevice as sd
import struct
import sys

LISTEN_IP   = "0.0.0.0"
LISTEN_PORT = 9720
SAMPLE_RATE = 16000
CHUNK       = 512  # сэмплов

def main():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((LISTEN_IP, LISTEN_PORT))
    sock.settimeout(5.0)

    print(f"[UDP] Слушаю порт {LISTEN_PORT}...")
    print("[UDP] Жду пакеты от ESP32... (Ctrl+C для выхода)\n")

    # Открываем аудио выход с минимальной задержкой
    stream = sd.OutputStream(samplerate=SAMPLE_RATE, channels=1, dtype='float32',
                              blocksize=256, latency='low')
    stream.start()

    packets = 0
    try:
        while True:
            try:
                data, addr = sock.recvfrom(4096)
            except socket.timeout:
                print("[!] Нет пакетов 5 сек — ESP32 подключён?")
                continue

            if packets == 0:
                print(f"[OK] Первый пакет от {addr[0]}:{addr[1]}")

            packets += 1

            # int16 PCM → float32 [-1, 1]
            samples = np.frombuffer(data, dtype=np.int16).astype(np.float32)
            samples /= 32768.0

            # Проигрываем
            stream.write(samples.reshape(-1, 1))

            # Статистика каждые 100 пакетов (~3 сек)
            if packets % 100 == 0:
                peak = np.max(np.abs(samples))
                print(f"  Пакетов: {packets} | Размер: {len(data)} bytes | Peak: {peak:.4f}")

    except KeyboardInterrupt:
        print(f"\n[Стоп] Получено пакетов: {packets}")
    finally:
        stream.stop()
        sock.close()

if __name__ == "__main__":
    main()
