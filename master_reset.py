import asyncio
import os
import time
from app.exchange.bingx_client import AsyncBingXClient
from app.exchange.order_executor import OrderExecutionEngine
from app.database.crud import clear_all_data

async def do_reset():
    print("--- 1. LIMPIANDO BASE DE DATOS (HISTORIAL INTERNO, WINRATE, ETC) ---")
    await clear_all_data()
    print("Base de Datos (app.db) borrada y recreada desde cero.")

    print("--- 2. BORRANDO ARCHIVOS DE HISTORIAL EXTERNO ---")
    files_to_delete = [
        "storage/recent_income.json",
        "storage/pnl_offset.json",
        "storage/trades.db"
    ]
    for f in files_to_delete:
        if os.path.exists(f):
            os.remove(f)
            print(f"Eliminado: {f}")

    print("--- 3. RESETEANDO PUNTO DE PARTIDA DE GANANCIAS ---")
    os.makedirs("storage", exist_ok=True)
    with open("storage/pnl_start_time.txt", "w") as f:
        f.write(str(int(time.time() * 1000)))
    print("Punto de partida de PNL reiniciado. El Dashboard empezará en $0.00.")

    print("--- 4. CERRANDO OPERACIONES Y ÓRDENES EN BINGX ---")
    client = AsyncBingXClient()
    executor = OrderExecutionEngine(client)
    
    positions = await client.get_positions()
    for pos in positions:
        amt = float(pos.get("positionAmt", 0))
        if abs(amt) > 0:
            sym = pos.get("symbol")
            side = "LONG" if amt > 0 else "SHORT"
            print(f"Cerrando posición a mercado: {sym} {side} ({abs(amt)})...")
            await executor.close_position_market(sym, side, abs(amt))
            await client.cancel_all_orders(sym)
            
    # Intentar cancelar órdenes colgadas huérfanas
    await client._request("DELETE", "/openApi/swap/v2/trade/allOpenOrders", signed=True)
    print("Todas las órdenes pendientes eliminadas.")

    print("\n[OK] RESET TOTAL COMPLETADO CON ÉXITO.")

if __name__ == "__main__":
    asyncio.run(do_reset())
