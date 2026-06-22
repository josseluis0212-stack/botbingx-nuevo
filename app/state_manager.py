import json
import os
import asyncio
from app.constants import RUNTIME_STATE_FILE, POSITIONS_FILE, TRADES_FILE
from app.logger import logger

class StateManager:
    _lock = asyncio.Lock()

    @classmethod
    async def load(cls, file_path, default=None):
        if default is None:
            default = {}
        if not os.path.exists(file_path):
            return default
        async with cls._lock:
            try:
                with open(file_path, "r") as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Error loading {file_path}: {e}")
                return default

    @classmethod
    async def save(cls, file_path, data):
        async with cls._lock:
            try:
                with open(file_path, "w") as f:
                    json.dump(data, f, indent=4)
            except Exception as e:
                logger.error(f"Error saving {file_path}: {e}")