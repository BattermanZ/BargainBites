# BargainBites

**BargainBites** is a Python app that helps you track and grab discounted food deals from Too Good To Go. It can handle multiple users, group chats, and private chats with interactive Telegram bot notifications, making saving food waste more engaging. 🍽️

## Features

- **Login Made Easy**: Use the Telegram bot to log in with your email.
- **Tailored Alerts**: Get notified when items are back in stock, sold out, or when something changes.
- **Always Updated**: The app keeps an eye on your favourites in the background.
- **Multi-User Support**: Multiple users can log in and use the bot simultaneously.
- **Private Chat and Token Access**: Authorise private access using admin-generated tokens.
- **Admin Features**: Includes admin-only commands for managing users and tokens.
- **Interactive Blacklist Management**: Users can blacklist or unblacklist stores.
- **Custom Alerts**: Set when and how to be notified about deals using an inline keyboard.
- **Secure Storage**: 💾 Saves login and preferences securely in a local SQLite database.

## Getting Started

### What You Need

- Docker (optional)
- A Too Good To Go account
- A Telegram bot token
- Python 3.12 or higher

### Setup

1. Clone this repo:

   ```bash
   git clone <repository-url>
   cd <repository-folder>
   ```

2. **Optional**: Use Docker for setup:

   ```bash
   docker build -t bargainbites .
   docker run -d --name bargainbites-container bargainbites
   ```

3. Create a `.env` file from the template:

   ```bash
   cp .env.example .env
   ```

   Then edit `.env` with your values:
   ```ini
   TELEGRAM_BOT_TOKEN=your_bot_token_here
   TELEGRAM_ADMIN_IDS=comma_separated_admin_ids  # e.g., 123456789,987654321
   ```

4. Run without Docker:

   ```bash
   python3 -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   pip install -r requirements.txt
   python3 app/main.py
   ```

5. **Login to Too Good To Go**: 🔑 Enter this in Telegram:

   *❗️️This is necessary if you want to use the bot❗️*

   ```
   /login email@example.com
   ```

   *Check your email for a confirmation link. No password needed!*

## How to Use It

### General Users

- Each user must have their own Too Good To Go account to use the bot.
- Use the bot directly in a private chat or add it to a group chat for shared notifications.
- If using a group chat:
  - Grant it admin rights (it needs to manage messages). 🔧
  - Turn off its privacy mode so it can read all group messages. 🔓

### Admin Users

Admins can manage tokens, and authorise private users. Admins are configured via the `config.ini` file using their Telegram user IDs.

### Commands You Can Use

#### General Commands

- `/help`: 📖 Get instructions.
- `/start`: ▶️ Start or restart the bot.
- `/login <email>`: 🔑 Log in to Too Good To Go with your email.
- `/settings`: ⚙️ Adjust your notification preferences.
- `/info`: ℹ️ See what deals are currently available.
- `/blacklist`: 🚫 View and manage blacklisted stores interactively.

#### Admin Commands

- `/generate_token`: 🔑 Generate a private access token.
- `/list_tokens`: 📋 View all generated tokens and their usage statuses.
- `/remove_blacklist <store_id>`: 🗑️ Remove a store from the blacklist manually.

## Key Features Explained

### Private Access Tokens

Admins can generate private tokens to authorise specific users in private chats:

1. Use `/generate_token` to create a token.
2. Share the token with the user you wish to authorise.
3. The user enters `/start <token>` in a private chat with the bot to gain access.

### Interactive Settings

Notification settings are managed using an inline keyboard:

- Toggle notifications for events like `sold_out`, `new_stock`, `stock_increased`, and `stock_reduced`.
- Use buttons to enable or disable all notifications at once.

### Blacklist Management

- Add stores to the blacklist to stop receiving notifications about them.
- Remove stores interactively via `/blacklist` or manually with `/remove_blacklist <store_id>`.
- Blacklist buttons are also available directly in notification messages.

### Background Checks

- The app automatically checks for new available bags from your favourites every 15 minutes with random intervals to avoid bot detection.
- Additional random delays between user checks (20-40 seconds) help prevent CAPTCHA challenges.
- The timing includes random jitter (±2 minutes) and small noise (±10 seconds) for less predictable behavior.

## Project Layout

```
├── app/
│   ├── database.py          # Handles SQLite database
│   ├── TooGoodToGo.py      # Talks to the Too Good To Go API
│   ├── Telegram.py         # Manages Telegram bot
│   ├── main.py             # Runs everything
├── Dockerfile              # Docker setup
├── requirements.txt        # Python dependencies
├── .env                   # Environment variables (not in git)
├── .env.example           # Template for .env file
├── database/              # Where SQLite stores data
└── logs/                  # Keeps logs
```

## Environment Variables

The app uses a `.env` file for configuration:

- `TELEGRAM_BOT_TOKEN`: Your Telegram bot token from @BotFather
- `TELEGRAM_ADMIN_IDS`: Comma-separated list of Telegram user IDs for admin access

## Anti-Bot Protection

The app implements several measures to avoid triggering Too Good To Go's bot detection:

- Random delays between checks (15 minutes base with ±2 minutes jitter)
- Additional small random noise (±10 seconds) for less predictable timing
- Increased delays between user checks (20-40 seconds)
- Automatic handling of rate limits and CAPTCHA challenges
- Random shuffling of user order during checks

## AI Warning

This app was partially built and adapted using AI tools. While every effort has been made to ensure the code is functional and secure, please:

- Carefully review the code before using it in production.
- Test it in a safe environment to confirm it works as expected.

Your security and privacy are important—proceed with caution! 🛡️

## Shoutouts

Big thanks to these awesome projects:

- **[tgtg-python](https://github.com/ahivert/tgtg-python)**: For the Too Good To Go API wrapper.
- **[TooGoodToGo-TelegramBot](https://github.com/TorbenStriegel/TooGoodToGo-TelegramBot)**: The app I forked from and adapted for this project. Many thanks for your implementation!
- **[Too Good To Go](https://www.toogoodtogo.com/)**: For helping us all reduce food waste. 🌍

## License

This project is licensed under the GPL 3 License.

