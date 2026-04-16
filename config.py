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
CLAUDE_MODEL_SMART = "claude-opus-4-6"      # coaching, conversations — smart
CLAUDE_MODEL_FAST = "claude-sonnet-4-6"     # food analysis, activity — fast & cheap
