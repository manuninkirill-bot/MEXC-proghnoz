import random
import time
from datetime import datetime, timedelta

class MarketSimulator:
    """
    Симулятор рынка для тестирования торговой стратегии без реальных денег
    """
    def __init__(self, initial_price=3000, volatility=0.02):
        self.current_price = initial_price
        self.volatility = volatility
        self.last_update = datetime.utcnow()
        self.price_history = []
        
    def get_current_price(self):
        """Возвращает текущую цену с симуляцией изменения"""
        self.update_price()
        return self.current_price
    
    def update_price(self):
        """Обновляет цену с учетом волатильности"""
        now = datetime.utcnow()
        time_diff = (now - self.last_update).total_seconds()
        
        if time_diff > 1:  # Обновляем цену каждую секунду
            # Случайное изменение цены
            change_percent = random.gauss(0, self.volatility)
            self.current_price *= (1 + change_percent)
            
            # Ограничиваем цену разумными пределами
            self.current_price = max(1000, min(10000, self.current_price))
            
            self.last_update = now
            self.price_history.append({
                'timestamp': now.timestamp() * 1000,
                'price': self.current_price
            })
            
            # Храним только последние 1000 точек
            if len(self.price_history) > 1000:
                self.price_history.pop(0)
    
    def fetch_ohlcv(self, timeframe, limit=200):
        """
        Генерирует OHLCV данные для заданного таймфрейма
        Возвращает список [timestamp, open, high, low, close, volume]
        """
        # Конвертируем таймфрейм в минуты
        tf_minutes = self._timeframe_to_minutes(timeframe)
        
        ohlcv = []
        current_time = datetime.utcnow()
        
        for i in range(limit):
            # Время для этой свечи
            candle_time = current_time - timedelta(minutes=tf_minutes * (limit - i))
            timestamp = int(candle_time.timestamp() * 1000)
            
            # Генерируем случайную цену для свечи
            base_price = self.current_price * (1 + random.gauss(0, self.volatility * (limit - i) / limit))
            
            # Генерируем OHLC
            open_price = base_price
            high_price = open_price * (1 + abs(random.gauss(0, self.volatility / 2)))
            low_price = open_price * (1 - abs(random.gauss(0, self.volatility / 2)))
            close_price = open_price + random.gauss(0, (high_price - low_price) / 2)
            close_price = max(low_price, min(high_price, close_price))
            
            volume = random.uniform(100, 1000)
            
            ohlcv.append([timestamp, open_price, high_price, low_price, close_price, volume])
        
        # Последняя свеча должна быть близка к текущей цене
        if ohlcv:
            ohlcv[-1][1] = self.current_price * 0.998  # open
            ohlcv[-1][2] = self.current_price * 1.001  # high
            ohlcv[-1][3] = self.current_price * 0.997  # low
            ohlcv[-1][4] = self.current_price  # close
        
        return ohlcv
    
    def _timeframe_to_minutes(self, timeframe):
        """Конвертирует строку таймфрейма в минуты"""
        if timeframe.endswith('m'):
            return int(timeframe[:-1])
        elif timeframe.endswith('h'):
            return int(timeframe[:-1]) * 60
        elif timeframe.endswith('d'):
            return int(timeframe[:-1]) * 1440
        else:
            return 1
