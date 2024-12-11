import os
import logging
from logging.handlers import RotatingFileHandler
import asyncio
import configparser
from Telegram import setup_bot
from TooGoodToGo import TooGoodToGo
import signal

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
tgtg_handler = None

async def shutdown(signal, loop):
    """Cleanup tasks tied to the service's shutdown."""
    logger.info(f"Received exit signal {signal.name}...")
    
    tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]

    for task in tasks:
        task.cancel()

    logger.info(f"Cancelling {len(tasks)} outstanding tasks")
    await asyncio.gather(*tasks, return_exceptions=True)
    loop.stop()

def handle_exception(loop, context):
    msg = context.get("exception", context["message"])
    logger.error(f"Caught exception: {msg}")
    logger.info("Shutting down...")
    asyncio.create_task(shutdown(signal.SIGTERM, loop))

async def main():
    global tgtg_handler
    loop = asyncio.get_running_loop()
    
    # Setup signal handlers
    signals = (signal.SIGHUP, signal.SIGTERM, signal.SIGINT)
    for s in signals:
        loop.add_signal_handler(
            s, lambda s=s: asyncio.create_task(shutdown(s, loop))
        )
    
    # Setup exception handler
    loop.set_exception_handler(handle_exception)
    
    tgtg_handler = TooGoodToGo(token, logger)
    bot = setup_bot(token, group_chat_id, tgtg_handler, logger)
    
    logger.info("Starting BargainBites bot...")
    print("BargainBites bot is starting...")
    print(f"Bot is configured for group chat ID: {group_chat_id}")
    print("Database will be stored in the 'database' folder")
    print("Bot is now running. Press Ctrl+C to stop.")
    
    polling_task = None
    try:
        polling_task = asyncio.create_task(bot.polling(non_stop=True, timeout=60))
        await polling_task
    except asyncio.CancelledError:
        logger.info("Bot polling was cancelled")
    except Exception as e:
        logger.error(f"Error during bot polling: {e}")
    finally:
        logger.info("Stopping bot...")
        if polling_task and not polling_task.done():
            polling_task.cancel()
            try:
                await polling_task
            except asyncio.CancelledError:
                pass
        await bot.shutdown()  # Use the shutdown method
        if tgtg_handler:
            await tgtg_handler.shutdown()
        logger.info("Bot stopped")
        print("Bot stopped. Goodbye!")

if __name__ == "__main__":
    asyncio.run(main())

