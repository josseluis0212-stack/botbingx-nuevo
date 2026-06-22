import time
import requests

url = "https://bit-ia-nuevo.onrender.com/api/bot/adjust_all_levels"

for _ in range(15):
    try:
        response = requests.post(url, timeout=15)
        if response.status_code == 200:
            print("Successfully hit the all-levels adjustment endpoint.")
            print(response.json())
            break
        else:
            print(f"Failed with status: {response.status_code}")
    except Exception as e:
        print(f"Waiting for deployment... {e}")
    time.sleep(10)
