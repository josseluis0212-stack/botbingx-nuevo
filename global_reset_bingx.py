import os
import time
import requests
import hmac
import hashlib

API_KEY = "83SwzN3Rf9FjsfzswrACVH5fL4VSoLaxATw8EUVwbmQH0dmw3676Sv3Pch4mqTtDrMka97GqCKJQC4KjttcFPQ"
SECRET_KEY = "7JkN8wZ9sj2Zt7VNGdk4ovCMPQ5jm9dIZXX324M7UlWcNFyn0amE4sOeJLRqh0sq8DL2xgYNLCfdNDJKJg"
BASE_URL = "https://open-api.bingx.com"

def get_sign(api_secret, payload):
    signature = hmac.new(api_secret.encode("utf-8"), payload.encode("utf-8"), digestmod=hashlib.sha256).hexdigest()
    return signature

def _request(method, path, params=None):
    if params is None:
        params = {}
    params["timestamp"] = int(time.time() * 1000)
    query_string = "&".join([f"{k}={v}" for k, v in sorted(params.items())])
    signature = get_sign(SECRET_KEY, query_string)
    url = f"{BASE_URL}{path}?{query_string}&signature={signature}"
    headers = {"X-BX-APIKEY": API_KEY}
    
    if method == "GET":
        res = requests.get(url, headers=headers)
    elif method == "POST":
        res = requests.post(url, headers=headers)
    elif method == "DELETE":
        res = requests.delete(url, headers=headers)
    
    try:
        return res.json()
    except:
        return {"code": -1, "msg": res.text}

def reset_all():
    print("--- FETCHING POSITIONS ---")
    positions_data = _request("GET", "/openApi/swap/v2/user/positions", {})
    if positions_data.get("code") == 0:
        positions = positions_data.get("data", [])
        for p in positions:
            symbol = p.get("symbol")
            size = float(p.get("available", 0))
            if size > 0:
                print(f"Cerrando posición {symbol}...")
                _request("POST", "/openApi/swap/v2/trade/closeAllPositions", {"symbol": symbol})
    else:
        print("Error fetching positions:", positions_data)
        
    print("--- CANCELLING ALL ORDERS ---")
    res = _request("DELETE", "/openApi/swap/v2/trade/allOpenOrders", {})
    print("Orders cancelled:", res)
    
    print("--- WIPING LOCAL DB ---")
    files_to_delete = [
        "app/database/trading.db",
        "storage/trades.json",
        "storage/positions.json",
        "storage/bot.log"
    ]
    for f in files_to_delete:
        if os.path.exists(f):
            os.remove(f)
            print(f"Deleted {f}")
            
    print("ALL DONE. DASHBOARD WILL START AT 0.")

if __name__ == "__main__":
    reset_all()
