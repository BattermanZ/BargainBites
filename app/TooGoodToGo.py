import json
import time
from datetime import datetime, timezone, date, timedelta
from threading import Thread, Event, Lock
from telebot.async_telebot import AsyncTeleBot
from telebot import types
from tgtg import TgtgClient
from database import Database
import asyncio
from queue import Queue
import queue
import random
from tgtg.exceptions import TgtgAPIError, TgtgLoginError
import os

class TooGoodToGo:
    def __init__(self, bot_token, logger, admin_ids):
        self.bot = AsyncTeleBot(bot_token)
        self.logger = logger
        self.admin_ids = [str(id) for id in admin_ids]  # Ensure all admin IDs are strings
        
        # Get the project root directory
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        db_path = os.path.join(project_root, 'database', 'bargain_bites.db')
        
        self.db = Database(db_path)
        self.users_login_data = self.db.get_users_login_data()
        self.users_settings_data = self.db.get_users_settings_data()
        self.available_items_favorites = self.db.get_available_items_favorites()
        self.connected_clients = {}   # user_id -> TgtgClient (per-user cache)
        self.pending_logins = {}  # telegram_user_id (str) -> {"client", "polling_id", "email"}
        self._client_lock = Lock()
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
            types.BotCommand("/pin", "complete login with the PIN from your email"),
            types.BotCommand("/relogin", "force a new login with your mail"),
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

    def message_queue_text(self, telegram_user_id, message):
        """Thread-safe: enqueue a plain-text message for the async sender."""
        self.message_queue.put((str(telegram_user_id), message))

    def add_user(self, telegram_user_id, credentials):
        self.users_login_data[telegram_user_id] = credentials
        self.db.save_users_login_data(self.users_login_data)
        self.users_settings_data[telegram_user_id] = {'sold_out': 0, 'new_stock': 1, 'stock_reduced': 0, 'stock_increased': 0}
        self.db.save_users_settings_data(self.users_settings_data)

    @staticmethod
    def _credentials_from_client(client):
        return {
            "access_token": client.access_token,
            "refresh_token": client.refresh_token,
            "cookie": client.cookie,
        }

    async def new_user(self, telegram_user_id, email, force_relogin=False):
        telegram_user_id = str(telegram_user_id)
        if telegram_user_id in self.users_login_data and not force_relogin:
            await self.send_message(telegram_user_id, "This chat is already logged in! To re-login, use /relogin")
            return
        # Run the blocking HTTP call off the event loop.
        await asyncio.get_event_loop().run_in_executor(
            None, self._initiate_login, telegram_user_id, email
        )

    def _initiate_login(self, telegram_user_id, email):
        """Blocking: POST authByEmail, capture polling_id, stash client. Runs in executor/thread."""
        from tgtg import AUTH_BY_EMAIL_ENDPOINT
        try:
            client = TgtgClient(email=email)
            response = client._post(
                client._get_url(AUTH_BY_EMAIL_ENDPOINT),
                json={"device_type": client.device_type, "email": client.email},
            )
            if response.status_code != 200:
                raise TgtgLoginError(response.status_code, response.content)

            login_resp = response.json()
            state = login_resp.get("state")
            if state == "WAIT":
                self.pending_logins[telegram_user_id] = {
                    "client": client,
                    "polling_id": login_resp["polling_id"],
                    "email": email,
                }
                self.logger.info(f"Login initiated for {telegram_user_id} - waiting for PIN")
                self.message_queue_text(
                    telegram_user_id,
                    "📩 Check your email for a *login PIN code* from Too Good To Go.\n\n"
                    "Then send it here:\n`/pin 12345`",
                )
            elif state == "TERMS":
                self.message_queue_text(
                    telegram_user_id,
                    "❌ This email is not linked to a TGTG account. Please sign up in the TGTG app first.",
                )
            else:
                self.message_queue_text(telegram_user_id, f"❌ Unexpected login state: {state}")
        except TgtgAPIError as e:
            self.logger.error(f"Login rate-limited for {telegram_user_id}: {e}")
            self.message_queue_text(telegram_user_id, "❌ Too many requests. Please try again later.")
        except TgtgLoginError as e:
            self.logger.warning(f"Login blocked/failed for {telegram_user_id}: {e}")
            self.message_queue_text(
                telegram_user_id,
                "🔒 *Login blocked by TGTG (anti-bot).* Try again later, or from a different network.",
            )
        except Exception as e:
            self.logger.error(f"Unexpected error initiating login for {telegram_user_id}: {e}")
            self.message_queue_text(telegram_user_id, "❌ An error occurred during login. Please try again later.")

    def complete_login_with_pin(self, telegram_user_id, pin):
        """Blocking: finish a pending login with the emailed PIN. Runs in executor/thread."""
        telegram_user_id = str(telegram_user_id)
        pending = self.pending_logins.pop(telegram_user_id, None)
        if not pending:
            self.message_queue_text(telegram_user_id, "⚠️ No pending login. Start with `/login email@example.com` first.")
            return
        try:
            client = pending["client"]
            client._auth_by_pin(pending["polling_id"], pin)
            credentials = self._credentials_from_client(client)
            self.add_user(telegram_user_id, credentials)
            # Reuse the just-authenticated client so the first /info doesn't
            # pay the cold-connect tax (rebuild + rate-limit sleep).
            with self._client_lock:
                self.connected_clients[telegram_user_id] = client
            self.logger.info(f"Login completed for {telegram_user_id}")
            self.message_queue_text(telegram_user_id, "✅ You are now logged in!")
        except TgtgLoginError as e:
            self.logger.error(f"PIN auth failed for {telegram_user_id}: {e}")
            self.pending_logins[telegram_user_id] = pending  # allow retry
            self.message_queue_text(telegram_user_id, "❌ Invalid or expired PIN. Check your email and resend `/pin 12345`.")
        except Exception as e:
            self.logger.error(f"Error completing login for {telegram_user_id}: {e}")
            self.message_queue_text(telegram_user_id, "❌ Login failed. Please try `/login` again.")

    async def relogin(self, telegram_user_id, email):
        telegram_user_id = str(telegram_user_id)
        if telegram_user_id in self.users_login_data:
            del self.users_login_data[telegram_user_id]
            self.db.save_users_login_data(self.users_login_data)
        await self.new_user(telegram_user_id, email, force_relogin=True)

    def find_credentials_by_telegramUserID(self, user_id):
        return self.users_login_data.get(user_id)

    def _build_client(self, user_id, cold_connect_delay=True):
        """Build (or reuse) a per-user TGTG client. Thread-safe. Returns a client or raises.

        cold_connect_delay adds a rate-limit cushion before a fresh build; the
        background poll loop keeps it, interactive paths (e.g. /info) skip it.
        """
        with self._client_lock:
            cached = self.connected_clients.get(user_id)
        if cached is not None:
            return cached
        creds = self.find_credentials_by_telegramUserID(user_id)
        if not creds:
            raise Exception(f"No credentials found for user ID: {user_id}")
        if cold_connect_delay:
            time.sleep(random.uniform(10, 20))  # rate-limit cushion on cold connect
        client = TgtgClient(
            access_token=creds["access_token"],
            refresh_token=creds["refresh_token"],
            cookie=creds["cookie"],
        )
        with self._client_lock:
            self.connected_clients[user_id] = client
        return client

    def refresh_credentials(self, user_id):
        """Refresh a user's credentials, persist them, return a fresh client or None."""
        try:
            creds = self.find_credentials_by_telegramUserID(user_id)
            if not creds:
                self.logger.error(f"No credentials found for user {user_id}")
                return None
            client = TgtgClient(
                access_token=creds["access_token"],
                refresh_token=creds["refresh_token"],
                cookie=creds["cookie"],
            )
            new_credentials = client.get_credentials()
            self.users_login_data[user_id] = new_credentials
            self.db.save_users_login_data(self.users_login_data)
            with self._client_lock:
                self.connected_clients[user_id] = client
            self.logger.info(f"Successfully refreshed credentials for user {user_id}")
            return client
        except Exception as e:
            self.logger.error(f"Failed to refresh credentials for user {user_id}: {e}")
            with self._client_lock:
                self.connected_clients.pop(user_id, None)
            return None

    def get_favourite_items(self, user_id, client):
        """Fetch favourites for a specific user/client, with retry, captcha and 401 handling."""
        max_retries = 3
        base_delay = 10
        for attempt in range(max_retries):
            try:
                if attempt > 0:
                    delay = base_delay * (2 ** attempt) + random.uniform(5, 15)
                    self.logger.warning(f"Retrying get_items for {user_id} after {delay:.2f}s...")
                    time.sleep(delay)
                return client.get_items()
            except TgtgAPIError as e:
                error_str = str(e).lower()
                if "401" in error_str or "unauthorized" in error_str:
                    self.logger.warning(f"401 for user {user_id}; attempting credential refresh")
                    refreshed = self.refresh_credentials(user_id)
                    if refreshed is None:
                        raise
                    client = refreshed
                    continue
                if "captcha" in error_str:
                    if attempt == max_retries - 1:
                        self.logger.error(f"Max retries reached for CAPTCHA (user {user_id})")
                        raise
                    continue
                if "404" in error_str:
                    self.logger.warning("Got 404, likely API endpoint issue")
                    raise
                self.logger.error(f"TGTG API error for {user_id}: {e}")
                raise
            except Exception as e:
                self.logger.error(f"Unexpected error in get_favourite_items for {user_id}: {e}")
                raise
        raise Exception(f"get_favourite_items exhausted retries for {user_id}")

    @staticmethod
    def format_message(item, status=None):
        store = item.get('store', {})
        store_name = store.get('store_name', 'Unknown store')
        store_id = store.get('store_id', '')
        address = store.get('store_location', {}).get('address', {}).get('address_line', '')
        inner = item.get('item', {})
        item_id = inner.get('item_id', '')
        minor_units = inner.get('price_including_taxes', {}).get('minor_units', 0)
        price = minor_units / 100
        items_available = item.get('items_available', 0)

        pickup_time = ""
        interval = item.get('pickup_interval')
        if interval and interval.get('start') and interval.get('end'):
            try:
                start_time = datetime.strptime(interval['start'], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).astimezone()
                end_time = datetime.strptime(interval['end'], '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc).astimezone()
                today = date.today()
                tomorrow = today + timedelta(days=1)
                if start_time.date() == today:
                    day_str = "Today"
                elif start_time.date() == tomorrow:
                    day_str = "Tomorrow"
                else:
                    day_str = start_time.strftime("%A")
                pickup_time = f"⏰ {day_str} {start_time.strftime('%H:%M')}-{end_time.strftime('%H:%M')} ({start_time.strftime('%A')})"
            except (ValueError, KeyError):
                pickup_time = ""

        status_headers = {
            'new_stock': '*NEW BAGS AVAILABLE* 🛍️\n\n',
            'sold_out': '*SOLD-OUT* 🥺\n\n',
            'stock_increased': '*STOCK INCREASED* 📈\n\n',
            'stock_reduced': '*STOCK REDUCED* 📉\n\n',
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
            client = self._build_client(user_id, cold_connect_delay=False)
            favourite_items = self.get_favourite_items(user_id, client)
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

    NOTIFICATION_TYPES = ("sold_out", "new_stock", "stock_reduced", "stock_increased")
    DAY_LOOP_MIN_SECONDS = 300    # 5 min
    DAY_LOOP_MAX_SECONDS = 480    # 8 min
    NIGHT_LOOP_MIN_SECONDS = 2700  # 45 min
    NIGHT_LOOP_MAX_SECONDS = 5400  # 90 min
    NIGHT_HOURS = (1, 2, 3, 4, 5, 6)

    @staticmethod
    def _user_needs_notifications(settings):
        if not settings:
            return False
        return any(settings.get(k, 0) for k in TooGoodToGo.NOTIFICATION_TYPES)

    @staticmethod
    def _compute_loop_delay(hour=None):
        """Return a randomized loop delay in seconds, with night-mode stretch
        applied between 01:00 and 06:59 local (`hour` in 1..6)."""
        if hour in TooGoodToGo.NIGHT_HOURS:
            return random.uniform(TooGoodToGo.NIGHT_LOOP_MIN_SECONDS,
                                  TooGoodToGo.NIGHT_LOOP_MAX_SECONDS)
        base = random.uniform(TooGoodToGo.DAY_LOOP_MIN_SECONDS,
                              TooGoodToGo.DAY_LOOP_MAX_SECONDS)
        noise = random.uniform(-10, 10)
        return base + noise

    @staticmethod
    def _prune_seen_items(seen, active_ids):
        return {item_id: data for item_id, data in seen.items() if item_id in active_ids}

    def get_available_items_per_user(self):
        consecutive_errors = 0
        max_consecutive_errors = 5
        
        while not self.shutdown_flag.is_set():
            try:
                # Reset consecutive errors on successful iteration
                consecutive_errors = 0
                
                users_login_data = self.db.get_users_login_data()
                available_items_favorites = self.db.get_available_items_favorites()
                temp_available_items = {}
                active_item_ids = set()

                # Only poll users who actually want at least one notification type.
                user_keys = [
                    uid for uid in users_login_data
                    if self._user_needs_notifications(self.db.get_user_settings(uid))
                ]
                if not user_keys:
                    self.logger.info("No users with active notifications - skipping API poll this cycle.")
                random.shuffle(user_keys)
                
                for key in user_keys:
                    if self.shutdown_flag.is_set():
                        break
                    
                    try:
                        client = self._build_client(key)
                        time.sleep(random.uniform(20, 40))
                        available_items = self.get_favourite_items(key, client)
                        
                        # Process each available item
                        for item in available_items:
                            if self.shutdown_flag.is_set():
                                break
                            
                            status = None
                            item_id = item['item']['item_id']
                            store_id = item['store']['store_id']
                            active_item_ids.add(item_id)

                            # Skip blacklisted stores
                            if self.db.is_store_blacklisted(key, store_id):
                                continue
                            
                            status = None
                            new_items_available = int(item['items_available'])
                            
                            # Check if this is a completely new item
                            if item_id not in available_items_favorites:
                                if new_items_available > 0:
                                    status = "new_stock"
                                    temp_available_items[item_id] = status
                            # Check for changes in existing items
                            elif item_id not in temp_available_items:
                                old_items_available = int(available_items_favorites[item_id]['items_available'])
                                
                                # Determine status based on availability changes
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
                            
                            # Update available items
                            available_items_favorites[item_id] = item
                            
                            # Send notifications for changed items
                            if item_id in temp_available_items:
                                user_settings = self.db.get_user_settings(key)
                                if user_settings and user_settings[temp_available_items[item_id]] == 1:
                                    message, item_id, store_id, store_name = self.format_message(item, temp_available_items[item_id])
                                    self.logger.info(f"{temp_available_items[item_id]} Telegram USER_ID: {key}\n{message}")
                                    self.message_queue.put((key, message, item_id, store_id, store_name))
                    
                    except Exception as e:
                        err_str = str(e).lower()
                        if "captcha" in err_str:
                            self.logger.warning(f"Captcha/Datadome block while polling user {key}; backing off 5 minutes.")
                            self.shutdown_flag.wait(timeout=5 * 60)
                        self.logger.error(f"Error processing user {key}: {e}")
                        consecutive_errors += 1
                        if consecutive_errors >= max_consecutive_errors:
                            self.logger.critical(f"Reached max consecutive errors ({max_consecutive_errors}). Pausing processing.")
                            break
                        continue
                
                # Prune stale entries and save updated available items
                if active_item_ids:
                    available_items_favorites = self._prune_seen_items(available_items_favorites, active_item_ids)
                self.db.save_available_items_favorites(available_items_favorites)
            
            except Exception as err:
                # Log unexpected global errors
                self.logger.error(f"Unexpected error in get_available_items_per_user: {err}", exc_info=True)
                consecutive_errors += 1
                
                # If too many consecutive errors, add a longer pause
                if consecutive_errors >= max_consecutive_errors:
                    self.logger.critical(f"Reached max consecutive errors ({max_consecutive_errors}). Adding extended pause.")
                    time.sleep(3600)  # 1-hour pause
                    consecutive_errors = 0
            
            if not self.shutdown_flag.is_set():
                total_delay = self._compute_loop_delay(hour=datetime.now().hour)
                self.shutdown_flag.wait(timeout=total_delay)
        
        self.logger.info("Background thread has finished.")

    async def process_message_queue(self):
        while not self.shutdown_flag.is_set():
            try:
                payload = await asyncio.get_event_loop().run_in_executor(
                    None, self.message_queue.get, True, 1.0
                )
                try:
                    if len(payload) == 2:
                        key, message = payload
                        await self.send_message(key, message)
                    else:
                        key, message, item_id, store_id, store_name = payload
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
        """Gracefully shut down all components."""
        self.logger.info("Initiating graceful shutdown...")
        
        # Set shutdown flag first
        self.shutdown_flag.set()
        
        try:
            # Wait for background thread with a longer timeout
            self.logger.info("Waiting for background thread to finish...")
            self.thread.join(timeout=5)  # Reduced timeout to 5 seconds
            if self.thread.is_alive():
                self.logger.warning("Background thread did not terminate within the timeout period.")
            
            # Process remaining messages in queue without waiting
            if not self.message_queue.empty():
                self.logger.info("Clearing message queue...")
                while not self.message_queue.empty():
                    try:
                        self.message_queue.get_nowait()
                        self.message_queue.task_done()
                    except queue.Empty:
                        break
            
            # Close bot and database connections
            self.logger.info("Closing connections...")
            try:
                # Close all connected clients
                for client in self.connected_clients.values():
                    if hasattr(client, 'close') and callable(client.close):
                        await client.close()
            except Exception as e:
                self.logger.error(f"Error closing TGTG clients: {e}")
            
            try:
                if hasattr(self.bot, 'session') and self.bot.session:
                    await self.bot.session.close()
                await self.bot.close()
            except Exception as e:
                self.logger.error(f"Error closing bot: {e}")
            
            # Close database connection last
            try:
                self.logger.info("Closing database connection...")
                self.db.close()
            except Exception as e:
                self.logger.error(f"Error closing database: {e}")
            
        except Exception as e:
            self.logger.error(f"Error during graceful shutdown: {e}")
        finally:
            self.logger.info("Graceful shutdown complete.")

    async def shutdown(self):
        """Public method to initiate shutdown."""
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
        self.logger.info(f"Checking authorization for user {user_id}")
        if self.is_admin(user_id):
            self.logger.info(f"Authorized: Admin user {user_id}")
            return True
        if self.is_user_authorized(user_id):
            self.logger.info(f"Authorized: Authorized user {user_id}")
            return True
        self.logger.info(f"Not authorized: User {user_id}")
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

