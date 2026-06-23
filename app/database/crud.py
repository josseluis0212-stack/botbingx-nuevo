from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import select, delete
from app.database.models import Base, TradeState, TradeHistory, SymbolCooldown
import datetime
import os
import uuid

DB_URL = "sqlite+aiosqlite:///app.db"
engine = create_async_engine(DB_URL, echo=False)
async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

async def init_db():
    async with engine.begin() as conn:
        # For an architectural reset, we recreate the tables if schema changes.
        # SQLite doesn't do ALTER TABLE easily, so we rely on clear_all_data() if needed.
        await conn.run_sync(Base.metadata.create_all)
        try:
            from sqlalchemy import text
            await conn.execute(text("ALTER TABLE trade_state ADD COLUMN strategy VARCHAR DEFAULT 'SMC_PRO'"))
        except:
            pass
            
        try:
            from sqlalchemy import text
            await conn.execute(text("ALTER TABLE trade_state ADD COLUMN structural_lock_sl_price FLOAT DEFAULT NULL"))
            await conn.execute(text("ALTER TABLE trade_state ADD COLUMN structural_trailing_dist_atr FLOAT DEFAULT NULL"))
        except:
            pass

class TradeStateRepository:
    """Handles persistence of open position states safely and robustly."""
    
    @staticmethod
    async def get_all_active_trades() -> list[TradeState]:
        async with async_session() as session:
            result = await session.execute(select(TradeState).where(TradeState.position_closed == False))
            return result.scalars().all()

    @staticmethod
    async def get_trade(symbol: str) -> TradeState:
        async with async_session() as session:
            result = await session.execute(select(TradeState).where(TradeState.symbol == symbol, TradeState.position_closed == False))
            return result.scalars().first()

    @staticmethod
    async def get_trade_by_id(trade_id: str) -> TradeState:
        async with async_session() as session:
            result = await session.execute(select(TradeState).where(TradeState.trade_id == trade_id))
            return result.scalars().first()

    @staticmethod
    async def save_trade(trade: TradeState):
        async with async_session() as session:
            if not trade.trade_id:
                trade.trade_id = str(uuid.uuid4())
            await session.merge(trade)
            await session.commit()

    @staticmethod
    async def mark_position_closed(symbol: str):
        async with async_session() as session:
            trade = await session.execute(select(TradeState).where(TradeState.symbol == symbol, TradeState.position_closed == False))
            trade = trade.scalars().first()
            if trade:
                trade.position_closed = True
                await session.commit()

async def add_history(symbol: str, side: str, entry_price: float, exit_price: float, pnl: float):
    async with async_session() as session:
        history = TradeHistory(symbol=symbol, side=side, entry_price=entry_price, exit_price=exit_price, pnl=pnl)
        session.add(history)
        await session.commit()

async def set_cooldown(symbol: str, minutes: int):
    async with async_session() as session:
        cooldown_until = datetime.datetime.utcnow() + datetime.timedelta(minutes=minutes)
        existing = await session.execute(select(SymbolCooldown).where(SymbolCooldown.symbol == symbol))
        existing = existing.scalars().first()
        if existing:
            await session.delete(existing)
        new_cooldown = SymbolCooldown(symbol=symbol, cooldown_until=cooldown_until)
        session.add(new_cooldown)
        await session.commit()

async def is_on_cooldown(symbol: str) -> bool:
    async with async_session() as session:
        result = await session.execute(select(SymbolCooldown).where(SymbolCooldown.symbol == symbol))
        cooldown = result.scalars().first()
        if cooldown:
            if datetime.datetime.utcnow() < cooldown.cooldown_until:
                return True
            else:
                await session.delete(cooldown)
                await session.commit()
        return False

async def clear_all_data():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
