import asyncio
import sys

# Adjust path to import from app
sys.path.append(".")

from app.core.engine import Engine

async def run():
    engine = Engine()
    try:
        await engine.reset_state()
        print("RESET SUCCESSFUL LOCALLY!")
    except Exception as e:
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(run())
