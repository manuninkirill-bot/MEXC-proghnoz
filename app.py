import os
import logging
import secrets
from dotenv import load_dotenv
from flask import Flask, render_template, jsonify, request, session, redirect, url_for
import threading
from datetime import datetime
import pandas as pd
from trading_bot import TradingBot, state, _position_lock
from telegram_notifications import TelegramNotifier

# Загружаем переменные окружения из .env файла
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

app = Flask(__name__)

# Генерируем безопасный случайный ключ если SESSION_SECRET не установлен
SESSION_SECRET = os.getenv('SESSION_SECRET')
if not SESSION_SECRET:
    SESSION_SECRET = secrets.token_hex(32)
    logging.warning("⚠️  SESSION_SECRET не установлен! Используется случайно сгенерированный ключ. Установите SESSION_SECRET в секретах для постоянства сессий между перезапусками.")

app.secret_key = SESSION_SECRET

# Глобальные переменные
bot_instance = None
bot_thread = None
bot_running = False
telegram_notifier = None

def init_telegram():
    """Инициализация Telegram уведомлений"""
    global telegram_notifier
    
    bot_token = os.getenv('TELEGRAM_BOT_TOKEN', '')
    chat_id = os.getenv('TELEGRAM_CHAT_ID', '')
    
    if bot_token and chat_id:
        telegram_notifier = TelegramNotifier(bot_token, chat_id)
        logging.info("Telegram notifier initialized")
    else:
        logging.warning("Telegram credentials not configured")

def _save_bot_running_flag(running: bool):
    """Сохраняет флаг запуска бота в файл state."""
    try:
        import json as _j
        try:
            with open("goldantilopaeth500_state.json", "r") as f:
                d = _j.load(f)
        except Exception:
            d = {}
        d["bot_was_running"] = running
        with open("goldantilopaeth500_state.json", "w") as f:
            _j.dump(d, f, default=str, indent=2)
    except Exception as e:
        logging.error(f"Failed to save bot_running flag: {e}")


def bot_main_loop():
    """Основной цикл торгового бота"""
    global bot_running, bot_instance
    
    try:
        bot_instance = TradingBot(telegram_notifier=telegram_notifier)
        logging.info("Trading bot initialized")
        
        def should_continue():
            return bot_running
        
        bot_instance.strategy_loop(should_continue=should_continue)
    except Exception as e:
        logging.error(f"Bot error: {e}", exc_info=True)
    finally:
        # Сбрасываем in-memory флаг, НО не трогаем state-файл —
        # bot_was_running в файле управляется только кнопками Start/Stop
        bot_running = False
        logging.info("🛑 Поток бота завершён")

# ── Фоновый апдейтер SAR — работает всегда, независимо от состояния бота ──
_sar_worker = None

def _sar_updater_loop():
    """Тихий фоновый поток: обновляет SAR-направления каждые 5 сек с реального MEXC"""
    import time
    try:
        helper = TradingBot(telegram_notifier=None)
        logging.info("SAR background helper initialized (MEXC real data)")
    except Exception as e:
        logging.error(f"SAR updater init error: {e}")
        return
    while True:
        try:
            dirs = helper.get_current_directions()
            if dirs and any(v is not None for v in dirs.values()):
                state['sar_directions'] = dirs
                logging.debug(f"SAR updated: {dirs}")
            price = helper.get_current_price()
            if price and price > 0:
                state['last_known_price'] = price
        except Exception as e:
            logging.warning(f"SAR updater fetch error: {e}")
        time.sleep(5)

def start_sar_updater():
    global _sar_worker
    if _sar_worker is None or not _sar_worker.is_alive():
        _sar_worker = threading.Thread(target=_sar_updater_loop, daemon=True)
        _sar_worker.start()
        logging.info("SAR background updater started")

@app.route('/')
def index():
    """Главная страница - дашборд"""
    init_price = state.get('last_known_price', 0.0)
    if bot_instance and not init_price:
        try:
            init_price = bot_instance.get_current_price() or 0.0
        except Exception:
            pass
    resp = render_template(
        'dashboard.html',
        init_balance=state.get('balance', 100.0),
        init_available=state.get('available', 100.0),
        init_price=init_price,
        bot_running=bot_running,
    )
    from flask import make_response
    r = make_response(resp)
    r.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    r.headers['Pragma'] = 'no-cache'
    r.headers['Expires'] = '0'
    return r

@app.route('/webapp')
def webapp():
    """Telegram WebApp интерфейс"""
    return render_template('webapp.html')

@app.route('/api/status')
def api_status():
    """Получение текущего статуса бота"""
    try:
        # Получаем текущие направления SAR
        directions = {}
        if bot_instance:
            directions = bot_instance.get_current_directions()
        
        # Если bot_instance еще не вернул данные, пробуем взять из state
        if not directions or all(v is None for v in directions.values()):
            directions = state.get('sar_directions', {tf: None for tf in ['1m', '3m', '5m', '15m', '30m']})
        
        # Получаем текущую цену; fallback на last_known_price если API недоступен
        current_price = state.get('last_known_price', 0.0)
        if bot_instance:
            try:
                p = bot_instance.get_current_price()
                if p:
                    current_price = p
            except Exception:
                pass
        
        return jsonify({
            'bot_running': bot_running,
            'paper_mode': os.getenv('RUN_IN_PAPER', '1') == '1',
            'balance': state.get('balance', 1000),
            'available': state.get('available', 1000),
            'positions': state.get('positions', []),
            'current_price': current_price,
            'directions': directions,
            'sar_directions': directions,
            'trades': state.get('trades', []),
            'bet': state.get('bet', 5.0),
            'trade_duration': state.get('trade_duration', 600),
            'strategy_level': state.get('strategy_level', 3),
            'strategy_tfs': state.get('strategy_tfs', ['1m', '3m', '5m']),
            'payouts': state.get('payouts', {
                '600':  {'up': None, 'down': None},
                '1800': {'up': None, 'down': None},
                '3600': {'up': None, 'down': None},
            }),
            'payout_updated_at': state.get('payout_updated_at'),
            'counter_trade': state.get('counter_trade', False),
            'council_running': state.get('council_running', False),
            'agent_stats': state.get('agent_stats', {}),
            'meetings': state.get('meetings', [])[:5],
        })
    except Exception as e:
        logging.error(f"Status error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/start_bot', methods=['POST'])
def api_start_bot():
    """Запуск торгового бота"""
    global bot_running, bot_thread
    
    if bot_running:
        return jsonify({'error': 'Бот уже запущен'}), 400
    
    try:
        bot_running = True
        _save_bot_running_flag(True)
        bot_thread = threading.Thread(target=bot_main_loop, daemon=True)
        bot_thread.start()
        
        logging.info("Trading bot started")
        return jsonify({'message': 'Бот успешно запущен', 'status': 'running'})
    except Exception as e:
        bot_running = False
        _save_bot_running_flag(False)
        logging.error(f"Start bot error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/stop_bot', methods=['POST'])
def api_stop_bot():
    """Остановка торгового бота"""
    global bot_running
    
    if not bot_running:
        return jsonify({'error': 'Бот уже остановлен'}), 400
    
    try:
        bot_running = False
        _save_bot_running_flag(False)
        logging.info("Trading bot stopped")
        return jsonify({'message': 'Бот успешно остановлен', 'status': 'stopped'})
    except Exception as e:
        logging.error(f"Stop bot error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/close_position', methods=['POST'])
def api_close_position():
    """Принудительное закрытие позиции"""
    data = request.get_json() or {}
    position_idx = data.get('position_idx', 0)
    
    if not state.get('positions') or position_idx >= len(state.get('positions')):
        return jsonify({'error': 'Позиция не найдена'}), 400
    
    try:
        if bot_instance:
            trade = bot_instance.close_position(position_idx=position_idx, close_reason='manual')
            if trade:
                return jsonify({'message': 'Позиция успешно закрыта', 'trade': trade})
            else:
                return jsonify({'error': 'Ошибка закрытия позиции'}), 500
        else:
            return jsonify({'error': 'Бот не инициализирован'}), 500
    except Exception as e:
        logging.error(f"Close position error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/set_payout', methods=['POST'])
def api_set_payout():
    """Установить процент выплаты для указанного времени и направления"""
    data = request.get_json() or {}
    duration = str(data.get('duration', '600'))
    direction = data.get('direction', 'up')   # 'up' или 'down'
    value = data.get('value')                 # число или None

    if duration not in ('600', '1800', '3600'):
        return jsonify({'error': 'Некорректная длительность'}), 400
    if direction not in ('up', 'down'):
        return jsonify({'error': 'Некорректное направление'}), 400

    if 'payouts' not in state:
        state['payouts'] = {'600': {'up': None, 'down': None},
                            '1800': {'up': None, 'down': None},
                            '3600': {'up': None, 'down': None}}

    state['payouts'][duration][direction] = float(value) if value is not None else None
    state['payout_updated_at'] = datetime.utcnow().isoformat()

    # Сохраняем в файл немедленно
    if bot_instance:
        bot_instance.save_state_to_file()
    else:
        try:
            import json
            with open("goldantilopaeth500_state.json", "w") as f:
                json.dump(state, f, default=str, indent=2)
        except Exception as e:
            logging.error(f"Payout save error: {e}")

    logging.info(f"Payout {direction} for {duration}s set to {value}%")
    return jsonify({'payouts': state['payouts'], 'payout_updated_at': state.get('payout_updated_at')})

@app.route('/api/set_strategy_level', methods=['POST'])
def api_set_strategy_level():
    """Установка уровня стратегии (1-5) — legacy"""
    data = request.get_json() or {}
    level = int(data.get('level', 3))
    if level < 1 or level > 5:
        return jsonify({'error': 'Уровень должен быть от 1 до 5'}), 400
    from trading_bot import STRATEGY_TIMEFRAMES
    state['strategy_level'] = level
    state['strategy_tfs'] = list(STRATEGY_TIMEFRAMES.get(level, STRATEGY_TIMEFRAMES[3]))
    logging.info(f"Strategy level set to {level} => tfs={state['strategy_tfs']}")
    return jsonify({'strategy_level': level, 'strategy_tfs': state['strategy_tfs']})

@app.route('/api/set_strategy_tfs', methods=['POST'])
def api_set_strategy_tfs():
    """Установка произвольного набора таймфреймов стратегии"""
    VALID_TFS = ['1m', '3m', '5m', '15m', '30m']
    data = request.get_json() or {}
    tfs = data.get('tfs', [])
    if not isinstance(tfs, list) or not tfs:
        return jsonify({'error': 'tfs должен быть непустым массивом'}), 400
    tfs = [t for t in tfs if t in VALID_TFS]
    if not tfs:
        return jsonify({'error': 'Нет допустимых таймфреймов'}), 400
    # Сортируем по порядку
    order = {tf: i for i, tf in enumerate(VALID_TFS)}
    tfs = sorted(tfs, key=lambda t: order.get(t, 99))
    state['strategy_tfs'] = tfs
    # Обновляем legacy level для совместимости
    state['strategy_level'] = 0
    logging.info(f"Strategy TFs set to {tfs}")
    return jsonify({'strategy_tfs': tfs})

@app.route('/api/set_settings', methods=['POST'])
def api_set_settings():
    """Установка ставки и длительности сделки"""
    data = request.get_json() or {}
    if 'bet' in data:
        state['bet'] = float(data['bet'])
        logging.info(f"Bet updated to ${state['bet']}")
    if 'trade_duration' in data:
        state['trade_duration'] = int(data['trade_duration'])
        logging.info(f"Trade duration updated to {state['trade_duration']}s")
    # Сохраняем в файл чтобы настройки пережили перезагрузку
    if bot_instance:
        bot_instance.save_state_to_file()
    else:
        try:
            import json
            with open("goldantilopaeth500_state.json", "w") as f:
                json.dump(state, f, default=str, indent=2)
        except Exception as e:
            logging.error(f"Settings save error: {e}")
    return jsonify({'bet': state['bet'], 'trade_duration': state['trade_duration']})

@app.route('/api/toggle_counter_trade', methods=['POST'])
def api_toggle_counter_trade():
    """Переключение режима контр трейда"""
    current = state.get('counter_trade', False)
    state['counter_trade'] = not current
    status = 'включён' if state['counter_trade'] else 'выключен'
    logging.info(f"Counter trade mode {status}")
    return jsonify({'counter_trade': state['counter_trade']})

@app.route('/api/clear_history', methods=['POST'])
def api_clear_history():
    """Очистка истории сделок"""
    state["trades"] = []
    return jsonify({'message': 'Trade history cleared'})

@app.route('/api/send_test_message', methods=['POST'])
def api_send_test_message():
    """Отправка тестового сообщения в Telegram"""
    if not telegram_notifier:
        return jsonify({'error': 'Telegram не настроен'}), 400
    
    try:
        message = f"""
🤖 <b>Тестовое уведомление</b>

Бот работает корректно и готов к отправке уведомлений!

⏰ Время: {datetime.utcnow().strftime("%H:%M:%S UTC")}
💰 Баланс: ${state.get('balance', 0):.2f}
        """.strip()
        
        success = telegram_notifier.send_message(message)
        if success:
            return jsonify({'message': 'Тестовое сообщение отправлено в Telegram'})
        else:
            return jsonify({'error': 'Ошибка отправки сообщения'}), 500
    except Exception as e:
        logging.error(f"Test message error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/telegram_info')
def api_telegram_info():
    """Получение информации о Telegram боте"""
    owner_id = os.getenv('TELEGRAM_OWNER_ID', 'NOT_SET')
    
    webhook_status = 'not_set'
    if telegram_notifier and telegram_notifier.bot_token:
        webhook_status = 'configured'
    
    return jsonify({
        'owner_id': owner_id,
        'webhook_status': webhook_status,
        'bot_configured': telegram_notifier is not None
    })

@app.route('/api/ai_poll', methods=['POST'])
def api_ai_poll():
    """Poll all 4 AI servers for LONG/SHORT recommendation"""
    try:
        from ai_advisor import poll_all_ai
        price = state.get('last_known_price', 0.0)
        if bot_instance:
            try:
                price = bot_instance.get_current_price() or price
            except Exception:
                pass

        candles_1m = []
        candles_5m = []
        if bot_instance:
            try:
                df1 = bot_instance.fetch_ohlcv_tf('1m', limit=35)
                if df1 is not None and len(df1) > 0:
                    for _, row in df1.iterrows():
                        candles_1m.append({
                            'time': pd.to_datetime(row['datetime']).strftime('%H:%M'),
                            'open': round(float(row['open']), 2),
                            'high': round(float(row['high']), 2),
                            'low':  round(float(row['low']),  2),
                            'close': round(float(row['close']), 2),
                            'volume': round(float(row.get('volume', 0)), 2),
                        })
                df5 = bot_instance.fetch_ohlcv_tf('5m', limit=15)
                if df5 is not None and len(df5) > 0:
                    for _, row in df5.iterrows():
                        candles_5m.append({
                            'time': pd.to_datetime(row['datetime']).strftime('%H:%M'),
                            'open': round(float(row['open']), 2),
                            'high': round(float(row['high']), 2),
                            'low':  round(float(row['low']),  2),
                            'close': round(float(row['close']), 2),
                            'volume': round(float(row.get('volume', 0)), 2),
                        })
            except Exception as e:
                logging.warning(f"Candle fetch for AI poll failed: {e}")

        poll_result = poll_all_ai(price, candles_1m, candles_5m)
        state['ai_poll'] = poll_result
        return jsonify(poll_result)
    except Exception as e:
        logging.error(f"AI poll error: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/ai_council', methods=['POST'])
def api_ai_council():
    """Двухраундовое заседание AI: каждый AI слышит мнение коллег и может изменить решение."""
    try:
        from ai_advisor import discuss_all_ai
        data = request.get_json(silent=True) or {}
        question = data.get('question') or None

        price = state.get('last_known_price', 0.0)
        if bot_instance:
            try:
                price = bot_instance.get_current_price() or price
            except Exception:
                pass

        candles_1m, candles_5m = [], []
        if bot_instance:
            try:
                df1 = bot_instance.fetch_ohlcv_tf('1m', limit=35)
                if df1 is not None and len(df1) > 0:
                    for _, row in df1.iterrows():
                        candles_1m.append({
                            'time':  pd.to_datetime(row['datetime']).strftime('%H:%M'),
                            'open':  round(float(row['open']),  2),
                            'high':  round(float(row['high']),  2),
                            'low':   round(float(row['low']),   2),
                            'close': round(float(row['close']), 2),
                            'volume': round(float(row.get('volume', 0)), 2),
                        })
                df5 = bot_instance.fetch_ohlcv_tf('5m', limit=15)
                if df5 is not None and len(df5) > 0:
                    for _, row in df5.iterrows():
                        candles_5m.append({
                            'time':  pd.to_datetime(row['datetime']).strftime('%H:%M'),
                            'open':  round(float(row['open']),  2),
                            'high':  round(float(row['high']),  2),
                            'low':   round(float(row['low']),   2),
                            'close': round(float(row['close']), 2),
                            'volume': round(float(row.get('volume', 0)), 2),
                        })
            except Exception as e:
                logging.warning(f"Candle fetch for AI council failed: {e}")

        meeting = discuss_all_ai(price, candles_1m, candles_5m, question=question)
        # Сохраняем последние 10 заседаний в state
        meetings = state.get('meetings', [])
        meetings.insert(0, meeting)
        state['meetings'] = meetings[:10]
        state['last_meeting'] = meeting
        return jsonify(meeting)
    except Exception as e:
        logging.error(f"AI council error: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/ai_open_position', methods=['POST'])
def api_ai_open_position():
    """Open a position manually based on AI consensus direction"""
    data = request.get_json() or {}
    side = data.get('side', 'long')
    if side not in ('long', 'short'):
        return jsonify({'error': 'Invalid side'}), 400

    current_price = state.get('last_known_price', 2300.0)
    if bot_instance:
        try:
            current_price = bot_instance.get_current_price() or current_price
        except Exception:
            pass

    duration = state.get('trade_duration', 3600)
    pos = {
        'side': side,
        'entry_price': current_price,
        'size_base': round(state.get('bet', 5.0) / max(current_price, 1), 8),
        'notional': state.get('bet', 5.0),
        'entry_time': datetime.utcnow().isoformat(),
        'close_time_seconds': duration,
        'trade_number': len(state.get('trades', [])) + 1,
        'bet': state.get('bet', 5.0),
        'source': 'ai',
    }
    # Под блокировкой: исключает гонку с bot strategy_loop
    with _position_lock:
        if state.get('positions'):
            return jsonify({'error': 'Позиция уже открыта — одновременно разрешена только одна'}), 409
        state.setdefault('positions', []).append(pos)
        state['available'] = max(0.0, state.get('available', 1000) - pos['bet'])
    logging.info(f"AI position opened: {side} @ ${current_price:.2f}")
    return jsonify({'message': f'Position {side.upper()} opened', 'position': pos})


@app.route('/api/debug_sar')
def api_debug_sar():
    """Получение отладочной информации о SAR индикаторе"""
    if not bot_instance:
        return jsonify({'error': 'Бот не инициализирован'}), 500
    
    try:
        debug_data = {
            'timestamp': datetime.utcnow().isoformat(),
            'current_price': bot_instance.get_current_price(),
            'sar_data': {}
        }
        
        for tf in ['15m', '5m', '1m']:
            df = bot_instance.fetch_ohlcv_tf(tf, limit=50)
            if df is not None and len(df) > 0:
                psar = bot_instance.compute_psar(df)
                direction = bot_instance.get_direction_from_psar(df)
                
                last_close = df['close'].iloc[-1]
                last_psar = psar.iloc[-1] if psar is not None else 0
                
                debug_data['sar_data'][tf] = {
                    'direction': direction,
                    'last_close': f"{last_close:.2f}",
                    'last_psar': f"{last_psar:.2f}",
                    'close_vs_psar': f"{(last_close - last_psar):.2f}",
                    'last_candles': [
                        {
                            'time': pd.to_datetime(row['datetime']).strftime('%H:%M'),
                            'open': f"{row['open']:.2f}",
                            'high': f"{row['high']:.2f}",
                            'low': f"{row['low']:.2f}",
                            'close': f"{row['close']:.2f}"
                        }
                        for _, row in df.tail(5).iterrows()
                    ]
                }
            else:
                debug_data['sar_data'][tf] = {'error': 'No data'}
        
        return jsonify(debug_data)
    except Exception as e:
        logging.error(f"Debug SAR error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/get_global_state')
def api_get_global_state():
    """Получение глобального состояния для Telegram бота"""
    return jsonify({
        'bot_running': bot_running,
        'balance': state.get('balance', 1000),
        'available': state.get('available', 1000),
        'in_position': state.get('in_position', False),
        'current_price': bot_instance.get_current_price() if bot_instance else 3000.0
    })

@app.route('/api/chart_data')
def api_chart_data():
    """Get 1m chart data with entry/exit markers"""
    try:
        # Return empty data if bot not running
        if not bot_instance:
            return jsonify({
                'candles': [],
                'markers': []
            })
        
        # Get last 50 candles (50 minutes of 1m data) for larger candlesticks
        df = bot_instance.fetch_ohlcv_tf('1m', limit=50)
        
        if df is None or len(df) == 0:
            return jsonify({
                'candles': [],
                'markers': []
            })
        
        # Prepare candle data
        candles = []
        for _, row in df.iterrows():
            candles.append({
                'time': pd.to_datetime(row['datetime']).strftime('%H:%M'),
                'open': float(row['open']),
                'high': float(row['high']),
                'low': float(row['low']),
                'close': float(row['close'])
            })
        
        # Get trade markers (entry/exit points)
        # Match by time string (HH:MM) instead of exact timestamp
        markers = []
        recent_trades = state.get('trades', [])[-20:]  # Last 20 trades
        
        for trade in recent_trades:
            # Try different field names for entry time
            entry_time_str = trade.get('entry_time') or trade.get('time')
            if entry_time_str:
                entry_time = datetime.fromisoformat(entry_time_str)
                
                # Entry marker - use time string for matching
                markers.append({
                    'time': entry_time.strftime('%H:%M'),
                    'price': trade.get('entry_price', trade.get('price', 0)),
                    'type': 'entry',
                    'side': trade.get('side', 'long')
                })
                
                # Exit marker
                exit_time_str = trade.get('exit_time')
                if exit_time_str:
                    exit_time = datetime.fromisoformat(exit_time_str)
                    markers.append({
                        'time': exit_time.strftime('%H:%M'),
                        'price': trade.get('exit_price', 0),
                        'type': 'exit',
                        'side': trade.get('side', 'long')
                    })
        
        # Current position marker
        if state.get('in_position') and state.get('position'):
            pos = state['position']
            entry_time_str = pos.get('entry_time')
            if entry_time_str:
                entry_time = datetime.fromisoformat(entry_time_str)
                markers.append({
                    'time': entry_time.strftime('%H:%M'),
                    'price': pos.get('entry_price', 0),
                    'type': 'entry',
                    'side': pos.get('side', 'long'),
                    'current': True
                })
        
        return jsonify({
            'candles': candles,
            'markers': markers
        })
    except Exception as e:
        logging.error(f"Chart data error: {e}")
        return jsonify({
            'candles': [],
            'markers': []
        })

@app.route('/api/pos_chart_data')
def api_pos_chart_data():
    """OHLCV closes for a given timeframe — used by position mini-charts"""
    tf = request.args.get('tf', '1m')
    limit = min(int(request.args.get('limit', 80)), 200)
    allowed = {'1m', '3m', '5m', '15m'}
    if tf not in allowed:
        return jsonify({'error': 'invalid tf'}), 400
    if not bot_instance:
        return jsonify({'prices': [], 'labels': []})
    try:
        df = bot_instance.fetch_ohlcv_tf(tf, limit=limit)
        if df is None or len(df) == 0:
            return jsonify({'prices': [], 'labels': []})
        prices = [round(float(x), 2) for x in df['close'].tolist()]
        labels = []
        for ts in df['timestamp']:
            d = datetime.utcfromtimestamp(float(ts) / 1000)
            labels.append(f"{d.hour:02d}:{d.minute:02d}")
        return jsonify({'prices': prices, 'labels': labels})
    except Exception as e:
        logging.error(f"pos_chart_data error: {e}")
        return jsonify({'prices': [], 'labels': []})


@app.route('/api/open_test_position', methods=['POST'])
def api_open_test_position():
    """Открыть тестовую позицию для проверки интерфейса"""
    data = request.get_json() or {}
    side = data.get('side', 'long')
    current_price = state.get('last_known_price', 2300.0)
    pos = {
        'side': side,
        'entry_price': current_price,
        'size_base': round(5.0 / max(current_price, 1), 8),
        'notional': 5.0,
        'entry_time': datetime.utcnow().isoformat(),
        'close_time_seconds': state.get('trade_duration', 600),
        'trade_number': len(state.get('trades', [])) + 1,
        'bet': state.get('bet', 5.0),
    }
    state.setdefault('positions', []).append(pos)
    state['available'] = state.get('available', 1000) - pos['bet']
    return jsonify({'message': 'Тестовая позиция открыта', 'position': pos})

@app.route('/api/delete_last_trade', methods=['POST'])
def api_delete_last_trade():
    """Delete the last trade from history"""
    try:
        trades = state.get('trades', [])
        if len(trades) == 0:
            return jsonify({'error': 'No trades to delete'}), 400
        
        deleted_trade = trades.pop()
        state['trades'] = trades
        
        # Save state
        if bot_instance:
            bot_instance.save_state_to_file()
        
        logging.info(f"Deleted last trade: {deleted_trade}")
        return jsonify({'message': 'Last trade deleted successfully', 'deleted_trade': deleted_trade})
    except Exception as e:
        logging.error(f"Delete trade error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/reset_balance', methods=['POST'])
def api_reset_balance():
    """Reset balance to $100 and reset trade counter"""
    try:
        state['balance'] = 100.0
        state['available'] = 100.0
        state['in_position'] = False
        state['position'] = None
        state['trades'] = []
        # Reset trade counter to start from 1
        if 'telegram_trade_counter' in state:
            del state['telegram_trade_counter']
        
        # Save state
        if bot_instance:
            bot_instance.save_state_to_file()
        
        logging.info("Balance reset to $100 and trade counter reset")
        return jsonify({'message': 'Balance reset to $100, trades cleared, counter reset to 1', 'balance': 100.0})
    except Exception as e:
        logging.error(f"Reset balance error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/send_current_position', methods=['POST'])
def api_send_current_position():
    """Send current position to Telegram"""
    try:
        if not telegram_notifier:
            return jsonify({'error': 'Telegram not configured'}), 400
        
        current_price = bot_instance.get_current_price() if bot_instance else 0
        position = state.get('position')
        balance = state.get('balance', 0)
        
        telegram_notifier.send_current_position(position, current_price, balance)
        
        logging.info("Current position sent to Telegram")
        return jsonify({'message': 'Current position sent to Telegram successfully'})
    except Exception as e:
        logging.error(f"Send position error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/verify_password', methods=['POST'])
def api_verify_password():
    """Verify dashboard password"""
    try:
        data = request.get_json()
        password = data.get('password', '')
        
        dashboard_password = os.getenv('DASHBOARD_PASSWORD', '')
        
        if not dashboard_password:
            # If no password is set, allow access
            return jsonify({'success': True})
        
        if password == dashboard_password:
            return jsonify({'success': True})
        else:
            return jsonify({'success': False})
    except Exception as e:
        logging.error(f"Password verification error: {e}")
        return jsonify({'success': False}), 500

@app.route('/webhook/telegram', methods=['POST'])
def telegram_webhook():
    """Webhook для Telegram бота"""
    if not telegram_notifier:
        return 'OK', 200
    
    try:
        update = request.get_json()
        if update and 'message' in update:
            telegram_notifier.handle_message(update['message'])
    except Exception as e:
        logging.error(f"Telegram webhook error: {e}")
    
    return 'OK', 200

# Инициализация при загрузке модуля
init_telegram()

# Загружаем сохранённые настройки из файла при старте Flask
_bot_was_running = False
try:
    import json as _json
    with open("goldantilopaeth500_state.json", "r") as _f:
        _saved = _json.load(_f)
        for _key in ("bet", "trade_duration", "balance", "available", "trades",
                     "counter_trade", "strategy_tfs", "strategy_level", "payouts"):
            if _key in _saved:
                state[_key] = _saved[_key]
        _bot_was_running = bool(_saved.get("bot_was_running", False))
        # При рестарте: если позиций нет — доступное = балансу
        if not _saved.get("positions"):
            state["available"] = state["balance"]
    logging.info(f"Settings restored: bet=${state['bet']}, duration={state['trade_duration']}s, bot_was_running={_bot_was_running}")
except Exception:
    pass  # файла нет — оставляем дефолты

start_sar_updater()

# Автозапуск бота если он был запущен до перезагрузки воркера
if _bot_was_running:
    import time as _time
    bot_running = True  # ставим True ДО паузы — UI сразу видит RUNNING
    _time.sleep(2)      # дождаться полной инициализации SAR
    bot_thread = threading.Thread(target=bot_main_loop, daemon=True)
    bot_thread.start()
    logging.info("🔄 Бот автоматически перезапущен после перезагрузки воркера")

# Настройка Telegram WebApp
try:
    from telegram_bot_handler import setup_telegram_webapp
    setup_telegram_webapp()
except Exception as e:
    logging.error(f"Failed to setup Telegram WebApp: {e}")

if __name__ == '__main__':
    # Запуск Flask приложения
    port = int(os.getenv('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
