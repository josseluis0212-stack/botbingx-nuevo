import asyncio
from app.exchange.websocket_client import BingXWebSocket
import sys

received_data = []

async def callback(data):
    print("Received data:", data)
    received_data.append(data)

async def main():
    ws_client = BingXWebSocket(message_callback=callback)
    
    # Run connect() in the background
    connect_task = asyncio.create_task(ws_client.connect())
    
    print("Waiting for 10 seconds to collect data...")
    await asyncio.sleep(10)
    
    # Stop the client
    await ws_client.stop()
    connect_task.cancel()
    
    # Check what we received
    if received_data:
        print(f"\nSUCCESS: Received {len(received_data)} messages from WebSocket.")
    else:
        print("\nFAILURE: No messages received from WebSocket.")

if __name__ == "__main__":
    asyncio.run(main())
