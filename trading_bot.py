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
API_KEY = os.getenv("MEXC_API_KEY", "")
API_SECRET = os.getenv("MEXC_SECRET", "")
RUN_IN_PAPER = os.getenv("RUN_IN_PAPER", "1") == "1"
USE_SIMULATOR = os.getenv("USE_SIMULATOR", "0") == "1"

SYMBOL = "ETH/USDT:USDT"  # MEXC futures symbol format  # инструмент
LEVERAGE = 1  # No leverage - binary options style
ISOLATED = True  # изолированная маржа
FIXED_BET = 10.0  # Fixed $10 bet per trade
TIMEFRAMES = {"1m": 1, "3m": 3, "5m": 5, "15m": 15, "30m": 30}
FIXED_TRADE_SECONDS = 3600  # Fixed 1-hour trade duration
AI_POLL_INTERVAL_SECONDS = 1800  # 30 minutes between AI council sessions

# Таймфреймы, необходимые для сигнала по каждому уровню стратегии
STRATEGY_TIMEFRAMES = {
    1: ["1m"],
    2: ["1m", "3m"],
    3: ["1m", "3m", "5m"],
    4: ["1m", "3m", "5m", "15m"],
    5: ["1m", "3m", "5m", "15m", "30m"],
}
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
    "counter_trade": False,     # инвертировать сигнал (контр трейд)
    "trades": [],  # список последних сделок
    "bet": FIXED_BET,           # текущая ставка ($10 по умолчанию)
    "trade_duration": FIXED_TRADE_SECONDS,  # текущая длительность (3600 сек = 1 час)
    "strategy_level": 3,        # уровень стратегии (1-5, legacy)
    "strategy_tfs": ["1m", "3m", "5m"],  # активные таймфреймы (мультивыбор)
    "payouts": {
        "600":  {"up": None, "down": None},
        "1800": {"up": None, "down": None},
        "3600": {"up": None, "down": None},
    },
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
            logging.info("Initializing MEXC exchange connection")
            self.simulator = None
            self.exchange = ccxt.mexc({
                "apiKey": API_KEY,
                "secret": API_SECRET,
                "sandbox": False,
                "enableRateLimit": True,
                "options": {
                    "defaultType": "swap",
                }
            })
            logging.info("MEXC configured for swap/futures trading")
            
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
                # Очищаем позиции при рестарте (чтобы не закрывать несуществующие)
                if "positions" in data:
                    data["positions"] = []
                state.update(data)
                # Если позиций нет — доступное = балансу (чтобы избежать накопления ошибок)
                if not state.get("positions"):
                    state["available"] = state["balance"]
        except:
            pass

    def now(self):
        return datetime.utcnow()

    # Таймфреймы, которые MEXC не поддерживает и которые нужно синтезировать
    _SYNTH_TFS = {
        "3m": ("1m", 3),   # 3m = resampled 1m × 3
        "2m": ("1m", 2),
        "10m": ("5m", 2),
    }

    def fetch_ohlcv_tf(self, tf: str, limit=200):
        """
        Возвращает pd.DataFrame с колонками: timestamp, open, high, low, close, volume.
        Если tf не поддерживается биржей напрямую — синтезируется ресемплингом.
        """
        try:
            # Синтез неподдерживаемых TF через ресемплинг
            if not USE_SIMULATOR and tf in self._SYNTH_TFS:
                base_tf, factor = self._SYNTH_TFS[tf]
                raw = self.exchange.fetch_ohlcv(SYMBOL, timeframe=base_tf, limit=limit * factor)
                if not raw:
                    return None
                df = pd.DataFrame(raw, columns=["timestamp", "open", "high", "low", "close", "volume"])
                df["datetime"] = pd.to_datetime(df["timestamp"], unit="ms")
                df = df.set_index("datetime")
                rule = f"{factor}min"
                resampled = df.resample(rule).agg({
                    "timestamp": "first",
                    "open":      "first",
                    "high":      "max",
                    "low":       "min",
                    "close":     "last",
                    "volume":    "sum",
                }).dropna(subset=["open"]).tail(limit).reset_index(drop=True)
                return resampled

            if USE_SIMULATOR and self.simulator:
                ohlcv = self.simulator.fetch_ohlcv(tf, limit=limit)
            else:
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
        # Берём ставку из state (устанавливается с дашборда)
        notional = state.get("bet", FIXED_BET)
        base_amount = notional / price if price > 0 else 0.001  # количество базового актива (ETH)
        return base_amount, notional

    def place_market_order(self, side: str, amount_base: float):
        """
        side: 'buy' или 'sell' (для открытия позиции)
        amount_base: количество в базовой валюте (ETH)
        
        Только одна позиция одновременно — проверяется перед вызовом.
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
            
            # Берём реальную ставку из позиции (не константу)
            bet_used = pos.get("bet", FIXED_BET)

            # Binary payout: +80% от ставки при WIN, -100% ставки при LOSE
            if is_win:
                pnl = bet_used * 0.80   # +80% прибыль
                result = "WIN"
            else:
                pnl = -bet_used          # -100% ставки
                result = "LOSE"

            state["available"] += bet_used + pnl  # Возвращаем ставку + PnL
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

    def _build_trade_analysis(self, trade: dict) -> str:
        """Генерирует текстовый анализ завершённой сделки для передачи AI-совету."""
        side = trade.get("side", "?").upper()
        result = trade.get("result", "?")
        entry = float(trade.get("entry_price", 0))
        exit_p = float(trade.get("exit_price", 0))
        pnl = float(trade.get("pnl", 0))
        pct = (exit_p - entry) / entry * 100 if entry else 0
        price_move = "UP" if exit_p > entry else "DOWN"
        won = result == "WIN"
        correct = (side == "LONG" and price_move == "UP") or (side == "SHORT" and price_move == "DOWN")
        hint = "The previous signal was CORRECT — trend may continue." if correct else \
               "The previous signal was WRONG — consider if a reversal is still in play."
        return (
            f"Direction: {side} → Result: {result} (PnL: ${pnl:+.2f})\n"
            f"Entry: ${entry:.2f} → Exit: ${exit_p:.2f} (price moved {price_move} by {abs(pct):.3f}%)\n"
            f"{hint}"
        )

    def _run_council_and_open(self, df_1m, label: str = "") -> bool:
        """Созывает AI-совет и при консенсусе открывает позицию. Возвращает True если позиция открыта."""
        state["council_running"] = True
        try:
            return self._run_council_and_open_inner(df_1m, label)
        finally:
            state["council_running"] = False

    def _run_council_and_open_inner(self, df_1m, label: str = "") -> bool:
        from ai_advisor import discuss_all_ai
        # Защита: не открываем если уже есть открытая позиция
        if state.get("positions"):
            logging.info("🚫 Позиция уже открыта — пропускаем совет")
            return False
        price = state.get("last_known_price") or self.get_current_price()
        candles_1m = []
        if df_1m is not None:
            for _, row in df_1m.iterrows():
                candles_1m.append({
                    'time': pd.to_datetime(row['datetime']).strftime('%H:%M'),
                    'open': round(float(row['open']), 2),
                    'high': round(float(row['high']), 2),
                    'low':  round(float(row['low']),  2),
                    'close': round(float(row['close']), 2),
                    'volume': round(float(row.get('volume', 0)), 2),
                })
        trade_dur = int(state.get("trade_duration", 600))
        # Для 60-мин сделок нужно больше 5m свечей
        limit_5m = 20 if trade_dur >= 3600 else 15
        candles_5m = []
        df_5m = self.fetch_ohlcv_tf('5m', limit=limit_5m)
        if df_5m is not None:
            for _, row in df_5m.iterrows():
                candles_5m.append({
                    'time': pd.to_datetime(row['datetime']).strftime('%H:%M'),
                    'open': round(float(row['open']), 2),
                    'high': round(float(row['high']), 2),
                    'low':  round(float(row['low']),  2),
                    'close': round(float(row['close']), 2),
                    'volume': round(float(row.get('volume', 0)), 2),
                })

        last_analysis = state.get("last_trade_analysis")
        mins = trade_dur // 60
        logging.info(f"🏛️ {label}Созываем AI совет @ ${price:.2f} (горизонт {mins}м, 2 раунда голосования…)")
        meeting = discuss_all_ai(price, candles_1m, candles_5m,
                                 last_trade_analysis=last_analysis,
                                 trade_duration_sec=trade_dur)

        meetings = state.get('meetings', [])
        meetings.insert(0, meeting)
        state['meetings'] = meetings[:10]
        state['last_meeting'] = meeting
        state["ai_poll"] = {
            "consensus": meeting["consensus"],
            "long_votes": meeting["long_votes"],
            "short_votes": meeting["short_votes"],
            "results": meeting["round2"],
        }
        logging.info(f"🏛️ AI совет: LONG={meeting['long_votes']} SHORT={meeting['short_votes']} → {meeting['consensus'].upper()}")

        if meeting["consensus"] in ("long", "short"):
            consensus = meeting["consensus"]

            # ── Фильтр 1: Защита от серии убытков (2 подряд → пропуск) ──
            recent_trades = state.get("trades", [])[:2]
            consecutive_losses = sum(1 for t in recent_trades if t.get("result") == "LOSE")
            skip_remaining = state.get("skip_council_count", 0)
            if skip_remaining > 0:
                state["skip_council_count"] = skip_remaining - 1
                logging.info(f"🛡️ Фильтр серий: пропускаем совет (осталось пропусков: {skip_remaining})")
                return False
            if consecutive_losses >= 2:
                state["skip_council_count"] = 1
                logging.info(f"🛡️ 2 убытка подряд — следующий совет будет пропущен (защита активирована)")

            # ── Фильтр 2: Направление свечей (3 из 5 должны совпадать) ──
            recent_5 = candles_1m[-5:] if len(candles_1m) >= 5 else candles_1m
            bull_c = sum(1 for c in recent_5 if c['close'] > c['open'])
            bear_c = len(recent_5) - bull_c
            candle_ok = True
            if consensus == "short" and bull_c >= 3:
                logging.info(f"🚫 Фильтр свечей: AI говорит SHORT но {bull_c}/5 свечей бычьи — пропускаем")
                candle_ok = False
            elif consensus == "long" and bear_c >= 3:
                logging.info(f"🚫 Фильтр свечей: AI говорит LONG но {bear_c}/5 свечей медвежьи — пропускаем")
                candle_ok = False
            if not candle_ok:
                return False

            # ── Фильтр 3: RSI подтверждение ──
            closes = [c['close'] for c in candles_1m[-16:]]
            rsi_ok = True
            if len(closes) >= 15:
                gains = [max(0, closes[i] - closes[i-1]) for i in range(1, len(closes))]
                losses = [max(0, closes[i-1] - closes[i]) for i in range(1, len(closes))]
                avg_gain = sum(gains[-14:]) / 14
                avg_loss = sum(losses[-14:]) / 14
                rs = avg_gain / avg_loss if avg_loss > 0 else 100
                rsi = 100 - (100 / (1 + rs))
                if consensus == "short" and rsi < 45:
                    logging.info(f"🚫 Фильтр RSI: SHORT при RSI={rsi:.1f} (<45, не медвежий) — пропускаем")
                    rsi_ok = False
                elif consensus == "long" and rsi > 55:
                    logging.info(f"🚫 Фильтр RSI: LONG при RSI={rsi:.1f} (>55, не бычий) — пропускаем")
                    rsi_ok = False
                else:
                    logging.info(f"✅ Фильтр RSI: RSI={rsi:.1f} — OK для {consensus.upper()}")
            if not rsi_ok:
                return False

            # ── Фильтр 4: SMA направление (только проверка конфликта) ──
            if len(candles_1m) >= 20:
                c5 = [c['close'] for c in candles_1m[-5:]]
                c20 = [c['close'] for c in candles_1m[-20:]]
                sma5 = sum(c5) / len(c5)
                sma20 = sum(c20) / len(c20)
                sma_gap = abs(sma5 - sma20) / sma20 * 100
                sma_dir = "SHORT" if sma5 < sma20 else "LONG"
                if sma_dir != consensus.upper():
                    logging.info(f"🚫 Фильтр SMA: SMA говорит {sma_dir} но AI говорит {consensus.upper()} — конфликт, пропускаем")
                    return False
                logging.info(f"✅ Фильтр SMA: gap={sma_gap:.3f}%, SMA→{sma_dir} совпадает с {consensus.upper()}")

            effective_dir = consensus
            if state.get("counter_trade", False):
                effective_dir = "short" if effective_dir == "long" else "long"
                logging.info(f"🔄 Counter trade: {consensus.upper()} → {effective_dir.upper()}")

            side = "buy" if effective_dir == "long" else "sell"
            cur_price = self.get_current_price() or price
            size_base, notional = self.compute_order_size_usdt(state["balance"], cur_price if cur_price > 0 else 1.0)
            logging.info(f"✅ AI OPEN {side.upper()} ${notional} — size={size_base:.6f} @ ${cur_price}")
            self.place_market_order(side, amount_base=size_base)
            self.save_state_to_file()
            return True
        else:
            logging.info("➖ Нет консенсуса AI — повтор через 60 сек")
            return False

    def strategy_loop(self, should_continue=lambda: True):
        """AI Council strategy: совет сразу при старте и после каждого закрытия позиции."""
        logging.info(f"Starting AI Council strategy loop. RUN_IN_PAPER={RUN_IN_PAPER}")

        first_run = True
        # Время следующего повторного совета при NONE-консенсусе (0 = не запланирован)
        retry_council_at = 0.0

        while should_continue():
            try:
                now_ts = time.time()

                # 1) Обновляем кэш цены из 1m свечей
                df_1m = self.fetch_ohlcv_tf('1m', limit=35)
                if df_1m is not None and len(df_1m) > 0:
                    state["last_known_price"] = float(df_1m["close"].iloc[-1])

                # 2) Первый старт — совет сразу если нет позиций
                if first_run:
                    first_run = False
                    if not state.get("positions"):
                        opened = self._run_council_and_open(df_1m, label="[старт] ")
                        if not opened:
                            retry_council_at = time.time() + 60
                    time.sleep(5)
                    continue

                # 3) Закрываем просроченные позиции
                position_just_closed = False
                for i in range(len(state["positions"]) - 1, -1, -1):
                    pos = state["positions"][i]
                    entry_t = datetime.fromisoformat(pos["entry_time"])
                    trade_duration = (datetime.utcnow() - entry_t).total_seconds()
                    position_close_time = pos.get("close_time_seconds", FIXED_TRADE_SECONDS)
                    if trade_duration >= position_close_time:
                        logging.info(f"⏱️ Closing position {i} after {trade_duration:.1f}s")
                        trade = self.close_position(position_idx=i, close_reason="fixed_time")
                        self.save_state_to_file()
                        if trade:
                            analysis = self._build_trade_analysis(trade)
                            state["last_trade_analysis"] = analysis
                            logging.info(f"📊 Анализ сделки: {analysis.replace(chr(10), ' | ')}")
                        position_just_closed = True

                # 4) После закрытия — сразу совет
                if position_just_closed and not state.get("positions"):
                    opened = self._run_council_and_open(df_1m, label="[после закрытия] ")
                    if not opened:
                        retry_council_at = time.time() + 60
                    else:
                        retry_council_at = 0.0

                # 5) Повтор совета если был NONE и прошло 60 сек (и нет открытых позиций)
                elif not state.get("positions") and retry_council_at > 0 and now_ts >= retry_council_at:
                    logging.info("🔁 Повтор AI совета (предыдущий был NONE)…")
                    opened = self._run_council_and_open(df_1m, label="[повтор] ")
                    retry_council_at = 0.0 if opened else time.time() + 60

                time.sleep(5)
            except Exception as e:
                logging.error(f"AI strategy loop error: {e}", exc_info=True)
                time.sleep(5)
