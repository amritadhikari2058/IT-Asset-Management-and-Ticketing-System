import os, re

backend = r'D:\IT-Asset-Management-and-Ticketing-System\backend'

# Search for select_for_update without of=('self',)
for root, dirs, files in os.walk(backend):
    if '__pycache__' in root or '.git' in root:
        continue
    for f in files:
        if f.endswith('.py'):
            filepath = os.path.join(root, f)
            try:
                with open(filepath, 'r', errors='replace') as fh:
                    content = fh.read()
                    lines = content.split('\n')
                    for i, line in enumerate(lines, 1):
                        # Check if line has select_for_update but not of=("self",)
                        stripped = line.strip()
                        if 'select_for_update' in stripped:
                            # Check if of=("self",) is on same line
                            if 'of=("self",)' not in stripped and "of=('self',)" not in stripped:
                                # Check it's not in a comment
                                code_part = stripped.split('#')[0].strip()
                                if 'select_for_update' in code_part:
                                    print(f'{filepath}:{i}: {stripped}')
            except:
                pass