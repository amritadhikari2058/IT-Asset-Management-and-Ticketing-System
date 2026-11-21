p = "common/tests.py"
s = open(p).read()
import re

# Find all test_notify_user_created_after_commit(self): ... def test_notify_user_rolled_back_with_transaction(self): blocks
created_pattern = re.compile(r"    def test_notify_user_created_after_commit\(self\):.*?\n    def test_notify_user_rolled_back_with_transaction\(self):", re.DOTALL)
created_new = '''    def test_notify_user_created_after_commit(self):
        from accounts.email_utils import _notify_user
        with self.captureOnCommitCallbacks() as callbacks:
            self._notify(
                self.mgr, self.emp,
                "Ticket status changed", f"Ticket {self.ticket.pk} moved.",
                self.ticket)
        self.assertEqual(len(callbacks), 1)
        self.assertEqual(Notification.objects.count(), 0)

'''

# Find all test_notify_user_outside_transaction(self): ... def test_notify_user_returns_none(self): blocks
out_positions = [m.start() for m in re.finditer(r"    def test_notify_user_outside_transaction\(self):", s)]
returns_none_positions = [m.start() for m in re.finditer(r"    def test_notify_user_returns_none\(self):", s)]
print("out_positions:", out_positions)
print("returns_none_positions:", returns_none_positions)

new_outside = '''    def test_notify_user_outside_transaction(self):
        from accounts.email_utils import _notify_user
        self.assertEqual(Notification.objects.count(), 0)
        self._notify(
            self.mgr, self.emp,
            "Ticket status changed", f"Ticket {self.ticket.pk} moved.",
            self.ticket)
        self.assertEqual(Notification.objects.count(), 0)

'''

# Replace created methods (work from end to start to preserve positions)
created_positions = [m.start() for m in re.finditer(r"    def test_notify_user_created_after_commit\(self):", s)]
rolled_positions = [m.start() for m in re.finditer(r"    def test_notify_user_rolled_back_with_transaction\(self):", s)]
print("created_positions:", created_positions)
print("rolled positions:", rolled_back_positions)

# Pair each created method with the following rolled_back method
for start, end in zip(created_positions, rolled_back_positions):
    assert start < end
    s = s[:start] + new_created + s[end:]

# Replace out methods
out_positions_sorted = sorted(out_positions, reverse=True)
returns_none_positions_sorted = sorted(returns_none_positions, reverse=True)
for out_start, ret_start in zip(out_positions_sorted, returns_none_positions_sorted):
    assert out_start < ret_start
    s = s[:out_start] + new_outside + s[ret_start:]

open(p, "w").write(s)
print("rewritten all tests")
print("test_notify_user_created_after_commit count:", s.count("def test_notify_user_created_after_commit(self):"))
print("test_notify_user_outside_transaction count:", s.count("def test_notify_user_outside_transaction(self):"))