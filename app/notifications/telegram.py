import asyncio
import httpx
from app.config import Config
from app.logger import logger

class TelegramNotifier:
    BASE_URL = "https://api.telegram.org"

    def __init__(self):
        self.token = Config.TELEGRAM_TOKEN
        self.chat_id = Config.TELEGRAM_CHAT_ID
        self.enabled = Config.USE_TELEGRAM and bool(self.token) and bool(self.chat_id)

    async def send_message(self, text: str):
        if not self.enabled:
            return
            
        url = f"{self.BASE_URL}/bot{self.token}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": "HTML"
        }
        
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(url, json=payload)
                response.raise_for_status()
        except Exception as e:
            logger.error(f"[Telegram] Error enviando mensaje: {e}")

    async def notify_open(self, symbol: str, side: str, entry_price: float, qty: float, strategy: str = "", trade: dict = None):
        icon = "🟢" if side.lower() == "long" else "🔴"
        strat_str = f"🧠 <b>Estrategia:</b> <code>{strategy}</code>\n" if strategy else ""
        
        sl_str = ""
        tp_str = ""
        risk_str = ""
        
        if trade:
            sl = trade.get("sl_price")
            if sl:
                risk_usdt = abs(entry_price - sl) * qty
                risk_str = f"⚠️ <b>Riesgo (Stop Loss):</b> <code>-${risk_usdt:.2f} USDT</code>\n"
                sl_str = f"🛡️ <b>Stop Loss:</b> <code>{sl:.6f}</code>\n"
            
            tps = trade.get("tps", [])
            if tps and len(tps) > 0:
                tp1_price = tps[0].get('price', 0)
                tp1_profit = abs(tp1_price - entry_price) * (qty * 0.5)
                tp_str = f"🎯 <b>TP1 (50%):</b> <code>{tp1_price:.6f}</code> <i>(+${tp1_profit:.2f})</i>\n"
                
                if len(tps) > 1:
                    tp2_price = tps[1].get('price', 0)
                    tp2_profit = abs(tp2_price - entry_price) * (qty * 0.5)
                    tp_str += f"🚀 <b>TP2 (50%):</b> <code>{tp2_price:.6f}</code> <i>(+${tp2_profit:.2f})</i>\n"
                
        text = (
            f"{icon} <b>NUEVA OPERACIÓN {side.upper()}</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"🪙 <b>Par:</b> #{symbol.replace('-', '')}\n"
            f"💰 <b>Entrada:</b> <code>{entry_price:.6f}</code>\n"
            f"⚖️ <b>Tamaño (Monedas):</b> <code>{qty}</code>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"{sl_str}{tp_str}{risk_str}{strat_str}"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"🤖 <i>Terminal Institucional SMC - BingX</i>"
        )
        
        await self.send_message(text)

    async def notify_close(self, symbol: str, side: str, pnl: float = 0.0, reason: str = "Cierre"):
        is_profit = pnl > 0
        icon = "✅" if is_profit else ("📉" if pnl < 0 else "⚖️")
        sign = "+" if is_profit else ""
        
        reason_icon = "🏁"
        if "TP" in reason: reason_icon = "🎯"
        elif "SL" in reason: reason_icon = "🛑"
        elif "BREAKEVEN" in reason: reason_icon = "🛡️"
        elif "TRAILING" in reason: reason_icon = "🏄‍♂️"
        
        text = (
            f"{icon} <b>CIERRE {side.upper()}</b>\n"
            f"─────────────────\n"
            f"🪙 <b>Par:</b> #{symbol.replace('-', '')}\n"
            f"{reason_icon} <b>Razón:</b> <code>{reason}</code>\n"
            f"💵 <b>PNL Neto:</b> <b>{sign}{pnl:.4f} USDT</b>\n"
            f"─────────────────"
        )
        await self.send_message(text)

notifier = TelegramNotifier()
