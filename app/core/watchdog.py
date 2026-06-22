import asyncio
import time
from app.logger import logger

class Watchdog:
    """
    Monitors the engine and WebSocket for signs of life.
    Restarts modules if they appear frozen or dead.
    """

    def __init__(self, engine):
        self.engine = engine
        self.running = False
        self._check_interval = 60  # seconds

    async def start(self):
        self.running = True
        logger.info("[WATCHDOG] Started.")
        await self._monitor()

    async def _monitor(self):
        while self.running:
            await asyncio.sleep(self._check_interval)
            try:
                # Check WebSocket health
                if not self.engine.ws.running:
                    logger.error("[WATCHDOG] WebSocket is NOT running! Triggering reconnect...")
                    self.engine.ws.running = True
                    asyncio.create_task(self.engine.ws.connect())

                # Check engine is still running
                if not self.engine.running:
                    logger.error("[WATCHDOG] Engine appears stopped! Restarting...")
                    asyncio.create_task(self.engine.start())

                logger.debug(f"[WATCHDOG] Heartbeat OK | Open trades: {len([s for s, t in self.engine.trade_state.items() if t.get('entry_order_id')])}")

            except Exception as e:
                logger.error(f"[WATCHDOG] Error during monitor: {e}")

    async def stop(self):
        self.running = False
        logger.info("[WATCHDOG] Stopped.")