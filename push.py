import os
import time
import subprocess

for i in range(5):
    print(f"Attempt {i+1}...")
    result = subprocess.run(["git", "push", "origin", "main"], capture_output=True, text=True)
    if result.returncode == 0:
        print("Push successful!")
        break
    else:
        print(f"Failed: {result.stderr}")
        time.sleep(5)
