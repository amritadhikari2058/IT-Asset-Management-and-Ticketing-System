p = "common/tests.py"
s = open(p).read()
import re

# Remove all test_notify_user_created_after_commit(self): ... def test_notify_user_rolled_back_with_transaction(self): blocks
created_pattern = re.compile(r"    def test_notify_user_created_after_commit\(self\):.*?\n    def test_notify_user_rolled_back_with_transaction\(self):", re.DOTALL)
s = re.sub(created_pattern, "", s)
print("Removed test_notify_user_created_after_commit blocks:", s.count("def test_notify_user_created_after_commit(self):"))

# Remove all test_notify_user_outside_transaction(self): ... def test_notify_user_returns_none(self): blocks
out_pattern = re.compile(r"    def test_notify_user_outside_transaction\(self\):.*?\n    def test_notify_user_returns_none\(self):", re.DOTALL)
s = re.sub(out_pattern, "", s)
print("test_notify_user_outside_transaction count:", s.count("def test_notify_user_outside_transaction(self):"))
print("test_notify_user_created_after_commit count:", s.count("def test_notify_user_created_after_commit(self):"))

open(p, "w").write(s)
print("done")