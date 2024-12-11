import re
import configparser
import asyncio
from _thread import start_new_thread

from telebot import types
from telebot.async_telebot import AsyncTeleBot

from TooGoodToGo import TooGoodToGo

config = configparser.ConfigParser()
config.read('config.ini')
token = config['Telegram']['token']
group_chat_id = config['Telegram']['group_chat_id']  # Add this line to read group chat ID
bot = AsyncTeleBot(token)
tooGoodToGo = TooGoodToGo(token)


# Handle '/start' and '/help'
@bot.message_handler(commands=['help', 'start'])
async def send_welcome(message):
    if str(message.chat.id) != group_chat_id:
        return  # Ignore messages not from the specified group
    await bot.send_message(group_chat_id,
                           """
*Hi welcome to the TGTG Bot:*

The bot will notify this group as soon as new bags from the favorites are available.

*❗️️This is necessary if you want to use the bot❗️*
🔑 To login into the TooGoodToGo account for this group, enter 
*/login email@example.com*
_You will then receive an email with a confirmation link.
You do not need to enter a password._

⚙️ With */settings* you can set when the group wants to be notified. 

ℹ️ With */info* you can display all stores from the favorites where bags are currently available.

_🌐 You can find more information about Too Good To Go_ [here](https://www.toogoodtogo.com/).

*🌍 LET'S FIGHT food waste TOGETHER 🌎*
""", parse_mode="Markdown")


@bot.message_handler(commands=['info'])
async def send_info(message):
    if str(message.chat.id) != group_chat_id:
        return  # Ignore messages not from the specified group
    credentials = tooGoodToGo.find_credentials_by_telegramUserID(group_chat_id)
    if credentials is None:
        await bot.send_message(chat_id=group_chat_id,
                               text="🔑 You have to log in with your mail first!\nPlease enter */login email@example.com*\n*❗️️This is necessary if you want to use the bot❗️*",
                               parse_mode="Markdown")
        return None
    tooGoodToGo.send_available_favourite_items_for_one_user(group_chat_id)


@bot.message_handler(commands=['login'])
async def send_login(message):
    if str(message.chat.id) != group_chat_id:
        return  # Ignore messages not from the specified group
    credentials = tooGoodToGo.find_credentials_by_telegramUserID(group_chat_id)
    if credentials is not None:
        await bot.send_message(chat_id=group_chat_id, text="👍 This group is already logged in!")
        return None
    email = message.text.replace('/login', '').lstrip()
    print(email, "  ", group_chat_id)

    if re.match(r"[^@]+@[^@]+\.[^@]+", email):
        await bot.send_message(chat_id=group_chat_id, text="📩 Please open your mail account"
                                                     "\nYou will then receive an email with a confirmation link."
                                                     "\n*You must open the link in your browser!*"
                                                     "\n_You do not need to enter a password._", parse_mode="markdown")
        start_new_thread(tooGoodToGo.new_user, (group_chat_id, email))
    else:
        await bot.send_message(chat_id=group_chat_id,
                               text="*⚠️ No valid mail address ⚠️*"
                                    "\nPlease enter */login email@example.com*"
                                    "\n_You will then receive an email with a confirmation link."
                                    "\nYou do not need to enter a password._",
                               parse_mode="Markdown")


def inline_keyboard_markup():
    inline_keyboard = types.InlineKeyboardMarkup(
        keyboard=[
            [
                types.InlineKeyboardButton(
                    text=("🟢" if tooGoodToGo.users_settings_data[group_chat_id]["sold_out"] else "🔴") + " sold out",
                    callback_data="sold_out"
                ),
                types.InlineKeyboardButton(
                    text=("🟢" if tooGoodToGo.users_settings_data[group_chat_id]["new_stock"] else "🔴") + " new stock",
                    callback_data="new_stock"
                )
            ],
            [
                types.InlineKeyboardButton(
                    text=("🟢" if tooGoodToGo.users_settings_data[group_chat_id]["stock_reduced"] else "🔴") + " stock reduced",
                    callback_data="stock_reduced"
                ),
                types.InlineKeyboardButton(
                    text=("🟢" if tooGoodToGo.users_settings_data[group_chat_id][
                        "stock_increased"] else "🔴") + " stock increased",
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
    if str(message.chat.id) != group_chat_id:
        return  # Ignore messages not from the specified group
    credentials = tooGoodToGo.find_credentials_by_telegramUserID(group_chat_id)
    if credentials is None:
        await bot.send_message(chat_id=group_chat_id,
                               text="🔑 You have to log in with your mail first!\nPlease enter */login email@example.com*\n*❗️️This is necessary if you want to use the bot❗️*",
                               parse_mode="Markdown")
        return None

    await bot.send_message(group_chat_id, "🟢 = enabled | 🔴 = disabled  \n*Activate alert if:*", parse_mode="markdown",
                           reply_markup=inline_keyboard_markup())


@bot.callback_query_handler(func=lambda c: c.data == 'sold_out')
async def back_callback(call: types.CallbackQuery):
    if str(call.message.chat.id) != group_chat_id:
        return  # Ignore callbacks not from the specified group
    settings = tooGoodToGo.users_settings_data[group_chat_id]["sold_out"]
    tooGoodToGo.users_settings_data[group_chat_id]["sold_out"] = 0 if settings else 1
    await bot.edit_message_reply_markup(chat_id=group_chat_id, message_id=call.message.message_id,
                                        reply_markup=inline_keyboard_markup())
    tooGoodToGo.save_users_settings_data_to_txt()


@bot.callback_query_handler(func=lambda c: c.data == 'new_stock')
async def back_callback(call: types.CallbackQuery):
    if str(call.message.chat.id) != group_chat_id:
        return  # Ignore callbacks not from the specified group
    settings = tooGoodToGo.users_settings_data[group_chat_id]["new_stock"]
    tooGoodToGo.users_settings_data[group_chat_id]["new_stock"] = 0 if settings else 1
    await bot.edit_message_reply_markup(chat_id=group_chat_id, message_id=call.message.message_id,
                                        reply_markup=inline_keyboard_markup())
    tooGoodToGo.save_users_settings_data_to_txt()


@bot.callback_query_handler(func=lambda c: c.data == 'stock_reduced')
async def back_callback(call: types.CallbackQuery):
    if str(call.message.chat.id) != group_chat_id:
        return  # Ignore callbacks not from the specified group
    settings = tooGoodToGo.users_settings_data[group_chat_id]["stock_reduced"]
    tooGoodToGo.users_settings_data[group_chat_id]["stock_reduced"] = 0 if settings else 1
    await bot.edit_message_reply_markup(chat_id=group_chat_id, message_id=call.message.message_id,
                                        reply_markup=inline_keyboard_markup())
    tooGoodToGo.save_users_settings_data_to_txt()


@bot.callback_query_handler(func=lambda c: c.data == 'stock_increased')
async def back_callback(call: types.CallbackQuery):
    if str(call.message.chat.id) != group_chat_id:
        return  # Ignore callbacks not from the specified group
    settings = tooGoodToGo.users_settings_data[group_chat_id]["stock_increased"]
    tooGoodToGo.users_settings_data[group_chat_id]["stock_increased"] = 0 if settings else 1
    await bot.edit_message_reply_markup(chat_id=group_chat_id, message_id=call.message.message_id,
                                        reply_markup=inline_keyboard_markup())
    tooGoodToGo.save_users_settings_data_to_txt()


@bot.callback_query_handler(func=lambda c: c.data == 'activate_all')
async def back_callback(call: types.CallbackQuery):
    if str(call.message.chat.id) != group_chat_id:
        return  # Ignore callbacks not from the specified group
    for key in tooGoodToGo.users_settings_data[group_chat_id].keys():
        tooGoodToGo.users_settings_data[group_chat_id][key] = 1
    tooGoodToGo.save_users_settings_data_to_txt()
    await bot.edit_message_reply_markup(chat_id=group_chat_id, message_id=call.message.message_id,
                                        reply_markup=inline_keyboard_markup())


@bot.callback_query_handler(func=lambda c: c.data == 'disable_all')
async def back_callback(call: types.CallbackQuery):
    if str(call.message.chat.id) != group_chat_id:
        return  # Ignore callbacks not from the specified group
    for key in tooGoodToGo.users_settings_data[group_chat_id].keys():
        tooGoodToGo.users_settings_data[group_chat_id][key] = 0
    tooGoodToGo.save_users_settings_data_to_txt()
    await bot.edit_message_reply_markup(chat_id=group_chat_id, message_id=call.message.message_id,
                                        reply_markup=inline_keyboard_markup())


asyncio.run(bot.polling())