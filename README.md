BargainBites

BargainBites is a Python app that helps you track and grab discounted food deals from Too Good To Go. It can handle multiple users, group chats, and private chats with interactive Telegram bot notifications, making saving food waste more engaging. 🍽️

Features

Login Made Easy: Use the Telegram bot to log in with your email.

Tailored Alerts: Get notified when items are back in stock, sold out, or when something changes.

Always Updated: The app keeps an eye on your favourites in the background.

Multi-User Support: Multiple users can log in and use the bot simultaneously.

Private Chat and Token Access: Authorise private access using admin-generated tokens.

Admin Features: Includes admin-only commands for managing users and tokens.

Interactive Blacklist Management: Users can blacklist or unblacklist stores.

Custom Alerts: Set when and how to be notified about deals using an inline keyboard.

Secure Storage: 💾 Saves login and preferences securely in a local SQLite database.

Getting Started

What You Need

Docker (optional)

A Too Good To Go account

A Telegram bot token and group chat ID

Setup

Clone this repo:

git clone <repository-url>
cd <repository-folder>

Optional: Use Docker for setup:

docker build -t bargainbites .
docker run -d --name bargainbites-container bargainbites

Create a config.ini file:

[Telegram]
token = <your-telegram-bot-token>
group_chat_id = <your-telegram-group-chat-id> # group_chat_id is optional. Use it for group chat notifications
admin_ids = <comma-separated-admin-ids>

Run without Docker:

python3 app/main.py

Login to Too Good To Go: 🔑 Enter this in Telegram:

❗️️This is necessary if you want to use the bot❗️

/login email@example.com

Check your email for a confirmation link. No password needed!

How to Use It

General Users

Each user must have their own Too Good To Go account to use the bot.

Use the bot directly in a private chat or add it to a group chat for shared notifications.

If using a group chat:

Grant it admin rights (it needs to manage messages). 🔧

Turn off its privacy mode so it can read all group messages. 🔓

Admin Users

Admins can manage tokens, and authorise private users. Admins are configured via the config.ini file using their Telegram user IDs.

Commands You Can Use

General Commands

/help: 📖 Get instructions.

/start: ▶️ Start or restart the bot.

/login <email>: 🔑 Log in to Too Good To Go with your email.

/settings: ⚙️ Adjust your notification preferences.

/info: ℹ️ See what deals are currently available.

/blacklist: 🚫 View and manage blacklisted stores interactively.

Admin Commands

/generate_token: 🔑 Generate a private access token.

/list_tokens: 📋 View all generated tokens and their usage statuses.

/remove_blacklist <store_id>: 🗑️ Remove a store from the blacklist manually.

Key Features Explained

Private Access Tokens

Admins can generate private tokens to authorise specific users in private chats:

Use /generate_token to create a token.

Share the token with the user you wish to authorise.

The user enters /start <token> in a private chat with the bot to gain access.

Interactive Settings

Notification settings are managed using an inline keyboard:

Toggle notifications for events like sold_out, new_stock, stock_increased, and stock_reduced.

Use buttons to enable or disable all notifications at once.

Blacklist Management

Add stores to the blacklist to stop receiving notifications about them.

Remove stores interactively via /blacklist or manually with /remove_blacklist <store_id>.

Blacklist buttons are also available directly in notification messages.

Background Checks

The app automatically checks for new available bags from your favourites every 5 minutes and sends notifications if any changes are detected.

Project Layout

├── app
│   ├── database.py          # Handles SQLite database
│   ├── TooGoodToGo.py       # Talks to the Too Good To Go API
│   ├── Telegram.py          # Manages Telegram bot
│   ├── main.py              # Runs everything
├── Dockerfile               # Docker setup
├── requirements.txt         # Python dependencies
├── config.ini               # Bot and API credentials
├── database/                # Where SQLite stores data
└── logs/                    # Keeps logs

AI Warning

This app was partially built and adapted using AI tools. While every effort has been made to ensure the code is functional and secure, please:

Carefully review the code before using it in production.

Test it in a safe environment to confirm it works as expected.

Your security and privacy are important—proceed with caution! 🛡️

Shoutouts

Big thanks to these awesome projects:

tgtg-python: For the Too Good To Go API wrapper.

TooGoodToGo-TelegramBot: The app I forked from and adapted for this project. Many thanks for your implementation!

Too Good To Go: For helping us all reduce food waste. 🌍

License

This project is licensed under the GPL 3 License.

