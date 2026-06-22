import aiohttp
from app.config import Config
from app.logger import logger

class DiscordNotifier:
    """
    Notificador Oficial para webhooks de Discord.
    Reporta ENTRADA, TP1, LOCK, TP2, TRAILING, CIERRE, y ERRORES.
    """
    
    def __init__(self):
        # Asumiendo que el usuario pondrá DISCORD_WEBHOOK_URL en .env o usará el de telegram
        self.webhook_url = getattr(Config, "DISCORD_WEBHOOK_URL", None)

    async def send_message(self, title: str, message: str, color: int = 3447003):
        if not self.webhook_url:
            return

        payload = {
            "embeds": [
                {
                    "title": title,
                    "description": message,
                    "color": color
                }
            ]
        }
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(self.webhook_url, json=payload) as response:
                    if response.status not in [200, 204]:
                        logger.warning(f"[DISCORD] Failed to send message, status: {response.status}")
        except Exception as e:
            logger.error(f"[DISCORD] Exception sending webhook: {e}")

    async def notify_entry(self, symbol: str, side: str, price: float, size: float):
        await self.send_message(
            f"🚀 [ENTRADA] {symbol} {side}",
            f"Precio: {price}\nTamaño: {size}",
            color=3066993 if side == "LONG" else 15158332
        )

    async def notify_tp1(self, symbol: str):
        await self.send_message(f"✅ [TP1] {symbol}", "30% Cerrado.", color=3066993)

    async def notify_lock(self, symbol: str):
        await self.send_message(f"🔒 [LOCK] {symbol}", "Protección al 40% activada. SL movido.", color=15105570)

    async def notify_tp2(self, symbol: str):
        await self.send_message(f"✅ [TP2] {symbol}", "30% Cerrado. Activando Trailing Stop.", color=3066993)

    async def notify_trailing_hit(self, symbol: str):
        await self.send_message(f"🏁 [TRAILING HIT] {symbol}", "Trailing Stop tocado. Operación finalizada.", color=10181046)

    async def notify_error(self, message: str):
        await self.send_message("❌ [ERROR DEL SISTEMA]", message, color=15158332)

discord_notifier = DiscordNotifier()
