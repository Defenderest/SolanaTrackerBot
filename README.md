# Solana New Pair Tracker Bot

<div align="center">



### A Blazing Fast, Real-Time Solana New Pair Bot for Raydium

[![Python Version](https://img.shields.io/badge/Python-3.8%2B-blue.svg)](https://www.python.org/downloads/)
[![Telegram](https://img.shields.io/badge/Platform-Telegram-blue.svg)](https://telegram.org/)
[![Alchemy](https://img.shields.io/badge/API-Alchemy-blueviolet.svg)](https://www.alchemy.com/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Contributions Welcome](https://img.shields.io/badge/Contributions-welcome-brightgreen.svg?style=flat)](https://github.com/Defenderest/SolanaTrackerBot/pulls)

</div>

In the high-velocity world of Solana DeFi, speed is everything. This bot provides a critical intelligence advantage by monitoring the Raydium Automated Market Maker (AMM) in real-time and delivering **instant notifications to your Telegram** the moment a new liquidity pool is created. Be the first to know, the first to analyze, and the first to act.

---

## 📜 Table of Contents

- [⭐ Project Philosophy](#-project-philosophy)
- [✨ Key Features](#-key-features)
- [⚙️ Architectural Flow](#️-architectural-flow)
- [🔬 How It Works: A Deep Dive](#-how-it-works-a-deep-dive)
- [📲 Example Notification](#-example-notification)
- [🛠️ Technology Stack](#️-technology-stack)
- [🔑 Prerequisites: Getting Your Keys](#-prerequisites-getting-your-keys)
- [🚀 Installation & Setup Guide](#-installation--setup-guide)
- [🏃 Running the Bot](#-running-the-bot)
  - [Running in the Background (24/7)](#running-in-the-background-247)
- [🔧 Configuration Details](#-configuration-details)
- [❓ Troubleshooting & FAQ](#-troubleshooting--faq)
- [🗺️ Future Roadmap](#️-future-roadmap)
- [🛡️ A Note on Security](#️-a-note-on-security)
- [🤝 Contributing](#-contributing)
- [📄 License](#-license)
- [🙏 Acknowledgements](#-acknowledgements)

---

## ⭐ Project Philosophy

The goal of this project is to democratize access to on-chain data. While sophisticated trading firms have teams building complex monitoring systems, this bot provides powerful, real-time capabilities in a simple, open-source package that anyone can run.

## ✨ Key Features

- **Sub-Minute Latency**: Utilizes a highly efficient RPC method to detect new pairs almost instantly after the creation transaction is confirmed on the Solana blockchain.
- **Actionable Intelligence**: Each notification is not just an alert; it's a data packet with everything you need:
    - Token Names & Symbols (e.g., WEN / SOL).
    - Verifiable Mint Addresses for both tokens.
    - The official Raydium Liquidity Pool (LP) address.
    - A **direct, clickable link** to the pair's trading page on Raydium.
- **Optimized API Usage**: Employs the `getSignaturesForAddress` method, which is lightweight and consumes minimal API credits, allowing for frequent polling even on free plans.
- **Secure by Design**: All sensitive credentials (API keys, bot tokens) are managed via environment variables and are never hard-coded. The `.gitignore` file prevents accidental exposure.
- **24/7 Unattended Operation**: Designed for stability, allowing it to run continuously on a server or a local machine.
- **Extensible Codebase**: Written in clean, commented Python, making it easy for developers to customize or build upon.

## ⚙️ Architectural Flow

The bot follows a simple yet effective data pipeline:

```
+----------------+      +------------------+      +-------------------+
|   Python Bot   |----->|   Alchemy API    |----->|  Solana Blockchain|
| (main.py)      |      | (RPC Endpoint)   |      |   (On-Chain Data) |
+----------------+      +------------------+      +-------------------+
        ^                       |                           |
        | (Format & Send)       | (Returns Signatures)      |
        |                       V                           |
+----------------+      +------------------+                |
|  Telegram API  |<-----|  Process Data &  |                |
|                |      |  Filter New Pairs|                |
+----------------+      +------------------+                |
        |                                                   |
        V                                                   |
+----------------+                                          |
| Your Telegram  | <----------------------------------------+
|   Chat/User    |
+----------------+
```

## 🔬 How It Works: A Deep Dive

1.  **Initialization**: On launch, the bot securely loads your `TELEGRAM_TOKEN`, `CHAT_ID`, and `ALCHEMY_API_URL` from the `.env` file. It initializes a Python `set` named `seen_pool_ids` to keep an in-memory record of pools it has already alerted for, preventing duplicates.

2.  **The Loop**: The core of the bot is a continuous `while` loop that executes the monitoring logic.

3.  **Querying the Blockchain**: In each cycle, the bot constructs a JSON-RPC request and sends it to your **Alchemy API endpoint**. It calls the `getSignaturesForAddress` method, passing Raydium's official "Liquidity Pool v4" program address as the target. This is a highly efficient way to get a history of all transactions that have interacted with the Raydium contract.

4.  **Signature Processing**: Alchemy returns a list of recent transaction signatures. The bot iterates through these signatures. For each one, it parses the transaction data to find the newly created Liquidity Pool ID.

5.  **Smart Filtering**: The bot checks if the extracted pool ID is present in the `seen_pool_ids` set.
    - **If it's a new ID**: The bot proceeds to format a notification message.
    - **If the ID already exists**: The bot ignores it and moves to the next signature, ensuring your chat remains clean and free of spam.

6.  **Notification & State Update**: For a new pool, a detailed, human-readable message is crafted. The `python-telegram-bot` library then sends this message to your specified `CHAT_ID`. Immediately after a successful send, the new pool ID is added to the `seen_pool_ids` set.

7.  **Cooldown & Repeat**: The bot then pauses for the duration specified by `BOT_INTERVAL` (default is 60 seconds) before starting the loop all over again.

## 📲 Example Notification

This is what you'll receive in Telegram:

```
🚀 New Raydium Liquidity Pool Detected! 🚀

Token A: WIF (Dogwifhat)
Mint A: EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzL7M6bMktdKQe

Token B: SOL (Wrapped SOL)
Mint B: So11111111111111111111111111111111111111112

🔗 Raydium Link:
https://raydium.io/liquidity/AnY18sFqGSHyE1y1pAfA8y1tM5y1t3s6y9tM2w1k4qWb
```
*(Note: Data is illustrative)*

## 🛠️ Technology Stack

- **Language**: Python 3
- **Blockchain Interaction**: `requests` (for raw JSON-RPC calls)
- **Telegram Integration**: `python-telegram-bot`
- **Environment Management**: `python-dotenv`
- **Primary Data Provider**: [Alchemy Solana API](https://www.alchemy.com/solana)

## 🔑 Prerequisites: Getting Your Keys

You need three things. All are free to obtain.

1.  **A Telegram Bot Token**:
    - Message [@BotFather](https://t.me/BotFather) on Telegram.
    - Type `/newbot` and follow the prompts to name your bot.
    - BotFather will give you an **API Token**. Save it.

2.  **Your Telegram Chat ID**:
    - Message [@userinfobot](https://t.me/userinfobot).
    - Type `/start`.
    - It will reply with your details. Your `Id` is your **Chat ID**.

3.  **An Alchemy API URL for Solana**:
    - Go to [alchemy.com](https://alchemy.com/) and create a free account.
    - From your dashboard, click **"+ CREATE APP"**.
    - Fill out the details:
        - **Chain**: `Solana`
        - **Network**: `Solana Mainnet`
        - Give your app a name (e.g., "Raydium Tracker").
    - Click **"CREATE APP"**.
    - On the next page, click **"VIEW KEY"**.
    - Copy the **HTTPS** URL. This is your `ALCHEMY_API_URL`.

## 🚀 Installation & Setup Guide

#### 1. Clone the Repository
Open your terminal and clone the project.
```bash
git clone https://github.com/Defenderest/SolanaTrackerBot.git
cd SolanaTrackerBot
```

#### 2. Create a Virtual Environment
This is a critical step to avoid conflicts with other Python projects.
- **On macOS / Linux**:
  ```bash
  python3 -m venv venv
  source venv/bin/activate
  ```
- **On Windows**:
  ```bash
  python -m venv venv
  .\venv\Scripts\activate
  ```
Your terminal prompt should now be prefixed with `(venv)`.

#### 3. Install Dependencies
Install all required libraries from the `requirements.txt` file.
```bash
pip install -r requirements.txt
```

#### 4. Configure Environment Variables
Create a `.env` file in the project's root directory.
```bash
# On macOS / Linux
touch .env

# On Windows
copy con .env
# Press Enter, then CTRL+Z, then Enter again to create an empty file.
```

Open `.env` with a text editor and paste the following, **replacing the placeholders with your actual keys**.

```ini
# --- .env file ---

# Your Telegram Bot API Token from @BotFather
TELEGRAM_TOKEN="123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11"

# Your personal Telegram Chat ID from @userinfobot
CHAT_ID="123456789"

# Your full HTTPS API URL from Alchemy
ALCHEMY_API_URL="https://solana-mainnet.g.alchemy.com/v2/your-unique-key"

# (Optional) The interval in seconds to check for new pairs.
# Lower value = faster alerts but more API calls. Default is 60.
BOT_INTERVAL=60
```

## 🏃 Running the Bot

Once configured, start the bot from your terminal:
```bash
python main.py
```

The console will display:
`Bot started successfully. Monitoring for new Raydium pairs...`

The bot is now active. To stop it, press `CTRL + C`.

### Running in the Background (24/7)

For continuous operation on a server (like a VPS), you should run the script in a way that it doesn't stop when you close your terminal.

**Method 1: `nohup` (Simple)**
```bash
nohup python main.py &
```
This runs the bot in the background and saves any output to a file named `nohup.out`.

**Method 2: `tmux` or `screen` (Recommended)**
These tools create persistent terminal sessions.
```bash
# Example with tmux
tmux new -s solana-bot   # Create a new session named "solana-bot"
python main.py           # Start the bot inside the session
```
You can now safely detach from the session by pressing `Ctrl+B` then `D`. The bot will keep running. To re-attach later: `tmux attach -t solana-bot`.

## 🔧 Configuration Details

All settings are managed in the `.env` file.

| Variable          | Description                                                                     | Required | Default |
| ----------------- | ------------------------------------------------------------------------------- | -------- | ------- |
| `TELEGRAM_TOKEN`  | Your Telegram bot's unique API token.                                           | **Yes**  | `None`  |
| `CHAT_ID`         | The destination chat ID for notifications.                                      | **Yes**  | `None`  |
| `ALCHEMY_API_URL` | Your full HTTPS endpoint URL from Alchemy for the Solana Mainnet.               | **Yes**  | `None`  |
| `BOT_INTERVAL`    | The delay in seconds between each check. Adjust based on your need for speed vs. API usage. | No       | `60`    |

## ❓ Troubleshooting & FAQ

- **Error: "Missing required environment variables"**
  - **Cause**: The script cannot find your `.env` file or it's missing keys.
  - **Solution**:
    1.  Ensure the file is named exactly `.env` (not `env.txt`).
    2.  Confirm it is in the root directory of the project.
    3.  Check that `TELEGRAM_TOKEN`, `CHAT_ID`, and `ALCHEMY_API_URL` are all present and have values.

- **Problem: The bot runs but I get no messages in Telegram.**
  - **Cause**: The bot cannot contact you.
  - **Solution**:
    1.  **Crucial Step**: You must initiate the conversation. Find your bot on Telegram via its username and send it a `/start` message. Bots cannot message users who haven't interacted with them first.
    2.  Double-check that your `CHAT_ID` is correct.
    3.  If using the bot in a group, ensure the bot has been added as a member and has permission to post messages.

- **Error: 401 Unauthorized or 403 Forbidden**
  - **Cause**: Your API key is invalid.
  - **Solution**: Go back to your Alchemy dashboard and copy the HTTPS API URL again. Ensure there are no extra spaces or characters.

- **Error: 429 Too Many Requests**
  - **Cause**: You are exceeding the rate limits of your Alchemy free plan.
  - **Solution**: Open your `.env` file and increase the `BOT_INTERVAL` to a higher value (e.g., `120` or `300`).

## 🗺️ Future Roadmap

This project is actively maintained. Future enhancements may include:
- [ ] **Persistent State**: Integrate a lightweight database like SQLite to remember seen pools across bot restarts.
- [ ] **Advanced Filtering**: Add environment variables to filter pairs by minimum initial liquidity (e.g., `MIN_LIQUIDITY_USD=1000`).
- [ ] **Token Metadata Enrichment**: Fetch and display more data about the tokens, such as whether the mint authority is revoked (a key security indicator).
- [ ] **Interactive Commands**: Add Telegram commands like `/stats` (show bot uptime and pairs found), `/last` (re-send the last notification), or `/pause`.
- [ ] **Multi-DEX Support**: Expand the architecture to monitor other Solana DEXs like Orca and Meteora.
- [ ] **Web Dashboard**: A simple web interface to view found pairs and configure the bot.

## 🛡️ A Note on Security

- **NEVER** share your `.env` file or post its contents publicly. It contains keys that grant access to your bot and API services.
- **NEVER** commit your `.env` file to Git. This project's `.gitignore` is already configured to prevent this, but always be vigilant.
- Be aware of the risks of trading new, unvetted tokens. Many are scams ("rug pulls"). This bot is an informational tool, not an endorsement of any token it finds.

## 🤝 Contributing

Contributions are the lifeblood of open source. If you have an idea for an improvement or have found a bug, please feel free to:
1.  Fork the Project
2.  Create your Feature Branch (`git checkout -b feature/MyAwesomeFeature`)
3.  Commit your Changes (`git commit -m 'Add some AwesomeFeature'`)
4.  Push to the Branch (`git push origin feature/MyAwesomeFeature`)
5.  Open a Pull Request

## 📄 License

This project is licensed under the MIT License. See the `LICENSE` file for more details. This means you are free to use, modify, and distribute the code, even for commercial purposes, as long as you include the original copyright and license notice.

## 🙏 Acknowledgements

- The [Python-Telegram-Bot](https://python-telegram-bot.org/) team for their excellent library.
- [Alchemy](https://www.alchemy.com/) for providing a robust and reliable Solana API.
- The entire Solana development community.
