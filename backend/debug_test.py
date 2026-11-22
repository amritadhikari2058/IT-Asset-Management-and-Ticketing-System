p = "common/tests.py"
s = open(p).read()
old = '''    def test_notify_user_created_after_commit(self):
        from accounts.email_utils import _notify_user
        with self.captureOnCommitCallbacks() as callbacks:
            _notify_user(
                self.mgr, self.emp,
                "Ticket status changed", f"Ticket {self.ticket.pk} moved.",
                self.ticket)
        self.assertEqual(len(callbacks), 1)
        self.assertEqual(Notification.objects.count(), 0)
        # Simulate the commit: run the captured callback.
        callbacks[0]()
        self.assertEqual(Notification.objects.count(), 1)
        n = Notification.objects.get()
        self.assertEqual(n.recipient, self.mgr)
        self.assertEqual(n.title, "Ticket status changed")'''
new = '''    def test_notify_user_created_after_commit(self):
        from accounts.email_utils import _notify_user
        with self.captureOnCommitCallbacks() as callbacks:
            self._notify()
        self.assertEqual(len(callbacks), 1)
        self.assertEqual(Notification.objects.count(), 0)
        cb = callbacks[0]
        print(f"DEBUG callback: {cb!r}")
        try:
            cb()
            print(f"DEBUG cb() succeeded")
        except Exception as e:
            print(f"DEBUG cb() raised: {type(e).__name__}: {e}")
        self.assertEqual(Notification.objects.count(), 1)
        n = Notification.objects.get()
        self.assertEqual(n.recipient, self.mgr)
        self.assertEqual(n.title, "Ticket status changed")'''
assert old in s
s = s.replace(old, new)
open(p, "w").write(s)
print("debug added")
PY