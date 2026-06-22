import urllib.request
import json

import sys
sys.stdout.reconfigure(encoding='utf-8')

def get_logs():
    hf_url = "https://luisalbertor-botbingx.hf.space"
    try:
        req = urllib.request.Request(f"{hf_url}/api/logs", headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req) as response:
            data = json.loads(response.read().decode('utf-8'))
            print("HF SPACE LOGS:")
            for line in data.get("logs", []):
                print(line)
    except Exception as e:
        print(f"Error fetching logs: {e}")

if __name__ == "__main__":
    get_logs()
