import os
from telegram_notifications import TelegramNotifier
from datetime import datetime

# Get credentials
bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
chat_id = os.getenv("TELEGRAM_CHAT_ID", "")

print(f"Bot token length: {len(bot_token)}")
print(f"Chat ID: {chat_id}")

# Create notifier
notifier = TelegramNotifier(bot_token, chat_id)

# Create test trade data
test_trade = {
    "side": "long",
    "entry_price": 67890.50,
    "exit_price": 68200.75,
    "size_base": 0.007365,
    "notional": 500.00,
    "pnl": 2.28,
    "time": datetime.utcnow().isoformat(),
    "duration": "9m 34s"
}

# Send notification
print("\nSending test signal...")
notifier.send_position_closed(test_trade, trade_number=42, balance=102.28)
print("Done!")
