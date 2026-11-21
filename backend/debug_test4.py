p = "common/tests.py"
s = open(p).read()
old = '''        self.assertEqual(len(callbacks), 1)
        self.assertEqual(Notification.objects.count(), 0)
        # Simulate the commit: run the captured callback.
        cb = callbacks[0]
        print(f"DEBUG callback: {cb!r}")
        try:
            cb()
            print(f"DEBUG cb() succeeded, count now: {Notification.objects.count()}")
        except Exception as e:
            print(f"DEBUG cb() raised: {type(e).__name__}: {e}")
        self.assertEqual(Notification.objects.count(), 1)'''
new = '''        self.assertEqual(len(callbacks), 1)
        self.assertEqual(Notification.objects.count(), 0)
        # Simulate the commit: run the captured callback.
        cb = callbacks[0]
        print(f"DEBUG callback: {cb!r} callable={callable(cb)}")
        result = cb()
        print(f"DEBUG cb() returned: {result!r}, count now: {Notification.objects.count()}")'''
assert old in s
s = s.replace(old, new)
open(p, "w").write(s)
print("debug2 added")
PY