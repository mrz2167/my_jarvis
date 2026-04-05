"""
Тест управления моторами ESP32 через UDP.
Запускай из любой директории.

Установка: pip install (ничего не нужно — только стандартная библиотека)
"""
import socket
import json
import time

ESP32_IP   = "192.168.1.XXX"  # ← поменяй на IP ESP32 из Serial Monitor
ESP32_PORT = 9721

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

def send(cmd, speed=180):
    msg = json.dumps({"cmd": cmd, "speed": speed})
    sock.sendto(msg.encode(), (ESP32_IP, ESP32_PORT))
    print(f"  → {msg}")

print("Тест моторов ESP32")
print(f"Отправляю на {ESP32_IP}:{ESP32_PORT}\n")
print("Смотри Serial Monitor — там появятся сообщения о командах\n")

tests = [
    ("forward",  180, 1.0),
    ("stop",     0,   0.5),
    ("backward", 180, 1.0),
    ("stop",     0,   0.5),
    ("left",     150, 0.8),
    ("stop",     0,   0.5),
    ("right",    150, 0.8),
    ("stop",     0,   0.5),
]

for cmd, speed, wait in tests:
    send(cmd, speed)
    time.sleep(wait)

print("\nГотово!")
sock.close()
