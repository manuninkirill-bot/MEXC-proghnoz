import requests
import logging


class SignalSender:
    """Отправка торговых сигналов на внешний сервис через ngrok"""

    def __init__(self):
        # Базовый URL из запроса пользователя
        self.base_url = "https://traci-unflashy-questingly.ngrok-free.dev/trades"
        # Параметры из примера curl
        self.target_url = "https://www.mexc.com/ru-RU/futures/event-futures/ETH_USDT"
        self.quantity = "5"
        self.time_unit = "M10"

    def send_signal(self, direction: str, time_unit: str = None, quantity: str = None):
        """
        Отправка вебхука с параметрами
        direction: 'Up' для лонга, 'Down' для шорта
        time_unit: 'M10', 'M30', 'H1' (по умолчанию M10)
        quantity: сумма ставки (по умолчанию '5')
        """
        params = {
            'targetUrl': self.target_url,
            'quantity': quantity if quantity is not None else self.quantity,
            'timeUnit': time_unit if time_unit is not None else self.time_unit,
            'orderDirection': direction
        }

        try:
            logging.info(
                f"Sending webhook to {self.base_url} with params: {params}")
            # Используем GET запрос как в curl --location (по умолчанию)
            response = requests.get(self.base_url, params=params, timeout=15)
            logging.info(
                f"Webhook response: {response.status_code} {response.text}")
            return True
        except Exception as e:
            logging.error(f"Failed to send webhook: {e}")
            return False

    def send_open_long(self, time_unit: str = None, quantity: str = None):
        """Отправка сигнала открытия LONG (Up)"""
        return self.send_signal("Up", time_unit=time_unit, quantity=quantity)

    def send_open_short(self, time_unit: str = None, quantity: str = None):
        """Отправка сигнала открытия SHORT (Down)"""
        return self.send_signal("Down", time_unit=time_unit, quantity=quantity)

    def send_close_long(self):
        """Сигналы закрытия отключены по запросу пользователя"""
        pass

    def send_close_short(self):
        """Сигналы закрытия отключены по запросу пользователя"""
        pass
