with open('backend/assets/reports.py', 'r') as f:
    content = f.read()

content = content.replace(
    '            s=Sum("purchase_cost", output_field=None)',
    '    s=Sum("purchase_cost", output_field=None)'
)
with open('backend/assets/reports.py', 'w') as f:
    f.write(content)
print("Fixed")