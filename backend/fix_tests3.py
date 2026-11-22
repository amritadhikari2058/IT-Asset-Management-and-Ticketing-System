import re

with open('D:/IT-Asset-Management-and-Ticketing-System/backend/common/test_scheduled_report_delivery.py', 'r') as f:
    content = f.read()

# Fix the delivery loop to handle None (keep status as 'pending')
old_loop = '''ok = email_utils.send_scheduled_report_email(
                email, \"Subject\", \"Body\", \"file.csv\", b\"data\", \"text/csv\")
            if ok:\r\n                d.status = \"sent\"\r\n                d.sent_at = timezone.now()\r\n                d.save(update_fields=[\"status\", \"sent_at\", \"updated_at\"])\r\n            else:\r\n                d.status = \"failed\"\r\n                d.error_message = \"smtp_send_failed\"\r\n                d.save(update_fields=[\"status\", \"error_message\",\r\n                                      \"updated_at\"])\r\n            deliveries[email] = d'''

new_loop = '''ok = email_utils.send_scheduled_report_email(
                email, \"Subject\", \"Body\", \"file.csv\", b\"data\", \"text/csv\")
            if ok is True:
                d.status = \"sent\"\r\n                d.sent_at = timezone.now()\r\n                d.save(update_fields=[\"status\", \"sent_at\", \"updated_at\"])\n            elif ok is False:\r\n                d.status = \"failed\"\r\n                d.error_message = \"smtp_send_failed\"\r\n                d.save(update_fields=[\"status\", \"error_message\",\r\n                                      \"updated_at\"])\n            # ok is None: SMTP not attempted, status stays "pending"\n            deliveries[email] = d'''

content = content.replace(old_loop, new_loop)

with open('D:/IT-Asset-Management-and-Ticketing-System/backend/common/test_scheduled_report_delivery.py', 'w') as f:
    f.write(content)

print("Fixed delivery loop")