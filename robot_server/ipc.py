"""
Jarvis IPC — UDP слушатель.

Jarvis C++ core отправляет распознанный текст сюда после STT.
Формат пакета: {"type": "stt", "text": "возьми предмет"}

Порт: 9712
"""
import asyncio
import json
import logging

log = logging.getLogger(__name__)

IPC_HOST = "127.0.0.1"
IPC_PORT = 9712


class _Protocol(asyncio.DatagramProtocol):
    def __init__(self, on_text):
        self._on_text = on_text

    def datagram_received(self, data, addr):
        try:
            msg = json.loads(data.decode("utf-8"))
            if msg.get("type") == "stt":
                text = msg.get("text", "").strip()
                if text:
                    log.info(f"[Jarvis IPC] '{text}'")
                    self._on_text(text)
        except Exception as e:
            log.warning(f"IPC ошибка разбора: {e}")

    def error_received(self, exc):
        log.warning(f"IPC ошибка: {exc}")


async def start_ipc_server(on_text):
    """Запустить UDP сервер. on_text(str) вызывается для каждой фразы от Jarvis."""
    loop = asyncio.get_event_loop()
    transport, _ = await loop.create_datagram_endpoint(
        lambda: _Protocol(on_text),
        local_addr=(IPC_HOST, IPC_PORT),
    )
    log.info(f"Jarvis IPC слушает UDP {IPC_HOST}:{IPC_PORT}")
    return transport
