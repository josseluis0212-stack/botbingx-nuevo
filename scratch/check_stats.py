import urllib.request
import json

def verify():
    hf_url = "https://luisalbertor-botbingx.hf.space"
    
    # 1. Verify stats
    try:
        req = urllib.request.Request(f"{hf_url}/api/stats", headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req) as response:
            data = json.loads(response.read().decode('utf-8'))
            print("STATS FROM HF SPACE:")
            print(json.dumps(data, indent=2))
    except Exception as e:
        print(f"Error checking stats: {e}")
        
    # 2. Verify dashboard (positions)
    try:
        req = urllib.request.Request(f"{hf_url}/api/dashboard", headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req) as response:
            data = json.loads(response.read().decode('utf-8'))
            print("\nDASHBOARD FROM HF SPACE:")
            print(json.dumps(data, indent=2))
    except Exception as e:
        print(f"Error checking dashboard: {e}")

if __name__ == "__main__":
    verify()
