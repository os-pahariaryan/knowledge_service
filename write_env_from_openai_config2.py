import json
from pathlib import Path

config_path = Path(".openai_config.json")
env_path = Path(".env")

if not config_path.exists():
    raise FileNotFoundError(".openai_config.json not found")

data = json.loads(config_path.read_text())

# Your file uses "api_key"
api_key = data.get("api_key")

if not api_key:
    raise ValueError("No 'api_key' field found in .openai_config.json")

env_path.write_text(f"OPENAI_API_KEY={api_key}\n")
print("Wrote OPENAI_API_KEY to .env")

