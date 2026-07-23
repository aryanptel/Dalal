import os
import sys
import shutil
from pathlib import Path

APP_NAME = "Dalal AI"
DOCUMENTS_FOLDER = "Documents"

def is_frozen() -> bool:
    """Check if the application is running as a PyInstaller bundle."""
    return getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS')

def get_bundle_dir() -> str:
    """Return the base directory of the bundled files or the project root."""
    if is_frozen():
        return sys._MEIPASS
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def get_user_data_dir() -> str:
    """Return the path to the user's Documents/Dalal AI folder. Create it if necessary."""
    home = str(Path.home())
    user_dir = os.path.join(home, DOCUMENTS_FOLDER, APP_NAME)
    os.makedirs(user_dir, exist_ok=True)
    return user_dir

def get_logs_dir() -> str:
    """Return the path to the logs directory inside user data."""
    logs_dir = os.path.join(get_user_data_dir(), "logs")
    os.makedirs(logs_dir, exist_ok=True)
    return logs_dir

def get_config_path() -> str:
    """Return the path to the user's config.yaml file."""
    return os.path.join(get_user_data_dir(), "config.yaml")

def get_history_path() -> str:
    """Return the path to the user's chat_history.json file."""
    return os.path.join(get_user_data_dir(), "chat_history.json")

def init_user_data() -> None:
    """Initialize user data by copying default config if it doesn't exist."""
    user_config = get_config_path()
    if not os.path.exists(user_config):
        bundled_config = os.path.join(get_bundle_dir(), "config.yaml")
        if os.path.exists(bundled_config):
            shutil.copy2(bundled_config, user_config)
            print(f"Copied default config to {user_config}")
        else:
            print(f"Warning: Default config not found at {bundled_config}")
