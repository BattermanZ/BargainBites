# BargainBites

**BargainBites** is a Python app that helps you grab discounted food deals from Too Good To Go. It pings you via Telegram when awesome deals are up for grabs, helping you save money and fight food waste. 🍽️

## Features

- **Login Made Easy**: Use the Telegram bot to log in with your email.
- **Tailored Alerts**: Get notified when items are back in stock, sold out, or when something changes.
- **Always Updated**: The app keeps an eye on your favourites in the background.
- **Instant Alerts**: 📲 Telegram notifications for hot deals.
- **Secure Storage**: 💾 Saves your login and preferences safely in an SQLite database.

## Getting Started

### What You Need

- Docker (if you prefer)
- A Too Good To Go account
- A Telegram bot token and group chat ID

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

3. Create a `config.ini` file:

   ```ini
   [Telegram]
   token = <your-telegram-bot-token>
   group_chat_id = <your-telegram-group-chat-id>
   ```

4. Run without Docker:

   ```bash
   python3 app/main.py
   ```

5. **Login to Too Good To Go**: 🔑 Enter this in Telegram:

   *❗️️This is necessary if you want to use the bot❗️*

   ```
   /login email@example.com
   ```

   *Check your email for a confirmation link. No password needed!*

## How to Use It

**Heads Up**: BargainBites only works in Telegram group chats. Here’s what you need to do:

- Add the bot to your group.
- Give it admin rights from your phone (it needs to manage messages). 🔧
- Turn off its privacy mode so it can read all group messages. 🔓

### Commands You Can Use

- `/help`: 📖 Get instructions.
- `/start`: ▶️ Start or restart the bot.
- `/login <email>`: 🔑 Log in to Too Good To Go with your email.
- `/settings`: ⚙️ Adjust your notification preferences.
- `/info`: ℹ️ See what deals are currently available.

## Project Layout

```
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
```

## AI Warning

This app was partially built and adapted using AI tools. While every effort has been made to ensure the code is functional and secure, please:

- Carefully review the code before using it in production.
- Test it in a safe environment to confirm it works as expected.

Your security and privacy are important—proceed with caution! 🛡️

## Acknowledgements

Big thanks to these awesome projects:

- **[tgtg-python](https://github.com/ahivert/tgtg-python)**: For the Too Good To Go API wrapper.
- **[TooGoodToGo-TelegramBot](https://github.com/TorbenStriegel/TooGoodToGo-TelegramBot)**: The app I forked from and adapted for this project. Many thanks for your implementation!
- **[Too Good To Go](https://www.toogoodtogo.com/)**: For helping us all reduce food waste. 🌍

## License

This project is licensed under the GPL 3 License.

