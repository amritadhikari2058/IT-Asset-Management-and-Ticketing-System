p = "common/tests.py"
s = open(p).read()
start = s.index("class TicketNotificationTransactionTests(TestCase):")
import re
m = re.search(r"\nclass ", s[start+1:])
if m:
    end = start + 1 + m.start()
else:
    # find @override_settings(**LOC)\nclass TicketEmailPreferenceTests after start
    idx = s.find("@override_settings(**LOC)\nclass TicketEmailPreferenceTests", start)
    end = idx if idx != -1 else len(s)
print("start", start, "end", end, "len", end - start)
print("FIRST 200:", repr(s[start:start+200]))
print("LAST 100:", repr(s[end-100:end]))