p = "common/tests.py"
s = open(p).read()
import re
# Find all class TicketNotificationTransactionTests(TestCase): occurrences
class_starts = [m.start() for m in re.finditer(r"class TicketNotificationTransactionTests\(TestCase\):", s)]
print("class TicketNotificationTransactionTests at:", class_starts)
# Find the last test_notify_user_skips_invalid_recipients method end
last_idx = s.rindex("    def test_notify_user_skips_invalid_recipients(self):")
# Find end of that method: next "    def " or "\n@override_settings" or "\nclass " after last_idx
tail = s[last_idx:]
m1 = re.search(r"\n    def ", tail[1:])
m2 = re.search(r"\n@override_settings", tail)
m3 = re.search(r"\nclass ", tail[1:])
candidates = [m1.start()+1 if m1 else len(tail)+1, m2.start()+1 if m2 else len(tail)+1, m3.start()+1 if m3 else len(tail)+1]
end = last_idx + 1 + min(candidates)
print("last test_notify_user_skips_invalid_recipients at", last_idx, "end at", end)
print("first class at", class_starts[0])
print("span:", start, "to", end, "len", end-start)
print("FIRST 150:", repr(s[start:start+150]))
print("LAST 100:", repr(s[end-100:end]))