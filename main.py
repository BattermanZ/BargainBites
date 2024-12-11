import os
import logging
from logging.handlers import RotatingFileHandler
import asyncio
import configparser
from Telegram import setup_bot
from TooGoodToGo import TooGoodToGo

# Setup logging
if not os.path.exists('logs'):
    os.makedirs('logs')

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
handler = RotatingFileHandler('logs/bargain_bites.log', maxBytes=10*1024*1024, backupCount=5)
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
handler.setFormatter(formatter)
logger.addHandler(handler)

# Create database directory if it doesn't exist
os.makedirs('database', exist_ok=True)


# Read configuration
config = configparser.ConfigParser()
config.read('config.ini')
token = config['Telegram']['token']
group_chat_id = config['Telegram']['group_chat_id']

# Setup TooGoodToGo handler
tgtg_handler = TooGoodToGo(token, logger)

# Setup and run the bot
async def main():
    bot = setup_bot(token, group_chat_id, tgtg_handler, logger)
    
    logger.info("Starting BargainBites bot...")
    print("BargainBites bot is starting...")
    print(f"Bot is configured for group chat ID: {group_chat_id}")
    print("Database will be stored in the 'database' folder")
    print("Bot is now running. Press Ctrl+C to stop.")
    
    await bot.polling(non_stop=True, timeout=60)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
        print("Bot stopped. Goodbye!")
    except Exception as e:
        logger.error(f"Unexpected error: {e}", exc_info=True)
        print(f"An error occurred: {e}")