p = "common/tests.py"
s = open(p).read()
start = s.index("@override_settings(**LOC)\nclass TicketNotificationTransactionTests")
end = s.index("@override_settings(**LOC)\nclass TicketEmailPreferenceTests")
new = '''@override_settings(**LOC)
class TicketNotificationTransactionTests(TestCase):
    """Regression coverage for accounts.email_utils._notify_user.

    The in-app notification must be created only after the surrounding
    transaction commits, so a rolled-back ticket creation or state change
    never leaves an orphaned notification pointing at a non-existent or
    reverted record.
    """

    def setUp(self):
        self.dep, self.admin, self.mgr, self.emp = make_users()
        self.c = APIClient()
        self.tcat = TicketCategory.objects.create(name="EM")
        self.ticket = Ticket.objects.create(
            title="Existing ticket",
            description="existing",
            category=self.tcat,
            priority="medium",
            status="open",
            requester=self.emp,
            department=self.dep)

    def _notify(self):
        from accounts.email_utils import _notify_user
        return _notify_user(
            self.mgr, self.emp,
            "Ticket status changed", f"Ticket {self.ticket.pk} moved.",
            self.ticket)

    def test_notify_user_created_after_commit(self):
        from accounts.email_utils import _notify_user
        # The callback is registered but NOT executed until commit.
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
        self.assertEqual(n.title, "Ticket status changed")

    def test_notify_user_rolled_back_with_transaction(self):
        from accounts.email_utils import _notify_user
        try:
            with transaction.atomic():
                self._notify()
                raise IntegrityError("boom")
        except IntegrityError:
            pass
        self.assertEqual(Notification.objects.count(), 0)

    def test_notify_user_defers_until_commit(self):
        from accounts.email_utils import _notify_user
        # Inside the test's atomic block: deferred, not visible yet.
        self._notify()
        self.assertEqual(Notification.objects.count(), 0)

    def test_notify_user_returns_none(self):
        from accounts.email_utils import _notify_user
        self.assertIsNone(self._notify())

    def test_notify_user_skips_invalid_recipients(self):
        from accounts.email_utils import _notify_user
        _notify_user(None, self.emp, "t", "b", self.ticket)
        _notify_user(self.mgr, None, "t", "b", self.ticket)
        self.assertEqual(Notification.objects.count(), 0)

'''
s = s[:start] + new + s[end:]
open(p, "w").write(s)
print("rewritten")
PY