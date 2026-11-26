with open('backend/assets/reports.py', 'r') as f:
    lines = f.readlines()

# Fix line 91 (1-indexed) which is the s=Sum line - needs 4-space indent
# Line numbers: 89 = total_assets, 90 = blank, 91 = s=Sum, 92 = )["s"]
for i in range(len(lines)):
    if i < len(lines) and 's=Sum("purchase_cost", output_field=None)' in lines[i]:
        # This line needs 4-space indentation
        lines[i] = '    ' + lines[i]
        break

with open('backend/assets/reports.py', 'w') as f:
    f.writelines(lines)
print("Fixed indentation")