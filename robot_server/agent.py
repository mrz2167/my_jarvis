"""
Gemini Agent — автономное управление роботом.

Получает задачу + фото с камеры, сам планирует и выполняет команды.
Не требует мощного железа — вся работа на серверах Google (бесплатно).
"""
import asyncio
import base64
import logging
import os
from google import genai
from google.genai import types

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """Ты — система управления роботом-манипулятором MasterPi.
Робот стоит на меканум шасси (движение в любую сторону) и имеет руку с 6 сервоприводами:
  Серво 1 — захват (gripper)
  Серво 2 — запястье
  Серво 3 — локоть
  Серво 4 — плечо
  Серво 5 — поворот основания
  Серво 6 — подъём основания

Когда получаешь задачу:
1. Посмотри на камеру — get_camera() — чтобы понять обстановку
2. Планируй небольшие шаги
3. Выполняй их по одному, делай паузы между шагами
4. Проверяй камерой результат когда нужно
5. Скажи когда задача выполнена или если не можешь выполнить

Всегда отвечай на русском языке. Будь лаконичен.
"""


class RobotAgent:
    def __init__(self, robot_control, get_frame_fn, api_key: str):
        """
        robot_control: экземпляр RobotControl
        get_frame_fn:  функция () -> bytes | None — возвращает JPEG кадр с камеры
        api_key:       Gemini API ключ
        """
        self._robot = robot_control
        self._get_frame = get_frame_fn
        self._client = genai.Client(api_key=api_key)
        self._tools = self._build_tools()

    # ─── Определение инструментов ────────────────────────────────

    def _build_tools(self):
        return [
            types.Tool(function_declarations=[
                types.FunctionDeclaration(
                    name="move",
                    description="Движение шасси робота в заданном направлении.",
                    parameters=types.Schema(
                        type="OBJECT",
                        properties={
                            "direction": types.Schema(
                                type="STRING",
                                enum=["вперёд", "назад", "влево", "вправо"],
                                description="Направление движения"
                            ),
                            "duration_ms": types.Schema(
                                type="INTEGER",
                                description="Время движения в миллисекундах (200–3000)"
                            ),
                        },
                        required=["direction", "duration_ms"],
                    ),
                ),
                types.FunctionDeclaration(
                    name="arm",
                    description="Переместить руку-манипулятор в именованную позицию.",
                    parameters=types.Schema(
                        type="OBJECT",
                        properties={
                            "position": types.Schema(
                                type="STRING",
                                enum=["home", "up", "down", "extend"],
                                description="home=исходное, up=вверх, down=вниз, extend=вытянуть вперёд"
                            ),
                        },
                        required=["position"],
                    ),
                ),
                types.FunctionDeclaration(
                    name="grab",
                    description="Закрыть захват — взять предмет.",
                    parameters=types.Schema(type="OBJECT", properties={}),
                ),
                types.FunctionDeclaration(
                    name="release",
                    description="Открыть захват — отпустить предмет.",
                    parameters=types.Schema(type="OBJECT", properties={}),
                ),
                types.FunctionDeclaration(
                    name="stop",
                    description="Остановить все движения робота.",
                    parameters=types.Schema(type="OBJECT", properties={}),
                ),
                types.FunctionDeclaration(
                    name="get_camera",
                    description="Получить текущий кадр с камеры робота для анализа.",
                    parameters=types.Schema(type="OBJECT", properties={}),
                ),
                types.FunctionDeclaration(
                    name="wait",
                    description="Подождать перед следующим действием.",
                    parameters=types.Schema(
                        type="OBJECT",
                        properties={
                            "ms": types.Schema(
                                type="INTEGER",
                                description="Время ожидания в миллисекундах (100–3000)"
                            ),
                        },
                        required=["ms"],
                    ),
                ),
            ])
        ]

    # ─── Выполнение вызовов инструментов ─────────────────────────

    async def _execute_tool(self, name: str, args: dict) -> str:
        log.info(f"[Agent] Инструмент: {name}({args})")

        if name == "move":
            direction = args.get("direction", "вперёд")
            duration  = int(args.get("duration_ms", 500))
            dispatch = {
                "вперёд": self._robot.move_forward,
                "назад":  self._robot.move_backward,
                "влево":  self._robot.move_left,
                "вправо": self._robot.move_right,
            }
            fn = dispatch.get(direction)
            if fn:
                await fn()
                await asyncio.sleep(duration / 1000)
                await self._robot.stop()
            return f"Движение {direction} {duration}мс выполнено"

        elif name == "arm":
            pos = args.get("position", "home")
            dispatch = {
                "home":   self._robot.arm_home,
                "up":     self._robot.arm_up,
                "down":   self._robot.arm_down,
                "extend": self._robot.arm_extend,
            }
            fn = dispatch.get(pos)
            if fn:
                await fn()
                await asyncio.sleep(0.6)
            return f"Рука в позиции {pos}"

        elif name == "grab":
            await self._robot.grab()
            await asyncio.sleep(0.5)
            return "Захват закрыт"

        elif name == "release":
            await self._robot.release()
            await asyncio.sleep(0.5)
            return "Захват открыт"

        elif name == "stop":
            await self._robot.stop()
            return "Остановлен"

        elif name == "get_camera":
            frame = self._get_frame()
            if frame is None:
                return "Камера недоступна"
            # Возвращаем base64 — Gemini его примет в следующем сообщении
            return base64.b64encode(frame).decode()

        elif name == "wait":
            ms = int(args.get("ms", 500))
            await asyncio.sleep(ms / 1000)
            return f"Подождал {ms}мс"

        return f"Неизвестный инструмент: {name}"

    # ─── Главный метод ────────────────────────────────────────────

    async def run(self, task: str, initial_frame: bytes | None = None) -> str:
        """
        Выполнить задачу автономно.
        task          — текст команды от пользователя
        initial_frame — JPEG кадр с камеры (опционально)
        """
        log.info(f"[Agent] Задача: '{task}'")

        # Начальное сообщение
        parts = [types.Part.from_text(task)]
        if initial_frame:
            parts.append(types.Part.from_bytes(
                data=initial_frame,
                mime_type="image/jpeg"
            ))

        contents = [types.Content(role="user", parts=parts)]

        # Цикл tool calling
        max_steps = 20
        for step in range(max_steps):
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                lambda c=contents: self._client.models.generate_content(
                    model="gemini-2.0-flash",
                    contents=c,
                    config=types.GenerateContentConfig(
                        system_instruction=SYSTEM_PROMPT,
                        tools=self._tools,
                        temperature=0.2,
                    ),
                )
            )

            candidate = response.candidates[0]
            contents.append(types.Content(
                role="model",
                parts=candidate.content.parts
            ))

            # Собираем вызовы инструментов
            tool_calls = [p for p in candidate.content.parts if p.function_call]

            if not tool_calls:
                # Нет вызовов — задача завершена
                text = response.text or ""
                log.info(f"[Agent] Завершено: {text}")
                return text

            # Выполняем все инструменты
            tool_results = []
            for part in tool_calls:
                fc   = part.function_call
                result = await self._execute_tool(fc.name, dict(fc.args))

                # Если get_camera вернул base64 — добавляем как изображение
                if fc.name == "get_camera" and result != "Камера недоступна":
                    try:
                        img_bytes = base64.b64decode(result)
                        tool_results.append(types.Part.from_function_response(
                            name=fc.name,
                            response={"result": "Кадр получен — смотри изображение ниже"}
                        ))
                        tool_results.append(types.Part.from_bytes(
                            data=img_bytes,
                            mime_type="image/jpeg"
                        ))
                        continue
                    except Exception:
                        pass

                tool_results.append(types.Part.from_function_response(
                    name=fc.name,
                    response={"result": result}
                ))

            contents.append(types.Content(role="user", parts=tool_results))

        return "Превышено максимальное число шагов"
