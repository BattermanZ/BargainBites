import json
import time
from datetime import datetime, timezone
from threading import Thread

from telebot import TeleBot, types
from tgtg import TgtgClient

class TooGoodToGo:
    def __init__(self, bot_token, logger):
        self.bot = TeleBot(bot_token)
        self.logger = logger
        self.users_login_data = {}
        self.users_settings_data = {}
        self.available_items_favorites = {}
        self.connected_clients = {}
        self.client = TgtgClient
        self.read_users_login_data_from_txt()
        self.read_users_settings_data_from_txt()
        self.read_available_items_favorites_from_txt()
        Thread(target=self.get_available_items_per_user).start()
        self.bot.set_my_commands([
            types.BotCommand("/info", "favorite bags that are currently available"),
            types.BotCommand("/login", "log in with your mail"),
            types.BotCommand("/settings", "set when you want to be notified"),
            types.BotCommand("/help", "short explanation"),
        ])

    def send_message(self, telegram_user_id, message):
        self.bot.send_message(telegram_user_id, text=message)

    def send_message_with_link(self, telegram_user_id, message, item_id):
        self.bot.send_message(telegram_user_id, text=message, reply_markup=types.InlineKeyboardMarkup(
            keyboard=[
                [
                    types.InlineKeyboardButton(
                        text="Open in app 📱",
                        callback_data="open_app",
                        url="https://share.toogoodtogo.com/item/" + item_id
                    )
                ],
            ]
        ))

    def read_users_login_data_from_txt(self):
        try:
            with open('users_login_data.txt', 'r') as file:
                data = file.read()
                self.users_login_data = json.loads(data)
        except FileNotFoundError:
            self.logger.warning("users_login_data.txt not found. Creating a new one.")
            self.users_login_data = {}
            self.save_users_login_data_to_txt()

    def save_users_login_data_to_txt(self):
        with open('users_login_data.txt', 'w') as file:
            json.dump(self.users_login_data, file)

    def read_users_settings_data_from_txt(self):
        try:
            with open('users_settings_data.txt', 'r') as file:
                data = file.read()
                self.users_settings_data = json.loads(data)
        except FileNotFoundError:
            self.logger.warning("users_settings_data.txt not found. Creating a new one.")
            self.users_settings_data = {}
            self.save_users_settings_data_to_txt()

    def save_users_settings_data_to_txt(self):
        with open('users_settings_data.txt', 'w') as file:
            json.dump(self.users_settings_data, file)

    def read_available_items_favorites_from_txt(self):
        try:
            with open('available_items_favorites.txt', 'r') as file:
                data = file.read()
                self.available_items_favorites = json.loads(data)
        except FileNotFoundError:
            self.logger.warning("available_items_favorites.txt not found. Creating a new one.")
            self.available_items_favorites = {}
            self.save_available_items_favorites_to_txt()

    def save_available_items_favorites_to_txt(self):
        with open('available_items_favorites.txt', 'w') as file:
            json.dump(self.available_items_favorites, file)

    def add_user(self, telegram_user_id, credentials):
        self.users_login_data[telegram_user_id] = credentials
        self.save_users_login_data_to_txt()
        self.users_settings_data[telegram_user_id] = {'sold_out': 0,
                                                'new_stock': 1,
                                                      'stock_reduced': 0,
                                                      'stock_increased': 0}
        self.save_users_settings_data_to_txt()

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

    def send_available_favourite_items_for_one_user(self, user_id):
        try:
            self.connect(user_id)
            favourite_items = self.get_favourite_items()
            available_items = []
            for item in favourite_items:
                if item['items_available'] > 0:
                    item_id = item['item']['item_id']
                    store_name = "🍽 " + str(item['store']['store_name'])
                    store_address_line = "🧭 " + str(item['store']['store_location']['address']['address_line'])
                    store_price = "💰 " + str(int(item['item']["price_including_taxes"]["minor_units"]) / 100)
                    store_items_available = "🥡 " + str(item['items_available'])
                    text = "{0}\n{1}\n{2}\n{3}\n⏰ {4} - {5}".format(
                        store_name, store_address_line, store_price, store_items_available,
                        datetime.strptime(item['pickup_interval']['start'], "%Y-%m-%dT%H:%M:%SZ").astimezone(timezone.utc).strftime("%a %d.%m at %H:%M"),
                        datetime.strptime(item['pickup_interval']['end'], '%Y-%m-%dT%H:%M:%SZ').astimezone(timezone.utc).strftime("%a %d.%m at %H:%M")
                    )
                    self.send_message_with_link(user_id, text, item_id)
                    available_items.append(item)
            if len(available_items) == 0:
                self.send_message(user_id, "Currently all your favorites are sold out 😕")
            self.logger.info(f"Sent available items for user ID: {user_id}")
        except Exception as e:
            self.logger.error(f"Error sending available items: {e}")
            self.send_message(user_id, "❌ An error occurred while fetching available items. Please try again later.")

    def get_available_items_per_user(self):
        while True:
            try:
                temp_available_items = {}
                for key in self.users_login_data.keys():
                    self.connect(key)
                    time.sleep(1)
                    available_items = self.get_favourite_items()
                    for item in available_items:
                        status = "null"
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
                            if status != "null":
                                temp_available_items[item_id] = status
                        self.available_items_favorites[item_id] = item
                        if item_id in temp_available_items and \
                                self.users_settings_data[key][temp_available_items[item_id]] == 1:
                            saved_status = temp_available_items[item_id]
                            store_name = "🍽 " + str(item['store']['store_name'])
                            store_address_line = "🧭 " + str(item['store']['store_location']['address']['address_line'])
                            store_price = "💰 " + str(int(item['item']["price_including_taxes"]["minor_units"]) / 100)
                            store_items_available = "🥡 " + str(item['items_available'])
                            if saved_status == "sold_out":
                                text = f"{store_name}\n{store_address_line}\n{store_price}\n{store_items_available}"
                            else:
                                text = "{0}\n{1}\n{2}\n{3}\n⏰ {4} - {5}".format(
                                    store_name, store_address_line, store_price, store_items_available,
                                    datetime.strptime(item['pickup_interval']['start'], "%Y-%m-%dT%H:%M:%SZ").astimezone(timezone.utc).strftime("%a %d.%m at %H:%M"),
                                    datetime.strptime(item['pickup_interval']['end'], '%Y-%m-%dT%H:%M:%SZ').astimezone(timezone.utc).strftime("%a %d.%m at %H:%M")
                                )
                            text += f"\n{saved_status}"
                            self.logger.info(f"{saved_status} Telegram USER_ID: {key}\n{text}")
                            self.send_message_with_link(key, text, item_id)
                self.save_available_items_favorites_to_txt()
                time.sleep(60)
            except Exception as err:
                self.logger.error(f"Unexpected error in get_available_items_per_user: {err}", exc_info=True)