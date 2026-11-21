p = "common/tests.py"
s = open(p).read()
start = s.index("    def test_notify_user_created_after_commit(self):")
end = s.index("    def test_notify_user_rolled_back_with_transaction(self):")
new = '''    def test_notify_user_created_after_commit(self):
        from accounts.email_utils import _notify_user
        # on_processing must register a callback but defer execution.
        with self.captureOnCommitCallbacks() as callbacks:
            self._notify(
                self.mgr, self.emp,
                "Ticket status changed", f"Ticket {self.ticket.pk} moved.",
                self.ticket)
        self.assertEqual(len(callbacks), 1)
        self.assertEqual(Notification.objects.count(), 0)
'''
s = s[:start] + new + s[end:]
open(p, "w").write(s)
print("rewritten")
PY