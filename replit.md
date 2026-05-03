# Overview

This project is a binary options trading bot for ETH/USDT (MEXC). Trading decisions are made by **polling 7 AI servers** (ChatGPT, Gemini, Grok, DeepSeek, Groq, OpenRouter, Mistral) — every 5 minutes the bot asks each AI whether ETH price will go UP or DOWN in the next 10 minutes, takes the majority vote, and opens a $5 position for 10 minutes. The system includes a Flask-based web dashboard for monitoring, optional Telegram notifications, and a market simulator for testing.

## AI Trading Loop (trading_bot.py → strategy_loop)
- `AI_POLL_INTERVAL_SECONDS = 300` (5 min between polls)
- `FIXED_TRADE_SECONDS = 600` (10 min position duration)
- Skip new poll if a position is already open
- `counter_trade` flag inverts the consensus direction
- Free AI keys: `GROQ_API_KEY`, `OPENROUTER_API_KEY`, `MISTRAL_API_KEY` (Groq=Llama 3.3 70B, OpenRouter=google/gemma-4-31b-it:free, Mistral=mistral-small-latest)
- Paid keys: `OPENAI_API_KEY`, `GEMINI_API_KEY` (gemini-2.5-flash with thinkingBudget=0), `XAI_API_KEY`, `DEEPSEEK_API_KEY`

# User Preferences

Preferred communication style: Simple, everyday language.

# System Architecture

## Frontend Architecture
- **Framework**: Vanilla JavaScript with Bootstrap 5
- **Design Pattern**: Single Page Application (SPA) with polling for real-time updates (every 3 seconds)
- **UI Components**: Dark theme trading dashboard with:
  - Balance display and current price
  - Active position with 10-minute countdown timer
  - Real-time profit/loss status indicator (green if in profit, red if in loss)
  - SAR indicators (1m/5m/15m) for reference
  - Trade entry signals based on 1m+15m alignment
  - Trade history
- **Result Modal**: WIN/LOSE outcome window showing trade result and P&L

## Backend Architecture
- **Framework**: Flask with Python
- **Design Pattern**: Modular architecture separating trading logic, notifications, and web interface
- **Core Components**:
    - `TradingBot` class: Manages exchange integration, SAR calculations, and position management
    - `MarketSimulator` class: Provides realistic market data
    - `TelegramNotifier` class: Handles Telegram notification delivery
    - Flask app: Serves the web dashboard and REST API endpoints
- **Threading Model**: A main Flask thread and a background trading thread ensure continuous market monitoring

## Trading Strategy - Binary Options Style
- **Algorithm**: Parabolic SAR strategy (SAR only)
- **Entry Condition**: A position is opened when 1m and 15m SAR directions align (both LONG or both SHORT)
- **Exit Condition**: Position is closed after exactly 10 minutes
- **Position Monitoring**: Real-time display shows:
  - Entry and current prices
  - Countdown timer (starts from 10:00, counts down to 0:00)
  - Status indicator (✓ IN PROFIT / ✗ IN LOSS) updated every second
- **Bet System**: 
    - Fixed $5 bet per trade (no leverage)
    - WIN: Price goes up for LONG or down for SHORT → +80% profit ($4 gain)
    - LOSE: Price goes down for LONG or up for SHORT → -100% loss (lose the $5 bet)
- **Position Limit**: Only 1 position can be open at a time
- **Operating Mode**: Paper trading mode with starting bank of $100
- **Instrument**: ETH/USDT

## Data Storage
- **State Persistence**: Bot state and trading history stored in JSON files
- **In-Memory Storage**: A global state dictionary facilitates real-time data sharing
- **Trades Array**: Maintains recent trade history for dashboard display

## Authentication & Security
- **API Security**: API keys for exchange integration managed via environment variables
- **Session Management**: Flask secret key used for basic session security
- **Dashboard Control**: No password protection on control buttons (manual close position, reset balance, etc.)

# External Dependencies

## Trading Exchange
- **ASCENDEX API**: Used for cryptocurrency exchange integration (can be disabled for paper trading)
- **ccxt library**: Employed for unified exchange API interaction

## Notification Services
- **Telegram Bot API**: Used for real-time trade notifications (optional)

## Technical Analysis
- **Python TA library**: Utilized for Parabolic SAR indicator calculations (PSARIndicator)
- **Pandas**: Used for OHLCV data processing across 1m, 5m, and 15m timeframes

## Frontend Libraries
- **Bootstrap 5**: Provides the CSS framework for responsive UI design
- **Font Awesome**: Supplies icon library for UI elements

## Python Libraries
- **Flask**: The web framework underpinning the dashboard and API
- **Requests**: Used for HTTP client operations, particularly for webhook calls
- **Threading**: Python's built-in threading for managing background processes
