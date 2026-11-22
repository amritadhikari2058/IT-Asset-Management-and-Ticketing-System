p = "common/tests.py"
s = open(p).read()
import re
# Find all test_notify_user_created_after_commit method bodies
for m in re.finditer(r"    def test_notify_user_created_after_commit\(self\):.*?(?=\n    def test_notify_user_rolled_back_with_transaction\(self):", s, re.DOTALL):
    print("FOUND test_notify_user_created_after_commit at", m.start())
    print(repr(s[m.start():m.end()][:200]))
    print("---")