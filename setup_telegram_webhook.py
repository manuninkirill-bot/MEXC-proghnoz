#!/usr/bin/env python3
"""
Script to setup Telegram webhook for the trading bot
"""
import os
import requests
import sys
import logging

logging.basicConfig(level=logging.INFO)

def setup_webhook():
    """Setup webhook for Telegram bot"""
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if not bot_token:
        print("❌ TELEGRAM_BOT_TOKEN environment variable not found!")
        return False
    
    # Get the replit domain
    replit_domain = os.environ.get("REPLIT_DOMAINS")
    if not replit_domain:
        print("❌ REPLIT_DOMAINS environment variable not found!")
        print("This script should be run on Replit with a published app.")
        return False
    
    # Parse domain (it can be multiple domains separated by comma)
    if ',' in replit_domain:
        domain = replit_domain.split(',')[0].strip()
    else:
        domain = replit_domain.strip()
    
    # Construct webhook URL
    webhook_url = f"https://{domain}/webhook/telegram"
    
    print(f"🔗 Setting up webhook URL: {webhook_url}")
    
    # Setup webhook
    telegram_api_url = f"https://api.telegram.org/bot{bot_token}/setWebhook"
    
    data = {
        "url": webhook_url,
        "drop_pending_updates": True  # Clear any pending updates
    }
    
    try:
        response = requests.post(telegram_api_url, data=data, timeout=30)
        response.raise_for_status()
        result = response.json()
        
        if result.get("ok"):
            print("✅ Webhook successfully set up!")
            print(f"   URL: {webhook_url}")
            return True
        else:
            print(f"❌ Failed to setup webhook: {result.get('description', 'Unknown error')}")
            return False
            
    except Exception as e:
        print(f"❌ Error setting up webhook: {e}")
        return False

def check_webhook_info():
    """Check current webhook info"""
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if not bot_token:
        return
    
    try:
        telegram_api_url = f"https://api.telegram.org/bot{bot_token}/getWebhookInfo"
        response = requests.get(telegram_api_url, timeout=30)
        response.raise_for_status()
        result = response.json()
        
        if result.get("ok"):
            webhook_info = result.get("result", {})
            print("\n📋 Current webhook info:")
            print(f"   URL: {webhook_info.get('url', 'Not set')}")
            print(f"   Has custom certificate: {webhook_info.get('has_custom_certificate', False)}")
            print(f"   Pending update count: {webhook_info.get('pending_update_count', 0)}")
            if webhook_info.get('last_error_date'):
                print(f"   Last error: {webhook_info.get('last_error_message', 'N/A')}")
        else:
            print(f"❌ Failed to get webhook info: {result.get('description', 'Unknown error')}")
            
    except Exception as e:
        print(f"❌ Error getting webhook info: {e}")

def main():
    print("🤖 Telegram Webhook Setup for Trading Bot")
    print("=" * 50)
    
    # First check current webhook info
    check_webhook_info()
    
    # Ask user if they want to proceed
    if len(sys.argv) > 1 and sys.argv[1] == "--auto":
        proceed = True
    else:
        proceed = input("\n🔧 Do you want to setup the webhook? (y/n): ").lower().startswith('y')
    
    if proceed:
        success = setup_webhook()
        if success:
            print("\n🎉 Webhook setup complete!")
            print("\nNext steps:")
            print("1. Find your bot in Telegram")
            print("2. Send /start command to your bot")
            print("3. Bot will now only respond to the owner (TELEGRAM_OWNER_ID)")
        else:
            print("\n💥 Webhook setup failed. Check the errors above.")
    else:
        print("Webhook setup cancelled.")

if __name__ == "__main__":
    main()