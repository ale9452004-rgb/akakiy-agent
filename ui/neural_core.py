"""
Совместимый интерфейс к ядру Акакия (NeuralCore / AkakiyCore).

Предоставляет класс NeuralCore, наследующий обновлённый визуальный
компонент AkakiyCore с сохранением полной обратной совместимости.
"""

from ui.akakiy_core import AkakiyCore, fibonacci_sphere, hex_to_rgb, rgb_to_hex, interpolate_rgb


class NeuralCore(AkakiyCore):
    """
    Алиас и совместимый фасад для AkakiyCore.
    Поддерживает все существующие методы и интерфейсы тестирования.
    """
    pass


__all__ = ["NeuralCore", "AkakiyCore", "fibonacci_sphere"]
