import os
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
# Use persistent volume if mounted, otherwise local file
if os.path.isdir("/data"):
    _default_db = "/data/coach.db"
else:
    _default_db = "coach.db"
DB_PATH = os.environ.get("DB_PATH", _default_db)
CLAUDE_MODEL = "claude-sonnet-4-6"
