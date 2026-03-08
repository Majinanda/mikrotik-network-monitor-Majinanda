import os
import requests
import logging

logger = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
WHATSAPP_WEBHOOK_URL = os.getenv("WHATSAPP_WEBHOOK_URL")

def send_notification(message: str):
    logger.info(f"Notification triggered: {message}")
    
    if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message}
        try:
            requests.post(url, json=payload, timeout=5)
            logger.info("Sent Telegram notification")
        except Exception as e:
            logger.error(f"Failed to send Telegram notification: {e}")
            
    if WHATSAPP_WEBHOOK_URL:
        # Assuming a generic JSON payload for WhatsApp webhooks (like self-hosted ones)
        payload = {"message": message}
        try:
            requests.post(WHATSAPP_WEBHOOK_URL, json=payload, timeout=5)
            logger.info("Sent WhatsApp notification")
        except Exception as e:
            logger.error(f"Failed to send WhatsApp notification: {e}")
