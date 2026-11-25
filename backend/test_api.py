from urllib.request import urlopen
import json

try:
    r = urlopen('http://127.0.0.1:8000/api/assets/')
    data = r.read()
    print(r.status, json.loads(data)[:200] if data else '')
except Exception as e:
    print(f"Error: {e}")