paths = [
    r"D:\IT-Asset-Management-and-Ticketing-System\backend\accounts\tests.py",
    r"D:\IT-Asset-Management-and-Ticketing-System\backend\assets\tests.py",
    r"D:\IT-Asset-Management-and-Ticketing-System\backend\tickets\tests.py",
]
needles = [
    "Asset.objects.create(",
    "Asset.objects.get_or_create(",
]
for p in paths:
    text = open(p, encoding="utf-8").read()
    print("=====", p, "len", len(text))
    for i, line in enumerate(text.splitlines(), 1):
        if any(n in line for n in needles) and "def " not in line and "class " not in line:
            print(f"{i}: {line}")

