p = "common/tests.py"
s = open(p).read()
# Replace each test_notify_user_created_after_commit method body
created_start = "    def test_notify_user_created_after_commit(self):"
created_end = "    def test_notify_user_rolled_back_with_transaction(self):"
# Find all occurrences of test_notify_user_created_after_commit method
import re
# Find all positions of test_notify_user_created_after_commit(self):
created_positions = [m.start() for m in re.finditer(r"    def test_notify_user_created_after_commit\(self):", s)]
rolled_back_positions = [m.start() for m in re.finditer(r"    def test_notify_user_rolled_back_with_transaction\(self):", s)]
print("test_notify_user_created_after_commit at:", created_positions)
print("test_notify_user_rolled_back_with_transaction at:", rolled_back_positions)
# Each created method is followed by rolled_back method
# Replace each created method body
new_created = '''    def test_notify_user_created_after_commit(self):
        from accounts.email_utils import _notify_user
        with self.captureOnCommitCallbacks() as callbacks:
            self._notify(
                self.mgr, self.emp,
                "Ticket status changed", f"Ticket {self.ticket.pk} moved.",
                self.ticket)
        self.assertEqual(len(callbacks), 1)
        self.assertEqual(Notification.objects.count(), 0)

'''
# Replace each test_notify_user_created_after_commit block
# Work from end to start to preserve positions
created_positions_sorted = sorted(created_positions, reverse=True)
for start in created_positions_sorted:
    end = s.index("    def test_notify_user_rolled_back_with_transaction(self):", start)
    s = s[:start] + new_created + s[end:]

# Replace each test_notify_user_outside_transaction(self): ... test_notify_user_returns_none(self):
out_positions = [m.start() for m in re.finditer(r"    def test_notify_user_outside_transaction\(self):", s)]
returns_none_positions = [m.start() for m in re.finditer(r"    def test_notify_user_returns_none\(self):", s)]
print("test_notify_user_outside_transaction at:", out_positions)
print("test_notify_user_returns_none at:", returns_none_positions)
new_outside = '''    def test_notify_user_outside_transaction(self):
        from accounts.email_utils import _notify_user
        self.assertEqual(Notification.objects.count(), 0)
        self._notify(
            self.mgr, self.emp,
            "Ticket status changed", f"Ticket {self.ticket.pk} moved.",
            self.ticket)
        self.assertEqual(Notification.objects.count(), 0)

'''
# Replace each out_position...returns_none block
out_positions_sorted = sorted(out_positions, reverse=True)
returns_none_positions_sorted = sorted(returns_none_positions, reverse=True)
for out_start, ret_start in zip(out_positions_sorted, returns_none_positions_sorted):
    s = s[:out_start] + new_outside + s[ret_start:]

open(p, "w").write(s)
print("done")