#!/usr/bin/env python3
with open('D:\\IT-Asset-Management-and-Ticketing-System\\frontend\\src\\App.jsx', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Look for the line that closes the cmdb routes block and add service routes after it
for i, line in enumerate(lines[330:350], start=331):
    print(f"Line {i}: {lines[i].rstrip()}")