import asyncio
from telebot import types
from telebot.async_telebot import AsyncTeleBot

def setup_bot(token, tooGoodToGo, logger, admin_ids):
    bot = AsyncTeleBot(token)

    async def check_authorization(obj):
        if isinstance(obj, types.CallbackQuery):
            user_id = str(obj.from_user.id)
        else:  # Assume it's a message
            user_id = str(obj.from_user.id)
        is_authorized = await tooGoodToGo.check_authorization(user_id, user_id)
        logger.info(f"Authorization check for user {user_id}: {is_authorized}")
        return is_authorized

    def command_arg(message):
        """Return the text after the command, or '' if none was supplied."""
        parts = message.text.split(maxsplit=1)
        return parts[1].strip() if len(parts) > 1 else ""

    # --- Shared submit helpers (used by both one-shot commands and the
    #     conversational follow-up handler) -------------------------------------

    async def submit_email(message, email, *, relogin=False):
        chat_id = str(message.chat.id)
        if not tooGoodToGo._is_valid_email(email):
            tooGoodToGo.set_awaiting(chat_id, "relogin_email" if relogin else "email")
            await bot.send_message(
                chat_id,
                "*⚠️ That doesn't look like a valid email.*\nPlease send your "
                "Too Good To Go email address again.",
                parse_mode="Markdown",
            )
            return
        await bot.send_message(chat_id, text="⏳ Requesting login...")
        if relogin:
            await tooGoodToGo.relogin(chat_id, email)
        else:
            await tooGoodToGo.new_user(chat_id, email)

    async def submit_pin(message, pin):
        chat_id = str(message.chat.id)
        if not pin:
            tooGoodToGo.set_awaiting(chat_id, "pin")
            await bot.send_message(chat_id, "⚠️ Please send the PIN from your email (e.g. `12345`).", parse_mode="Markdown")
            return
        await bot.send_message(chat_id, text="⏳ Verifying PIN...")
        asyncio.get_event_loop().run_in_executor(None, tooGoodToGo.complete_login_with_pin, chat_id, pin)

    async def submit_token(message, token):
        if token and tooGoodToGo.db.validate_token(token):
            if tooGoodToGo.authorize_user(token, str(message.from_user.id), message.from_user.first_name):
                await bot.reply_to(message, f"You have been successfully authorized for private chat access, {message.from_user.first_name}.")
            else:
                await bot.reply_to(message, "Error occurred during authorization. Please try again or contact an admin.")
        else:
            await bot.reply_to(message, "Invalid or missing token. Please send a valid invite token to gain access.")

    @bot.message_handler(commands=['start'])
    async def start(message):
        tooGoodToGo.clear_awaiting(message.chat.id)
        if await check_authorization(message):
            await send_welcome(message)
            return
        token = command_arg(message)
        if token:
            await submit_token(message, token)
        else:
            tooGoodToGo.set_awaiting(message.chat.id, "token")
            await bot.reply_to(message, "👋 Please send me your invite token to get access.")

    @bot.message_handler(commands=['help'])
    async def send_welcome(message):
        if not await check_authorization(message):
            await bot.reply_to(message, "You are not authorized to use this command.")
            return
        logger.info(f"Received /help command in chat {message.chat.id}")
        await bot.send_message(message.chat.id,
                               """
*Hi welcome to the TGTG Bot:*

The bot will notify this group as soon as new bags from the favorites are available.

*❗️️This is necessary if you want to use the bot❗️*
🔑 To login, send */login* and the bot will ask for your email.
_You can also do it in one step:_ */login email@example.com*
_You'll then receive a PIN by email — just send it back here to finish. No password needed._

⚙️ With */settings* you can set when the group wants to be notified. 

ℹ️ With */info* you can display all stores from the favorites where bags are currently available.

🚫 Use */blacklist* to manage your ignored stores.

_🌐 You can find more information about Too Good To Go_ [here](https://www.toogoodtogo.com/).

*🌍 LET'S FIGHT food waste TOGETHER 🌎*
""", parse_mode="Markdown")

    @bot.message_handler(commands=['info'])
    async def send_info(message):
        if not await check_authorization(message):
            return
        logger.info(f"Received /info command in chat {message.chat.id}")
        credentials = tooGoodToGo.find_credentials_by_telegramUserID(str(message.chat.id))
        if credentials is None:
            await bot.send_message(chat_id=message.chat.id,
                                   text="🔑 You have to log in first!\nSend */login* and I'll ask for your email.\n*❗️️This is necessary if you want to use the bot❗️*",
                                   parse_mode="Markdown")
            return None
        await tooGoodToGo.send_available_favourite_items_for_one_user(str(message.chat.id))

    @bot.message_handler(commands=['login'])
    async def send_login(message):
        if not await check_authorization(message):
            return
        tooGoodToGo.clear_awaiting(message.chat.id)
        logger.info(f"Received /login command in chat {message.chat.id}")
        credentials = tooGoodToGo.find_credentials_by_telegramUserID(str(message.chat.id))
        if credentials is not None:
            await bot.send_message(chat_id=message.chat.id, text="👍 This chat is already logged in! To re-login, use /relogin")
            return None
        email = command_arg(message)
        if email:
            await submit_email(message, email)
        else:
            tooGoodToGo.set_awaiting(message.chat.id, "email")
            await bot.send_message(chat_id=message.chat.id,
                                   text="🔑 Please send me your *Too Good To Go email address*.\n_You'll then get a PIN by email to finish. No password needed._",
                                   parse_mode="Markdown")

    @bot.message_handler(commands=['relogin'])
    async def send_relogin(message):
        if not await check_authorization(message):
            return
        tooGoodToGo.clear_awaiting(message.chat.id)
        logger.info(f"Received /relogin command in chat {message.chat.id}")
        email = command_arg(message)
        if email:
            await submit_email(message, email, relogin=True)
        else:
            tooGoodToGo.set_awaiting(message.chat.id, "relogin_email")
            await bot.send_message(chat_id=message.chat.id,
                                   text="🔄 Please send me the *Too Good To Go email address* to re-login with.\n_You'll then get a PIN by email to finish. No password needed._",
                                   parse_mode="Markdown")

    @bot.message_handler(commands=['pin'])
    async def send_pin(message):
        if not await check_authorization(message):
            return
        tooGoodToGo.clear_awaiting(message.chat.id)
        await submit_pin(message, command_arg(message))

    def inline_keyboard_markup(chat_id):
        inline_keyboard = types.InlineKeyboardMarkup(
            keyboard=[
                [
                    types.InlineKeyboardButton(
                        text=("🟢" if tooGoodToGo.users_settings_data[chat_id]["sold_out"] else "🔴") + " sold out",
                        callback_data="sold_out"
                    ),
                    types.InlineKeyboardButton(
                        text=("🟢" if tooGoodToGo.users_settings_data[chat_id]["new_stock"] else "🔴") + " new stock",
                        callback_data="new_stock"
                    )
                ],
                [
                    types.InlineKeyboardButton(
                        text=("🟢" if tooGoodToGo.users_settings_data[chat_id]["stock_reduced"] else "🔴") + " stock reduced",
                        callback_data="stock_reduced"
                    ),
                    types.InlineKeyboardButton(
                        text=("🟢" if tooGoodToGo.users_settings_data[chat_id]["stock_increased"] else "🔴") + " stock increased",
                        callback_data="stock_increased"
                    )
                ],
                [
                    types.InlineKeyboardButton(
                        text="✅ activate all ✅",
                        callback_data="activate_all"
                    )
                ],
                [
                    types.InlineKeyboardButton(
                        text="❌ disable all ❌",
                        callback_data="disable_all"
                    )
                ]
            ])
        return inline_keyboard

    @bot.message_handler(commands=['settings'])
    async def send_settings(message):
        if not await check_authorization(message):
            return
        logger.info(f"Received /settings command in chat {message.chat.id}")
        credentials = tooGoodToGo.find_credentials_by_telegramUserID(str(message.chat.id))
        if credentials is None:
            await bot.send_message(chat_id=message.chat.id,
                                   text="🔑 You have to log in with your mail first!\nPlease enter */login email@example.com*\n*❗️️This is necessary if you want to use the bot❗️*",
                                   parse_mode="Markdown")
            return None

        await bot.send_message(message.chat.id, "🟢 = enabled | 🔴 = disabled\n*Activate alert if:*", parse_mode="markdown",
                               reply_markup=inline_keyboard_markup(str(message.chat.id)))

    @bot.callback_query_handler(func=lambda c: c.data in ['sold_out', 'new_stock', 'stock_reduced', 'stock_increased'])
    async def toggle_setting(call: types.CallbackQuery):
        if not await check_authorization(call):
            await bot.answer_callback_query(call.id, text="You are not authorized to perform this action.")
            return
        logger.info(f"Toggling setting {call.data} in chat {call.message.chat.id}")
        settings = tooGoodToGo.users_settings_data[str(call.message.chat.id)][call.data]
        tooGoodToGo.users_settings_data[str(call.message.chat.id)][call.data] = 0 if settings else 1
        await bot.edit_message_reply_markup(chat_id=call.message.chat.id, message_id=call.message.message_id,
                                            reply_markup=inline_keyboard_markup(str(call.message.chat.id)))
        tooGoodToGo.db.save_users_settings_data(tooGoodToGo.users_settings_data)

    @bot.callback_query_handler(func=lambda c: c.data == 'activate_all')
    async def activate_all(call: types.CallbackQuery):
        if not await check_authorization(call):
            await bot.answer_callback_query(call.id, text="You are not authorized to perform this action.")
            return
        logger.info(f"Activating all settings in chat {call.message.chat.id}")
        for key in tooGoodToGo.users_settings_data[str(call.message.chat.id)].keys():
            tooGoodToGo.users_settings_data[str(call.message.chat.id)][key] = 1
        tooGoodToGo.db.save_users_settings_data(tooGoodToGo.users_settings_data)
        await bot.edit_message_reply_markup(chat_id=call.message.chat.id, message_id=call.message.message_id,
                                            reply_markup=inline_keyboard_markup(str(call.message.chat.id)))

    @bot.callback_query_handler(func=lambda c: c.data == 'disable_all')
    async def disable_all(call: types.CallbackQuery):
        if not await check_authorization(call):
            await bot.answer_callback_query(call.id, text="You are not authorized to perform this action.")
            return
        logger.info(f"Disabling all settings in chat {call.message.chat.id}")
        for key in tooGoodToGo.users_settings_data[str(call.message.chat.id)].keys():
            tooGoodToGo.users_settings_data[str(call.message.chat.id)][key] = 0
        tooGoodToGo.db.save_users_settings_data(tooGoodToGo.users_settings_data)
        await bot.edit_message_reply_markup(chat_id=call.message.chat.id, message_id=call.message.message_id,
                                            reply_markup=inline_keyboard_markup(str(call.message.chat.id)))

    @bot.callback_query_handler(func=lambda c: c.data.startswith('ignore_'))
    async def ignore_store(call: types.CallbackQuery):
        if not await check_authorization(call):
            await bot.answer_callback_query(call.id, text="You are not authorized to perform this action.")
            return
        _, store_id, store_name = call.data.split('_', 2)
        logger.info(f"Ignoring store {store_name} (ID: {store_id}) for chat {call.message.chat.id}")
        success = await tooGoodToGo.add_to_blacklist(str(call.message.chat.id), store_id, store_name)
        if success:
            await bot.answer_callback_query(call.id, text=f"Store '{store_name}' has been ignored.")
            await bot.edit_message_reply_markup(chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=None)
        else:
            await bot.answer_callback_query(call.id, text="Failed to ignore store. Please try again.")

    @bot.message_handler(commands=['blacklist'])
    async def manage_blacklist(message):
        if not await check_authorization(message):
            return
        logger.info(f"Received /blacklist command in chat {message.chat.id}")
        await tooGoodToGo.get_blacklist(str(message.chat.id))

    @bot.callback_query_handler(func=lambda call: call.data.startswith('remove_blacklist_'))
    async def callback_remove_blacklist(call):
        if not await check_authorization(call):
            await bot.answer_callback_query(call.id, text="You are not authorized to perform this action.")
            return
        logger.info(f"Received remove_blacklist callback in chat {call.message.chat.id}")
        await tooGoodToGo.handle_remove_blacklist_callback(call)

    @bot.message_handler(commands=['remove_blacklist'])
    async def remove_from_blacklist(message):
        if not await check_authorization(message):
            return
        logger.info(f"Received /remove_blacklist command in chat {message.chat.id}")
        try:
            _, store_id = message.text.split(maxsplit=1)
            store_id = store_id.strip()
            blacklisted_stores = tooGoodToGo.db.get_blacklisted_stores(str(message.chat.id))
            store_name = next((name for id, name in blacklisted_stores if id == store_id), None)
            if store_name:
                await tooGoodToGo.remove_from_blacklist(str(message.chat.id), store_id, store_name)
            else:
                await bot.send_message(message.chat.id, f"Store with ID {store_id} is not in your blacklist.")
        except ValueError:
            await bot.send_message(message.chat.id, "Please use the format: /remove_blacklist <store_id>")

    @bot.message_handler(commands=['generate_token'])
    async def generate_token(message):
        if not await check_authorization(message):
            return
        token = tooGoodToGo.db.generate_token()
        await bot.reply_to(
            message,
            "New invite token generated. Forward the next message to the new user — "
            "they just need to send it to the bot to gain access.",
        )
        await bot.send_message(message.chat.id, f"/start {token}")
        logger.info(f"Admin {message.from_user.id} generated a new token")

    @bot.message_handler(commands=['list_tokens'])
    async def list_tokens(message):
        if not await check_authorization(message):
            return
        tokens = tooGoodToGo.get_all_tokens()
        response = "List of tokens:\n\n"
        for token, user_id, first_name in tokens:
            status = "Used" if user_id else "Unused"
            user_info = f"User: {first_name} (ID: {user_id})" if user_id else "N/A"
            response += f"Token: {token}\nStatus: {status}\n{user_info}\n\n"
        await bot.reply_to(message, response)
        logger.info(f"Admin {message.from_user.id} requested token list")

    @bot.message_handler(func=lambda m: True, content_types=['text'])
    async def handle_followup(message):
        """Catch-all for plain (non-command) text. Routes the message to a pending
        conversational flow if one is active for this chat; otherwise nudges the
        user toward /help. Commands never reach here — telebot dispatches them to
        their own handlers — so sending any command cancels a pending prompt."""
        chat_id = str(message.chat.id)
        kind = tooGoodToGo.get_awaiting(chat_id)
        if not kind:
            return
        # Token redemption is the only flow allowed before authorization.
        if kind != "token" and not await check_authorization(message):
            tooGoodToGo.clear_awaiting(chat_id)
            return
        tooGoodToGo.clear_awaiting(chat_id)
        text = message.text.strip()
        if kind == "email":
            await submit_email(message, text)
        elif kind == "relogin_email":
            await submit_email(message, text, relogin=True)
        elif kind == "pin":
            await submit_pin(message, text)
        elif kind == "token":
            await submit_token(message, text)

    async def shutdown():
        logger.info("Shutting down Telegram bot...")
        await bot.close()
        logger.info("Telegram bot shutdown complete.")

    bot.shutdown = shutdown
    return bot
