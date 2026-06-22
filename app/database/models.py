from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime
from sqlalchemy.orm import declarative_base
import datetime

Base = declarative_base()

class TradeState(Base):
    __tablename__ = 'trade_state'
    
    trade_id = Column(String, primary_key=True)
    symbol = Column(String, nullable=False)
    side = Column(String, nullable=False)
    entry_price = Column(Float, nullable=False)
    position_size = Column(Float, nullable=False)
    atr = Column(Float, nullable=False)
    stop_loss = Column(Float, nullable=False)
    tp1_price = Column(Float, nullable=False)
    tp2_price = Column(Float, nullable=False)
    profit_lock_price = Column(Float, nullable=False)
    highest_price = Column(Float, nullable=True)
    lowest_price = Column(Float, nullable=True)
    remaining_size = Column(Float, nullable=False)
    strategy = Column(String, default="SMC_PRO")
    
    tp1_filled = Column(Boolean, default=False)
    tp2_filled = Column(Boolean, default=False)
    profit_lock_active = Column(Boolean, default=False)
    trailing_active = Column(Boolean, default=False)
    position_closed = Column(Boolean, default=False)
    
    # Internal exchange order tracking
    entry_order_id = Column(String, nullable=True)
    sl_order_id = Column(String, nullable=True)
    
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

class TradeHistory(Base):
    __tablename__ = 'trade_history'
    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String)
    side = Column(String)
    entry_price = Column(Float)
    exit_price = Column(Float)
    pnl = Column(Float)
    closed_at = Column(DateTime, default=datetime.datetime.utcnow)

class SymbolCooldown(Base):
    __tablename__ = 'symbol_cooldown'
    symbol = Column(String, primary_key=True)
    cooldown_until = Column(DateTime)
