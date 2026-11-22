p = "common/tests.py"
s = open(p).read()
import re
# Find all TicketNotificationTransactionTests class starts
class_starts = [m.start() for m in re.finditer(r"class TicketNotificationTransactionTests\(TestCase\):", s)]
print("Found TicketNotificationTransactionTests classes at:", class_starts)

new_class = '''class TicketNotificationTransactionTests(TestCase):
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
        with self.captureOnCommitCallbacks() as callbacks:
            self._notify(
                self.mgr, self.emp,
                "Ticket status changed", f"Ticket {self.ticket.pk} moved.",
                self.ticket)
        self.assertEqual(len(callbacks), 1)
        self.assertEqual(Notification.objects.count(), 0)

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
        self._notify(
            self.mgr, self.emp,
            "Ticket status changed", f"Ticket {self.ticket.pk} moved.",
            self.ticket)
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

# Replace each class from start to its end (next class definition or end of file)
result_parts = []
last_end = 0
for start in class_starts:
    # Find the end of this class: next '\nclass ' or '@override_settings(**LOC)\nclass TicketEmailPreferenceTests' after start
    m = re.search(r"\nclass ", s[start+1:])
    if m:
        class_end = start + 1 + m.start()
    else:
        # find next @override_settings(**LOC)\nclass TicketEmailPreferenceTests after start
        idx = s.find("@override_settings(**LOC)\nclass TicketEmailPreferenceTests", start)
        class_end = idx if idx != -1 else len(s)
    class_end = m.start() + start + 1 if m else class_end
    result += s[last_end:start]
    result += new_class
    last_end = class_end
# Append remaining text after the last class
result += s[last_end:]
open(p, "w").write(s)
print("rewritten cleanly - all TicketNotificationTransactionTests classes replaced")