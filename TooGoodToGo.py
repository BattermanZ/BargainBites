import json
import time
from datetime import datetime, timezone, date, timedelta
from threading import Thread, Event
from telebot.async_telebot import AsyncTeleBot
from telebot import types
from tgtg import TgtgClient
from database import Database
import asyncio
from queue import Queue
import queue

class TooGoodToGo:
    def __init__(self, bot_token, logger, group_chat_id, admin_ids):
        self.bot = AsyncTeleBot(bot_token)
        self.logger = logger
        self.group_chat_id = group_chat_id
        self.admin_ids = [str(id) for id in admin_ids]  # Ensure all admin IDs are strings
        self.db = Database('database/bargain_bites.db')
        self.users_login_data = self.db.get_users_login_data()
        self.users_settings_data = self.db.get_users_settings_data()
        self.available_items_favorites = self.db.get_available_items_favorites()
        self.connected_clients = {}
        self.client = TgtgClient
        self.shutdown_flag = Event()
        self.message_queue = Queue()
        asyncio.create_task(self.process_message_queue())
        asyncio.create_task(self.set_bot_commands())
        self.thread = Thread(target=self.get_available_items_per_user)
        self.thread.start()
        self.logger.info(f"TooGoodToGo initialized with admin IDs: {self.admin_ids}")

    async def set_bot_commands(self):
        await self.bot.set_my_commands([
            types.BotCommand("/info", "favorite bags that are currently available"),
            types.BotCommand("/login", "log in with your mail"),
            types.BotCommand("/settings", "set when you want to be notified"),
            types.BotCommand("/blacklist", "manage your ignored stores"),
            types.BotCommand("/help", "short explanation"),
        ])

    async def send_message(self, telegram_user_id, message):
        await self.bot.send_message(telegram_user_id, text=message, parse_mode="Markdown")

    async def send_message_with_link(self, telegram_user_id, message, item_id, store_id, store_name):
        keyboard = types.InlineKeyboardMarkup()
        url_button = types.InlineKeyboardButton(text="Open in App", url=f"https://share.toogoodtogo.com/item/{item_id}")
        ignore_button = types.InlineKeyboardButton(text="Ignore Store", callback_data=f"ignore_{store_id}_{store_name}")
        keyboard.add(url_button, ignore_button)
        await self.bot.send_message(telegram_user_id, text=message, reply_markup=keyboard, parse_mode="Markdown")

    def add_user(self, telegram_user_id, credentials):
        self.users_login_data[telegram_user_id] = credentials
        self.db.save_users_login_data(self.users_login_data)
        self.users_settings_data[telegram_user_id] = {'sold_out': 0, 'new_stock': 1, 'stock_reduced': 0, 'stock_increased': 0}
        self.db.save_users_settings_data(self.users_settings_data)

    async def new_user(self, telegram_user_id, email):
        try:
            client = TgtgClient(email=email)
            credentials = client.get_credentials()
            self.add_user(telegram_user_id, credentials)
            await self.send_message(telegram_user_id, "✅ You are now logged in!")
            self.logger.info(f"New user added with ID: {telegram_user_id}")
        except Exception as e:
            self.logger.error(f"Error adding new user: {e}")
            await self.send_message(telegram_user_id, "❌ An error occurred during login. Please try again later.")

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
        store_id = item['store']['store_id']

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
            'sold_out': '*SOLD-OUT* 🥺\n\n',
            'stock_increased': '*STOCK INCREASED* 📈\n\n',
            'stock_reduced': '*STOCK REDUCED* 📉\n\n'
        }

        message = status_headers.get(status, '')
        message += f"🏪 *{store_name}*\n"
        message += f"📍 {address}\n"
        message += f"💰 €{price:.2f}\n"
        message += f"🥡 {items_available} bags available\n"
        if pickup_time:
            message += f"{pickup_time}\n"
        
        return message, item_id, store_id, store_name

    async def send_available_favourite_items_for_one_user(self, user_id):
        try:
            self.connect(user_id)
            favourite_items = self.get_favourite_items()
            available_items = [item for item in favourite_items if item['items_available'] > 0 and not self.db.is_store_blacklisted(user_id, item['store']['store_id'])]
            
            if not available_items:
                await self.send_message(user_id, "Currently all your favorites are sold out or ignored 😕")
                return

            for item in available_items:
                message, item_id, store_id, store_name = self.format_message(item)
                await self.send_message_with_link(user_id, message, item_id, store_id, store_name)
            
            self.logger.info(f"Sent available items for user ID: {user_id}")
        except Exception as e:
            self.logger.error(f"Error sending available items: {e}")
            await self.send_message(user_id, "❌ An error occurred while fetching available items. Please try again later.")

    def get_available_items_per_user(self):
        while not self.shutdown_flag.is_set():
            try:
                users_login_data = self.db.get_users_login_data()
                available_items_favorites = self.db.get_available_items_favorites()
                temp_available_items = {}
                for key in list(users_login_data.keys()):
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
                        store_id = item['store']['store_id']
                        if self.db.is_store_blacklisted(key, store_id):
                            continue
                        if item_id in available_items_favorites and item_id not in temp_available_items:
                            old_items_available = int(available_items_favorites[item_id]['items_available'])
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
                        available_items_favorites[item_id] = item
                        if item_id in temp_available_items:
                            user_settings = self.db.get_user_settings(key)
                            if user_settings and user_settings[temp_available_items[item_id]] == 1:
                                message, item_id, store_id, store_name = self.format_message(item, temp_available_items[item_id])
                                self.logger.info(f"{temp_available_items[item_id]} Telegram USER_ID: {key}\n{message}")
                                self.message_queue.put((key, message, item_id, store_id, store_name))
                self.db.save_available_items_favorites(available_items_favorites)
            except Exception as err:
                self.logger.error(f"Unexpected error in get_available_items_per_user: {err}", exc_info=True)
            
            if not self.shutdown_flag.is_set():
                self.shutdown_flag.wait(timeout=300)  # 5 minutes = 300 seconds
        
        self.logger.info("Background thread has finished.")

    async def process_message_queue(self):
        while not self.shutdown_flag.is_set():
            try:
                key, message, item_id, store_id, store_name = await asyncio.get_event_loop().run_in_executor(
                    None, self.message_queue.get, True, 1.0
                )
                try:
                    await self.send_message_with_link(key, message, item_id, store_id, store_name)
                    self.logger.info(f"Message sent to user {key}")
                except Exception as e:
                    self.logger.error(f"Error sending message: {e}")
                finally:
                    self.message_queue.task_done()
            except queue.Empty:
                pass
            except Exception as e:
                self.logger.error(f"Unexpected error in process_message_queue: {e}", exc_info=True)
                await asyncio.sleep(1)

    async def graceful_shutdown(self):
        self.logger.info("Initiating graceful shutdown...")
        self.shutdown_flag.set()
        self.thread.join(timeout=10)
        if self.thread.is_alive():
            self.logger.warning("Background thread did not terminate within the timeout period.")
        if not self.message_queue.empty():
            self.logger.info("Waiting for message queue to be processed...")
            self.message_queue.join()
        await self.bot.close()
        self.db.close()
        self.logger.info("Graceful shutdown complete.")

    async def shutdown(self):
        await self.graceful_shutdown()

    def is_admin(self, user_id):
        user_id_str = str(user_id)
        is_admin = user_id_str in self.admin_ids or self.db.is_admin(user_id_str)
        self.logger.info(f"Admin check for user {user_id_str}: {is_admin}")
        self.logger.info(f"Current admin IDs: {self.admin_ids}")
        return is_admin

    def is_user_authorized(self, user_id):
        user_id_str = str(user_id)
        is_admin = self.is_admin(user_id_str)
        is_authorized = self.db.is_user_authorized(user_id_str)
        self.logger.info(f"Authorization check for user {user_id_str}: Admin: {is_admin}, Authorized: {is_authorized}")
        return is_admin or is_authorized

    async def check_authorization(self, user_id, chat_id):
        user_id = str(user_id)
        chat_id = str(chat_id)
        self.logger.info(f"Checking authorization for user {user_id} in chat {chat_id}")
        if self.is_group_chat(chat_id):
            self.logger.info(f"Authorized: Group chat {chat_id}")
            return True
        if self.is_admin(user_id):
            self.logger.info(f"Authorized: Admin user {user_id}")
            return True
        if self.is_user_authorized(user_id):
            self.logger.info(f"Authorized: Authorized user {user_id}")
            return True
        self.logger.info(f"Not authorized: User {user_id} in chat {chat_id}")
        return False

    async def add_to_blacklist(self, user_id, store_id, store_name):
        if not await self.check_authorization(user_id, user_id):
            self.logger.warning(f"Unauthorized blacklist attempt by user {user_id}")
            return False
        self.db.add_blacklisted_store(user_id, store_id, store_name)
        message = (f"Store '{store_name}' has been added to your blacklist.\n\n"
                   f"To view and manage your blacklist, use the /blacklist command. "
                   f"You can easily remove stores from your blacklist using the provided buttons.")
        await self.send_message(user_id, message)
        return True

    async def remove_from_blacklist(self, user_id, store_id, store_name):
        if not await self.check_authorization(user_id, user_id):
            self.logger.warning(f"Unauthorized blacklist removal attempt by user {user_id}")
            return False
        self.db.remove_blacklisted_store(user_id, store_id)
        await self.send_message(user_id, f"Store '{store_name}' has been removed from your blacklist.")
        return True

    async def get_blacklist(self, user_id):
        if not await self.check_authorization(user_id, user_id):
            self.logger.warning(f"Unauthorized blacklist access attempt by user {user_id}")
            return False
        blacklisted_stores = self.db.get_blacklisted_stores(user_id)
        if not blacklisted_stores:
            await self.send_message(user_id, "You haven't blacklisted any stores yet.")
        else:
            message = "Your blacklisted stores:\n\nClick on a button to remove a store from your blacklist:"
            keyboard = types.InlineKeyboardMarkup(row_width=2)
            buttons = []
            for store_id, store_name in blacklisted_stores:
                button = types.InlineKeyboardButton(text=store_name, callback_data=f"remove_blacklist_{store_id}")
                buttons.append(button)
            keyboard.add(*buttons)
            await self.bot.send_message(user_id, message, reply_markup=keyboard)
        return True

    async def handle_remove_blacklist_callback(self, call):
        user_id = call.message.chat.id
        store_id = call.data.split('_')[2]
        blacklisted_stores = self.db.get_blacklisted_stores(str(user_id))
        store_name = next((name for id, name in blacklisted_stores if id == store_id), None)
    
        if store_name:
            if not await self.check_authorization(user_id, user_id):
                self.logger.warning(f"Unauthorized blacklist removal attempt by user {user_id}")
                return False
            await self.remove_from_blacklist(str(user_id), store_id, store_name)
            await self.bot.answer_callback_query(call.id, text=f"'{store_name}' removed from blacklist.")
            updated_blacklist = self.db.get_blacklisted_stores(str(user_id))
            if not updated_blacklist:
                await self.bot.edit_message_text("Your blacklist is now empty.", user_id, call.message.message_id)
            else:
                new_keyboard = types.InlineKeyboardMarkup(row_width=2)
                buttons = []
                for s_id, s_name in updated_blacklist:
                    button = types.InlineKeyboardButton(text=s_name, callback_data=f"remove_blacklist_{s_id}")
                    buttons.append(button)
                new_keyboard.add(*buttons)
                await self.bot.edit_message_reply_markup(user_id, call.message.message_id, reply_markup=new_keyboard)
        else:
            await self.bot.answer_callback_query(call.id, text="Store not found in blacklist.")
        return True

    def generate_token(self):
        return self.db.generate_token()

    def validate_token(self, token):
        return self.db.validate_token(token)

    def authorize_user(self, token, user_id, first_name):
        result = self.db.authorize_user(token, user_id, first_name)
        self.logger.info(f"Authorizing user {user_id} with token: {'Success' if result else 'Failure'}")
        return result

    def get_all_tokens(self):
        return self.db.get_all_tokens()

    def is_group_chat(self, chat_id):
        return str(chat_id) == self.group_chat_id

