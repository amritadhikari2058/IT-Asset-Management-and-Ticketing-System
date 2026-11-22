import re

with open('D:/IT-Asset-Management-and-Ticketing-System/backend/common/test_scheduled_report_delivery.py', 'r') as f:
    content = f.read()

# Fix test_mixed_outcomes_independent_per_recipient - update send_side_effect
# to return None for pending recipient (meaning SMTP not attempted, status stays pending)
old_send = '''def send_side_effect(to_email, *args, **kwargs):
            # First recipient succeeds, second fails, third would be pending.
            return to_email == "success@example.com"'''

new_send = '''def send_side_effect(to_email, *args, **kwargs):
            # First recipient succeeds, second fails, third would be pending.
            if to_email == "success@example.com":
                return True
            elif to_email == "fail@example.com":
                return False
            # pending@example.com: SMTP not attempted, status stays pending
            return None'''

content = content.replace(old_send, new_send)

with open('D:/IT-Asset-Management-and-Ticketing-System/backend/common/test_scheduled_report_delivery.py', 'w') as f:
    f.write(content)

print("Fixed test_mixed_outcomes")