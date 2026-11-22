p = "common/tests.py"
s = open(p).read()
append = '''
@override_settings(**LOC)
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
            case_number="ONB-2026-00001", case_type="onboarding",
            employee=self.emp, status="open")

    def _notify(self):
        from accounts.email_utils import _notify_user
        return _notify_user(
            self.mgr, self.emp,
            "Ticket status changed", f"Ticket {self.ticket.pk} moved.",
            self.ticket)

    def test_notify_user_created_after_commit(self):
        with transaction.atomic():
            self._notify()
        self.assertEqual(Notification.objects.count(), 1)
        n = Notification.objects.get()
        self.assertEqual(n.recipient, self.mgr)
        self.assertEqual(n.title, "Ticket status changed")

    def test_notify_user_rolled_back_with_transaction(self):
        try:
            with transaction.atomic():
                self._notify()
                raise IntegrityError("boom")
        except IntegrityError:
            pass
        self.assertEqual(Notification.objects.count(), 0)

    def test_notify_user_outside_transaction(self):
        self.assertEqual(Notification.objects.count(), 0)
        self._notify_user()
        self.assertEqual(Notification.objects.count(), 1)
        n = Notification.objects.get()
        self.assertEqual(n.recipient, self.mgr)
        self.assertEqual(n.object_id, str(self.ticket.pk))

    def test_notify_user_returns_none(self):
        self.assertIsNone(self._notify_user())

    def test_notify_user_skips_invalid_recipients(self):
        self._notify_user(None, self.emp, "t", "b", self.ticket)
        self._notify_user(self.mgr, None, "t", "b", self.ticket)
        self.assertEqual(Notification.objects.count(), 0)

'''
s = s.rstrip("\n") + "\n\n" + append
open(p, "w").write(s)
print("appended")
PY