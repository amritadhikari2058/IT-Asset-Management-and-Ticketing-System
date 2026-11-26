with open('backend/assets/reports.py', 'r') as f:
    lines = f.readlines()

# Fix lines 91-93 (aggregate wrapper) to have proper indentation
# Current: 
# line 91: '            s=Sum(...')
# line 92: '            )["s"]'
# Need to change to 4-space indent

# Find and replace the aggregate block
for i in range(len(lines)):
    if 'assets.aggregate(' in lines[i]:
        # Replace this line and the next 2 lines
        indent = '    '
        lines[i] = indent + 'assets.aggregate(\n'
        lines[i+1] = indent + '    s=Sum("purchase_cost", output_field=None)\n'
        lines[i+2] = indent + ')["s"]\n'
        break

with open('backend/assets/reports.py', 'w') as f:
    f.writelines(lines)
print("Fixed aggregate indentation")