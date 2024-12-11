import json
import time
from datetime import datetime, timezone, date, timedelta
from threading import Thread, Event
from telebot import TeleBot, types
from tgtg import TgtgClient
from database import Database
import asyncio

class TooGoodToGo:
    def __init__(self, bot_token, logger):
        self.bot = TeleBot(bot_token)
        self.logger = logger
        self.db = Database('database/bargain_bites.db')
        self.users_login_data = self.db.get_users_login_data()
        self.users_settings_data = self.db.get_users_settings_data()
        self.available_items_favorites = self.db.get_available_items_favorites()
        self.connected_clients = {}
        self.client = TgtgClient
        self.shutdown_flag = Event()
        self.thread = Thread(target=self.get_available_items_per_user)
        self.thread.start()
        self.bot.set_my_commands([
            types.BotCommand("/info", "favorite bags that are currently available"),
            types.BotCommand("/login", "log in with your mail"),
            types.BotCommand("/settings", "set when you want to be notified"),
            types.BotCommand("/help", "short explanation"),
        ])

    def send_message(self, telegram_user_id, message):
        self.bot.send_message(telegram_user_id, text=message, parse_mode="Markdown")

    def send_message_with_link(self, telegram_user_id, message, item_id):
        keyboard = types.InlineKeyboardMarkup()
        url_button = types.InlineKeyboardButton(text="Open in App", url=f"https://share.toogoodtogo.com/item/{item_id}")
        keyboard.add(url_button)
        self.bot.send_message(telegram_user_id, text=message, reply_markup=keyboard, parse_mode="Markdown")

    def add_user(self, telegram_user_id, credentials):
        self.users_login_data[telegram_user_id] = credentials
        self.db.save_users_login_data(self.users_login_data)
        self.users_settings_data[telegram_user_id] = {'sold_out': 0,
                                                      'new_stock': 1,
                                                      'stock_reduced': 0,
                                                      'stock_increased': 0}
        self.db.save_users_settings_data(self.users_settings_data)

    def new_user(self, telegram_user_id, email):
        try:
            client = TgtgClient(email=email)
            credentials = client.get_credentials()
            self.add_user(telegram_user_id, credentials)
            self.send_message(telegram_user_id, "✅ You are now logged in!")
            self.logger.info(f"New user added with ID: {telegram_user_id}")
        except Exception as e:
            self.logger.error(f"Error adding new user: {e}")
            self.send_message(telegram_user_id, "❌ An error occurred during login. Please try again later.")

    def find_credentials_by_telegramUserID(self, user_id):
        return self.users_login_data.get(user_id)

    def connect(self, user_id):
        if user_id in self.connected_clients:
            self.client = self.connected_clients[user_id]
        else:
            user_credentials = self.find_credentials_by_telegramUserID(user_id)
            if user_credentials:
                self.client = TgtgClient(access_token=user_credentials["access_token"],
                                         refresh_token=user_credentials["refresh_token"],
                                         cookie=user_credentials["cookie"])
                self.connected_clients[user_id] = self.client
                time.sleep(3)
            else:
                raise Exception(f"No credentials found for user ID: {user_id}")

    def get_favourite_items(self):
        return self.client.get_items()

    def format_message(self, item, status=None):
        store_name = item['store']['store_name']
        address = item['store']['store_location']['address']['address_line']
        price = item['item']["price_including_taxes"]["minor_units"] / 100
        items_available = item['items_available']
        item_id = item['item']['item_id']

        pickup_time = ""
        if 'pickup_interval' in item:
            start_time = datetime.strptime(item['pickup_interval']['start'], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).astimezone()
            end_time = datetime.strptime(item['pickup_interval']['end'], '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc).astimezone()
        
            today = date.today()
            tomorrow = today + timedelta(days=1)
        
            if start_time.date() == today:
                day_str = "Today"
            elif start_time.date() == tomorrow:
                day_str = "Tomorrow"
            else:
                day_str = start_time.strftime("%A")
        
            pickup_time = f"⏰ {day_str} {start_time.strftime('%H:%M')}-{end_time.strftime('%H:%M')} ({start_time.strftime('%A')})"

        status_headers = {
            'new_stock': '*NEW BAGS AVAILABLE* 🛍️\n\n',
            'sold_out': '*SOLD-OUT* 🥺\n\n'
        }

        message = status_headers.get(status, '')
        message += f"🏪 *{store_name}*\n"
        message += f"📍 {address}\n"
        message += f"💰 €{price:.2f}\n"
        message += f"🥡 {items_available} bags available\n"
        if pickup_time:
            message += f"{pickup_time}\n"
        
        return message, item_id

    def send_available_favourite_items_for_one_user(self, user_id):
        try:
            self.connect(user_id)
            favourite_items = self.get_favourite_items()
            available_items = [item for item in favourite_items if item['items_available'] > 0]
            
            if not available_items:
                self.send_message(user_id, "Currently all your favorites are sold out 😕")
                return

            for item in available_items:
                message, item_id = self.format_message(item)
                self.send_message_with_link(user_id, message, item_id)
            
            self.logger.info(f"Sent available items for user ID: {user_id}")
        except Exception as e:
            self.logger.error(f"Error sending available items: {e}")
            self.send_message(user_id, "❌ An error occurred while fetching available items. Please try again later.")

    def get_available_items_per_user(self):
        while not self.shutdown_flag.is_set():
            try:
                temp_available_items = {}
                for key in list(self.users_login_data.keys()):
                    if self.shutdown_flag.is_set():
                        break
                    self.connect(key)
                    time.sleep(1)
                    available_items = self.get_favourite_items()
                    for item in available_items:
                        if self.shutdown_flag.is_set():
                            break
                        status = None
                        item_id = item['item']['item_id']
                        if item_id in self.available_items_favorites and item_id not in temp_available_items:
                            old_items_available = int(self.available_items_favorites[item_id]['items_available'])
                            new_items_available = int(item['items_available'])
                            if new_items_available == 0 and old_items_available > 0:
                                status = "sold_out"
                            elif old_items_available == 0 and new_items_available > 0:
                                status = "new_stock"
                            elif old_items_available > new_items_available:
                                status = "stock_reduced"
                            elif old_items_available < new_items_available:
                                status = "stock_increased"
                            if status:
                                temp_available_items[item_id] = status
                        self.available_items_favorites[item_id] = item
                        if item_id in temp_available_items and \
                                self.users_settings_data[key][temp_available_items[item_id]] == 1:
                            message, item_id = self.format_message(item, temp_available_items[item_id])
                            self.logger.info(f"{temp_available_items[item_id]} Telegram USER_ID: {key}\n{message}")
                            self.send_message_with_link(key, message, item_id)
                if not self.shutdown_flag.is_set():
                    self.db.save_available_items_favorites(self.available_items_favorites)
                    self.shutdown_flag.wait(timeout=60)
            except Exception as err:
                self.logger.error(f"Unexpected error in get_available_items_per_user: {err}", exc_info=True)
                if not self.shutdown_flag.is_set():
                    time.sleep(60)
        
        self.logger.info("Background thread has finished.")

    async def shutdown(self):
        self.logger.info("Shutting down TooGoodToGo handler...")
        self.shutdown_flag.set()
        self.thread.join(timeout=10)  # Increased timeout to 10 seconds
        if self.thread.is_alive():
            self.logger.warning("Background thread did not terminate within the timeout period.")
        # Remove the await keyword as TeleBot.stop_bot() is not a coroutine
        self.bot.stop_bot()
        self.db.close()
        for client in self.connected_clients.values():
            client.close()  # Close all TgtgClient instances
        self.logger.info("TooGoodToGo handler shut down complete.")

