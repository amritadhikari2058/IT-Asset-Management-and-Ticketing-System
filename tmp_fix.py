with open('backend/problem_management/tests.py', 'r') as f:
    lines = f.readlines()
# Remove line 721 (index 720) - the standalone broken line
del lines[720]
# Fix the second broken self.assertTrue on what is now at index 726
lines[726] = '        self.assertTrue(\n            ProblemHistory.objects.filter(problem=p1.pk, event_type="task_created").count()\n            >= 1,\n        )\n'
with open('backend/problem_management/tests.py', 'w') as f:
    f.writelines(lines)
print('Fixed both issues')