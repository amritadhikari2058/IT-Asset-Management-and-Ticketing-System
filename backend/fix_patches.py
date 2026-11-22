import re

with open('D:/IT-Asset-Management-and-Ticketing-System/backend/common/test_scheduled_report_delivery.py', 'r') as f:
    content = f.read()

old = '@patch("common.tasks._email_utils.send_scheduled_report_email")'
new = '@patch("accounts.email_utils.send_scheduled_report_email")'

content = content.replace(old, new)

with open('D:/IT-Asset-Management-and-Ticketing-System/backend/common/test_scheduled_report_delivery.py', 'w') as f:
    f.write(content)

print('Done')