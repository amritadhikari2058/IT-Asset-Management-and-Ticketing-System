import importlib.util
import sys

# Load shared.py directly
spec = importlib.util.spec_from_file_location("shared", r"D:\IT-Asset-Management-and-Ticketing-System\backend\assets\views\shared.py")
shared = importlib.util.module_from_spec(spec)
spec.loader.exec_module(shared)

print("Has _asset_visible_qs:", hasattr(shared, '_asset_visible_qs'))
if hasattr(shared, '_asset_visible_qs'):
    print("It is callable:", callable(shared._asset_visible_qs))
    # Try calling it with a dummy user
    try:
        result = shared._asset_visible_qs(None)
        print("Result with None:", result)
    except Exception as e:
        print("Error calling:", e)