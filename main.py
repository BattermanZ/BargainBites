import os
import logging
from logging.handlers import RotatingFileHandler
import asyncio
import configparser
from Telegram import setup_bot
from TooGoodToGo import TooGoodToGo
import signal

# Get the directory where main.py is located
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Setup logging
logs_dir = os.path.join(BASE_DIR, 'logs')
if not os.path.exists(logs_dir):
    os.makedirs(logs_dir)

# Configure root logger
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        # Console handler for Docker/Dozzle
        logging.StreamHandler(),
        # File handler for local logs
        RotatingFileHandler(
            os.path.join(logs_dir, 'bargain_bites.log'),
            maxBytes=10*1024*1024,
            backupCount=5,
            encoding='utf-8'
        )
    ]
)

# Get logger for this module
logger = logging.getLogger(__name__)

# Create database directory if it doesn't exist
db_dir = os.path.join(BASE_DIR, 'database')
os.makedirs(db_dir, exist_ok=True)

# Read configuration
config = configparser.ConfigParser()
config_path = os.path.join(BASE_DIR, 'config.ini')
logger.info(f"Loading config from: {config_path}")
if not os.path.exists(config_path):
    logger.error(f"Config file not found at: {config_path}")
    raise FileNotFoundError(f"Config file not found at: {config_path}")

config.read(config_path)
token = config['Telegram']['token']

# Get admin_ids, defaulting to an empty list if not present
admin_ids = config['Telegram'].get('admin_ids', '').split(',')
admin_ids = [id.strip() for id in admin_ids if id.strip()]  # Remove empty strings

logger.info(f"Loaded admin IDs: {admin_ids}")

if not admin_ids:
    logger.warning("No admin IDs configured. Admin-only features will be unavailable.")

# Setup TooGoodToGo handler
tgtg_handler = None

async def shutdown(signal, loop):
    """Cleanup tasks tied to the service's shutdown."""
    logger.info(f"Received exit signal {signal.name}...")
    
    try:
        # First stop the bot and TGTG handler
        if tgtg_handler:
            logger.info("Stopping bot and TGTG handler...")
            await tgtg_handler.shutdown()
        
        # Then cancel remaining tasks
        tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
        if tasks:
            logger.info(f"Cancelling {len(tasks)} outstanding tasks")
            for task in tasks:
                task.cancel()
            # Wait for tasks to complete with timeout
            await asyncio.wait(tasks, timeout=5)
    except Exception as e:
        logger.error(f"Error during shutdown: {e}")

def handle_exception(loop, context):
    msg = context.get("exception", context["message"])
    logger.error(f"Caught exception: {msg}")
    logger.info("Shutting down due to exception...")
    if not loop.is_closed():
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
    
    tgtg_handler = TooGoodToGo(token, logger, admin_ids)
    bot = setup_bot(token, tgtg_handler, logger, admin_ids)
    
    logger.info("Starting BargainBites bot...")
    print("BargainBites bot is starting...")
    print(f"Number of configured admin IDs: {len(admin_ids)}")
    print("Database will be stored in the 'database' folder")
    print("Bot is now running. Press Ctrl+C to stop.")
    
    try:
        await bot.polling(non_stop=True, timeout=60)
    except asyncio.CancelledError:
        logger.info("Bot polling was cancelled")
    except Exception as e:
        logger.error(f"Error during bot polling: {e}")
    finally:
        logger.info("Bot stopped")
        print("Bot stopped. Goodbye!")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nShutdown initiated by keyboard interrupt...")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
    finally:
        print("Goodbye!")

