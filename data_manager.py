import json
from config import DEFAULT_RPC_URL

USER_DATA_FILE = "user_data.json"


def load_user_data() -> dict:
    """Loads user data from a JSON file."""
    try:
        with open(USER_DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_user_data(data: dict):
    """Saves user data to a JSON file."""
    with open(USER_DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)


def resolve_address(chat_id: int, alias_or_address: str) -> str:
    """Resolves an alias to a Solana address if it exists for the user."""
    data = load_user_data()
    user_aliases = data.get(str(chat_id), {}).get("aliases", {})
    return user_aliases.get(alias_or_address, alias_or_address)


def get_rpc_url(chat_id: int) -> str:
    """Gets the custom RPC URL for a chat, or the default if not set."""
    data = load_user_data()
    return data.get(str(chat_id), {}).get("rpc_url", DEFAULT_RPC_URL)
