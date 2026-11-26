with open('backend/assets/reports.py', 'r') as f:
    lines = f.readlines()

# Find line with s=Sum and replace the next 2 lines with aggregate wrapper
for i in range(len(lines) - 1):
    if 's=Sum("purchase_cost", output_field=None)' in lines[i]:
        # Replace lines i and i+1 with the aggregate wrapper
        new_lines = [
            '    assets.aggregate(\n',
            '        s=Sum("purchase_cost", output_field=None)\n',
            ')["s"]\n'
        ]
        lines[i:i+2] = new_lines
        break

with open('backend/assets/reports.py', 'w') as f:
    f.writelines(lines)
print("Fixed the aggregate call")