p = "common/tests.py"
s = open(p).read()

# Replace all test_inbound_message_created_after_commit ... test_notify_user_rolled_back_with_transaction blocks
created_marker = "    def test_notify_user_created_after_commit(self):"
rolled_back_marker = "    def test_notify_user_rolled_back_with_transaction(self):"

# Find all start positions
created_positions = []
idx = 0
while True:
    idx = s.find(created_marker, idx)
    if idx == -1:
        break
    created_positions.append(idx)
    idx += 1

rolled_positions = [m.start() for m in re.finditer(r"    def test_notify_user_rolled_back_with_transaction\(self):", s)]

print("Created positions:", created_positions)
print("Rolled back positions:", rolled_back_positions)

# Pair each created with the next rolled_back
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

# Replace from end to start to preserve positions
for start, end in sorted(zip(created_positions, rolled_back_positions), reverse=True):
    s = s[:start] + new_created + s[end:]

open(p, "w").write(s)
print("done")
print("test_notify_user_created_after_commit count:", s.count("def test_notify_user_created_after_commit(self):"))