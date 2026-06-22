import time
import requests

url = "https://bit-ia-nuevo.onrender.com/api/bot/adjust_sl_20"

for _ in range(15):
    try:
        response = requests.post(url, timeout=10)
        if response.status_code == 200:
            print("Successfully hit the SL adjustment endpoint.")
            print(response.json())
            break
        else:
            print(f"Failed with status: {response.status_code}")
    except Exception as e:
        print(f"Waiting for deployment... {e}")
    time.sleep(10)
