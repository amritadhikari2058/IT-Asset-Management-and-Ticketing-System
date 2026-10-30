import subprocess, sys

mods = ["assets", "accounts", "common"]
r = subprocess.run(["python", "manage.py", "test", *mods], cwd="D:\\IT-Asset-Management-and-Ticketing-System\\backend", capture_output=True, text=True, timeout=3000)
sys.stdout.write(r.stdout[-6000:] + "\n")
sys.stdout.write(r.stderr[-3000:] + "\n")
sys.stdout.write(f"EXIT {r.returncode}\n")

