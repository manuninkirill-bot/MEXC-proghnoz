import os
import time
import json
import threading
import random
from datetime import datetime, timedelta

import ccxt
import pandas as pd
from ta.trend import PSARIndicator
import logging
from market_simulator import MarketSimulator
from signal_sender import SignalSender
# Google Sheets integration removed

# ========== Конфигурация ==========
API_KEY = os.getenv("ASCENDEX_API_KEY", "")
API_SECRET = os.getenv("ASCENDEX_SECRET", "")
RUN_IN_PAPER = os.getenv("RUN_IN_PAPER", "1") == "1"
USE_SIMULATOR = os.getenv("USE_SIMULATOR", "0") == "1"  # Переключаемся на реальные данные с новыми API ключами

SYMBOL = "ETH/USDT:USDT"  # ASCENDEX futures symbol format  # инструмент
LEVERAGE = 1  # No leverage - binary options style
ISOLATED = True  # изолированная маржа
FIXED_BET = 5.0  # Fixed $5 bet per trade (binary options)
TIMEFRAMES = {"1m": 1, "5m": 5, "15m": 15}  # 1m and 15m used for alignment, 5m for info
FIXED_TRADE_SECONDS = 600  # Fixed 10-minute trade duration
MIN_PAYOUT_THRESHOLD = 0.80  # Минимальный процент выплаты для открытия сделки (80%)
PAUSE_BETWEEN_TRADES = 0  # пауза между сделками убрана
START_BANK = 100.0  # стартовый банк (для бумажной торговли / учета)
DASHBOARD_MAX = 20

# ========== Глобальные переменные состояния ==========
state = {
    "balance": START_BANK,
    "available": START_BANK,
    "positions": [], # list of active position dicts
    "last_trade_time": None,
    "last_1m_dir": None,
    "one_min_flip_count": 0,
    "skip_next_signal": False,  # пропускать следующий сигнал входа
    "trades": [],  # список последних сделок
    "bet": FIXED_BET,           # текущая ставка ($5 по умолчанию)
    "trade_duration": FIXED_TRADE_SECONDS  # текущая длительность (600 сек = 10 мин)
}

class TradingBot:
    def __init__(self, telegram_notifier=None):
        self.notifier = telegram_notifier
        self.signal_sender = SignalSender()
        # Google Sheets integration removed
        
        # Выбираем режим работы: симулятор или реальная биржа
        if USE_SIMULATOR:
            logging.info("Initializing market simulator")
            self.simulator = MarketSimulator(initial_price=60000, volatility=0.02)
            self.exchange = None
        else:
            logging.info("Initializing ASCENDEX exchange connection")
            self.simulator = None
            self.exchange = ccxt.ascendex({
                "apiKey": API_KEY,
                "secret": API_SECRET,
                "sandbox": False,
                "enableRateLimit": True,
                "options": {
                    "defaultType": "swap",  # Enable futures/swap trading for leverage
                }
            })
            logging.info("ASCENDEX configured for swap/futures trading with leverage support")
            
            # Configure leverage and margin mode during initialization
            if API_KEY and API_SECRET:
                try:
                    # Set margin mode to isolated
                    if ISOLATED:
                        self.exchange.set_margin_mode('isolated', SYMBOL)
                        logging.info(f"Margin mode set to ISOLATED for {SYMBOL}")
                    
                    # Set leverage
                    self.exchange.set_leverage(LEVERAGE, SYMBOL)
                    logging.info(f"Leverage set to {LEVERAGE}x for {SYMBOL}")
                except Exception as e:
                    logging.error(f"Failed to configure leverage/margin mode: {e}")
                    logging.error("Trading will continue in paper mode to avoid order rejections")
        
        self.load_state_from_file()
        
    def save_state_to_file(self):
        try:
            with open("goldantilopaeth500_state.json", "w") as f:
                json.dump(state, f, default=str, indent=2)
        except Exception as e:
            logging.error(f"Save error: {e}")

    def load_state_from_file(self):
        try:
            with open("goldantilopaeth500_state.json", "r") as f:
                data = json.load(f)
                # Clear old positions on startup to avoid closing them immediately
                if "positions" in data:
                    data["positions"] = []
                state.update(data)
        except:
            pass

    def now(self):
        return datetime.utcnow()

    def fetch_ohlcv_tf(self, tf: str, limit=200):
        """
        Возвращает pd.DataFrame с колонками: timestamp, open, high, low, close, volume
        """
        try:
            if USE_SIMULATOR and self.simulator:
                # Используем симулятор
                ohlcv = self.simulator.fetch_ohlcv(tf, limit=limit)
            else:
                # Используем реальную биржу
                ohlcv = self.exchange.fetch_ohlcv(SYMBOL, timeframe=tf, limit=limit)
            
            if not ohlcv:
                return None
                
            df = pd.DataFrame(ohlcv)
            df.columns = ["timestamp", "open", "high", "low", "close", "volume"]
            df["datetime"] = pd.to_datetime(df["timestamp"], unit="ms")
            return df
        except Exception as e:
            logging.error(f"Error fetching {tf} ohlcv: {e}")
            return None

    def compute_psar(self, df: pd.DataFrame):
        """
        Возвращает Series с PSAR (последняя точка).
        Используем ta.trend.PSARIndicator
        """
        if df is None or len(df) < 5:
            return None
        try:
            high_series = pd.Series(df["high"].values)
            low_series = pd.Series(df["low"].values)
            close_series = pd.Series(df["close"].values)
            # Повышенная чувствительность SAR (увеличены step и max_step умеренно)
            psar_ind = PSARIndicator(high=high_series, low=low_series, close=close_series, step=0.05, max_step=0.5)
            psar = psar_ind.psar()
            return psar
        except Exception as e:
            logging.error(f"PSAR compute error: {e}")
            return None

    def get_direction_from_psar(self, df: pd.DataFrame):
        """
        Возвращает направление 'long' или 'short' на основе сравнения последней close и psar
        """
        psar = self.compute_psar(df)
        if psar is None:
            return None
        last_psar = psar.iloc[-1]
        last_close = df["close"].iloc[-1]
        return "long" if last_close > last_psar else "short"


    def get_current_directions(self):
        """Get current PSAR directions for all timeframes"""
        directions = {}
        for tf in TIMEFRAMES.keys():
            df = self.fetch_ohlcv_tf(tf)
            if df is not None:
                directions[tf] = self.get_direction_from_psar(df)
            else:
                directions[tf] = None
        return directions

    def compute_order_size_usdt(self, balance, price):
        # Binary options: fixed $5 bet, no leverage
        notional = FIXED_BET
        base_amount = notional / price if price > 0 else 0.001  # количество базового актива (ETH)
        return base_amount, notional

    def place_market_order(self, side: str, amount_base: float):
        """
        side: 'buy' или 'sell' (для открытия позиции)
        amount_base: количество в базовой валюте (ETH)
        
        Multiple simultaneous positions allowed.
        """
        logging.info(f"[{self.now()}] PLACE MARKET ORDER -> side={side}, amount={amount_base:.6f}")

        # Читаем текущие настройки ставки и длительности из state
        current_bet = state.get("bet", FIXED_BET)
        current_duration = state.get("trade_duration", FIXED_TRADE_SECONDS)
        
        # Маппинг длительности в timeUnit для ngrok
        duration_to_time_unit = {600: "M10", 1800: "M30", 3600: "H1"}
        ngrok_time_unit = duration_to_time_unit.get(int(current_duration), "M10")

        if RUN_IN_PAPER or API_KEY == "" or API_SECRET == "":
            # Бумажная торговля — симулируем ордер
            price = self.get_current_price()
            entry_price = price
            entry_time = datetime.utcnow()
            notional = current_bet
            
            # Вычитаем ставку из доступного баланса
            state["available"] -= current_bet
            
            close_time_seconds = current_duration
            
            # Генерируем номер сделки для Telegram (отдельный счетчик)
            if "telegram_trade_counter" not in state:
                state["telegram_trade_counter"] = 1
            else:
                state["telegram_trade_counter"] += 1
            trade_number = state["telegram_trade_counter"]
            
            pos = {
                "side": "long" if side == "buy" else "short",
                "entry_price": entry_price,
                "size_base": amount_base,
                "notional": notional,
                "entry_time": entry_time.isoformat(),
                "close_time_seconds": close_time_seconds,
                "trade_number": trade_number,
                "bet": current_bet
            }
            state["positions"].append(pos)
            state["last_trade_time"] = entry_time.isoformat()
            
            duration_min = int(current_duration // 60)
            logging.info(f"Position opened: bet=${current_bet} duration={duration_min}min timeUnit={ngrok_time_unit}")
            
            # Send Telegram notification for position opening
            if self.notifier:
                self.notifier.send_position_opened(pos, price, trade_number, state["balance"])
            
            # Send signal to ngrok with correct timeUnit and quantity
            if pos["side"] == "long":
                self.signal_sender.send_open_long(time_unit=ngrok_time_unit, quantity=str(int(current_bet)))
            else:
                self.signal_sender.send_open_short(time_unit=ngrok_time_unit, quantity=str(int(current_bet)))
            
            return pos
        else:
            # Реальная торговля
            try:
                try:
                    self.exchange.set_leverage(LEVERAGE, SYMBOL)
                except Exception as e:
                    logging.error(f"set_leverage failed: {e}")

                order = self.exchange.create_market_buy_order(SYMBOL, amount_base) if side == "buy" else self.exchange.create_market_sell_order(SYMBOL, amount_base)
                logging.info(f"Order response: {order}")
                
                entry_price = float(order.get("average", order.get("price", self.get_current_price())))
                entry_time = datetime.utcnow()
                notional = amount_base * entry_price
                margin = notional / LEVERAGE
                
                state["available"] -= margin
                close_time_seconds = current_duration
                
                pos = {
                    "side": "long" if side == "buy" else "short",
                    "entry_price": entry_price,
                    "size_base": amount_base,
                    "notional": notional,
                    "margin": margin,
                    "entry_time": entry_time.isoformat(),
                    "close_time_seconds": close_time_seconds,
                    "bet": current_bet
                }
                state["positions"].append(pos)
                state["last_trade_time"] = entry_time.isoformat()
                
                logging.info(f"Position opened: bet=${current_bet} duration={int(current_duration//60)}min")
                
                if pos["side"] == "long":
                    self.signal_sender.send_open_long(time_unit=ngrok_time_unit, quantity=str(int(current_bet)))
                else:
                    self.signal_sender.send_open_short(time_unit=ngrok_time_unit, quantity=str(int(current_bet)))
                
                return pos
            except Exception as e:
                logging.error(f"place_market_order error: {e}")
                return None

    def close_position(self, position_idx=0, close_reason="unknown"):
        if not state["positions"] or position_idx >= len(state["positions"]):
            return None
            
        pos = state["positions"][position_idx]
        side = pos["side"]
        size = pos["size_base"]
        
        # Для закрытия: делаем ордер в противоположную сторону
        close_side = "sell" if side == "long" else "buy"
        logging.info(f"[{self.now()}] CLOSE POSITION -> {close_side} {size:.6f}")
        
        if RUN_IN_PAPER or API_KEY == "" or API_SECRET == "":
            # симуляция: считаем результат PnL по цене закрытия
            price = self.get_current_price()
            entry_price = pos["entry_price"]
            notional = pos["notional"]
            
            # Binary options outcome: WIN if price went up, LOSE if price went down
            if pos["side"] == "long":
                is_win = price > entry_price
            else:
                is_win = price < entry_price
            
            # Binary payout: +80% of bet if win, -100% (lose the bet) if lose
            if is_win:
                pnl = FIXED_BET * 0.80  # +80% profit
                result = "WIN"
            else:
                pnl = -FIXED_BET  # -100% loss (lose the bet)
                result = "LOSE"
            
            state["available"] += FIXED_BET + pnl  # Return the bet + profit/loss
            state["balance"] = state["available"]
            
            trade = {
                "time": datetime.utcnow().isoformat(),
                "side": pos["side"],
                "entry_price": entry_price,
                "exit_price": price,
                "size_base": size,
                "pnl": pnl,
                "notional": notional,
                "duration": self.calculate_duration(pos["entry_time"]),
                "close_reason": close_reason,
                "result": result
            }
            
            # Send Telegram notification for position closing
            if self.notifier:
                trade_number = pos.get("trade_number", 1)
                self.notifier.send_position_closed(trade, trade_number, state["balance"])
            
            # Send signal to external service
            if pos["side"] == "long":
                self.signal_sender.send_close_long()
            else:
                self.signal_sender.send_close_short()
            
            self.append_trade(trade)
            
            # сброс позиции
            state["positions"].pop(position_idx)
            state["last_trade_time"] = datetime.utcnow().isoformat()
            self.save_state_to_file()
            return trade
        else:
            try:
                # реальный ордер закрытия
                if side == "long":
                    order = self.exchange.create_market_sell_order(SYMBOL, size)
                else:
                    order = self.exchange.create_market_buy_order(SYMBOL, size)
                    
                logging.info(f"Close order response: {order}")
                
                # Получаем цену закрытия
                exit_price = float(order.get("average", order.get("price", self.get_current_price())))
                entry_price = pos["entry_price"]
                
                if pos["side"] == "long":
                    pnl = (exit_price - entry_price) * size
                else:
                    pnl = (entry_price - exit_price) * size
                    
                fee = abs(pos["notional"]) * 0.0003
                pnl_after_fee = pnl - fee
                
                # Возвращаем маржу + PnL
                margin = pos.get("margin", abs(pos["notional"]) / LEVERAGE)
                state["available"] += margin + pnl_after_fee  # Возвращаем маржу + PnL
                state["balance"] = state["available"]
                
                trade = {
                    "time": datetime.utcnow().isoformat(),
                    "side": pos["side"],
                    "entry_price": entry_price,
                    "exit_price": exit_price,
                    "size_base": size,
                    "pnl": pnl_after_fee,
                    "notional": pos["notional"],
                    "duration": self.calculate_duration(pos["entry_time"]),
                    "close_reason": close_reason
                }
                
                self.append_trade(trade)
                
                # Send signal to external service
                if trade["side"] == "long":
                    self.signal_sender.send_close_long()
                else:
                    self.signal_sender.send_close_short()
                
                state["positions"].pop(position_idx)
                self.save_state_to_file()
                return trade
            except Exception as e:
                logging.error(f"close_position error: {e}")
                return None

    def calculate_duration(self, entry_time_str):
        """Calculate trade duration in human readable format"""
        try:
            entry_time = datetime.fromisoformat(entry_time_str.replace('Z', '+00:00'))
            duration = datetime.utcnow() - entry_time
            
            minutes = int(duration.total_seconds() // 60)
            seconds = int(duration.total_seconds() % 60)
            
            if minutes > 0:
                return f"{minutes}м {seconds}с"
            else:
                return f"{seconds}с"
        except:
            return "N/A"

    def append_trade(self, trade):
        state["trades"].insert(0, trade)
        # keep only last DASHBOARD_MAX
        state["trades"] = state["trades"][:DASHBOARD_MAX]

    def get_current_price(self):
        try:
            if USE_SIMULATOR and self.simulator:
                return self.simulator.get_current_price()
            else:
                ticker = self.exchange.fetch_ticker(SYMBOL)
                price = float(ticker["last"])
                state["last_known_price"] = price
                return price
        except Exception as e:
            logging.warning(f"fetch ticker failed, using last candle close: {e}")
            # Use last close from 1m OHLCV — already being fetched in the strategy loop
            try:
                df = self.fetch_ohlcv_tf("1m", limit=2)
                if df is not None and len(df) > 0:
                    price = float(df["close"].iloc[-1])
                    state["last_known_price"] = price
                    return price
            except Exception as e2:
                logging.error(f"ohlcv fallback also failed: {e2}")
            # Last resort: use cached price if available
            if state.get("last_known_price"):
                return state["last_known_price"]
            return 3000.0

    def strategy_loop(self, should_continue=lambda: True):
        logging.info(f"Starting strategy loop. RUN_IN_PAPER={RUN_IN_PAPER}")
        
        while should_continue():
            try:
                # 1) Получаем свечи и направления
                dfs = {}
                dirs = {}
                for tf in TIMEFRAMES.keys():
                    df = self.fetch_ohlcv_tf(tf)
                    dfs[tf] = df
                    if df is not None:
                        dirs[tf] = self.get_direction_from_psar(df)
                    else:
                        dirs[tf] = None

                # пропускаем итерацию, если нет данных
                if any(d is None for d in dirs.values()):
                    time.sleep(5)
                    continue

                # Cache last close from 1m candles as a reliable price reference
                if dfs.get("1m") is not None and len(dfs["1m"]) > 0:
                    state["last_known_price"] = float(dfs["1m"]["close"].iloc[-1])

                dir_1m = dirs["1m"]
                dir_15m = dirs["15m"]
                
                logging.info(f"[{self.now()}] SAR directions => 1m:{dir_1m} 15m:{dir_15m}")
                
                # Store current SAR directions for status reporting
                self._current_sar_directions = dirs

                # Проверка на закрытие (если есть позиции)
                for i in range(len(state["positions"]) - 1, -1, -1):
                    pos = state["positions"][i]
                    entry_t = datetime.fromisoformat(pos["entry_time"])
                    trade_duration = (datetime.utcnow() - entry_t).total_seconds()
                    
                    # Принудительное закрытие по фиксированному времени (10 минут = 600 сек)
                    position_close_time = pos.get("close_time_seconds", FIXED_TRADE_SECONDS)
                    if trade_duration >= position_close_time:
                        logging.info(f"⏱️ Closing position {i} after {trade_duration:.1f}s (10 min limit reached)")
                        self.close_position(position_idx=i, close_reason="fixed_time")
                        state["skip_next_signal"] = True  # устанавливаем флаг пропуска
                        self.save_state_to_file()
                
                # Отслеживание смены 1m SAR для сброса флага пропуска
                if state["last_1m_dir"] and state["last_1m_dir"] != dir_1m:
                    if state["skip_next_signal"]:
                        logging.info(f"✅ Resetting skip flag after 1m SAR change: {state['last_1m_dir']} -> {dir_1m}")
                        state["skip_next_signal"] = False
                        self.save_state_to_file()
                
                # Убираем вебхук из place_market_order — сигнал уходит через signal_sender
                
                # Сохраняем текущее направление для отслеживания смен
                state["last_1m_dir"] = dir_1m
                
                dir_5m = dirs.get("5m")
                
                # Вход когда ВСЕ три таймфрейма 1m, 5m и 15m SAR совпадают
                all_align = (
                    dir_1m in ["long", "short"] and
                    dir_5m == dir_1m and
                    dir_15m == dir_1m
                )
                
                if all_align and not state["skip_next_signal"]:
                    logging.info(f"✅ Entry signal: 1m=5m=15m SAR = {dir_1m.upper()}")
                    
                    # вход в позицию
                    side = "buy" if dir_1m == "long" else "sell"
                    price = self.get_current_price()
                    # compute order size
                    size_base, notional = self.compute_order_size_usdt(state["balance"], price if price > 0 else 1.0)
                    logging.info(f"Signal to OPEN {side} — size_base={size_base:.6f} notional=${notional:.2f} price={price}")
                    
                    # Place order
                    self.place_market_order(side, amount_base=size_base)
                    
                    # Блокируем повторный вход до следующего флипа 1m SAR
                    state["skip_next_signal"] = True
                    
                    self.save_state_to_file()
                    time.sleep(1)
                elif state["skip_next_signal"] and all_align:
                    logging.info(f"🔄 Skip flag active: 1m:{dir_1m} 5m:{dir_5m} 15m:{dir_15m} — wait for SAR flip")

                time.sleep(5)  # маленькая пауза в основном цикле
            except Exception as e:
                logging.error(f"Main loop error: {e}")
                time.sleep(5)
