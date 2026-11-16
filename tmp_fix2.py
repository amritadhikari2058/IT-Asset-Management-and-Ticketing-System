#!/usr/bin/env python
import re

with open('backend/problem_management/tests.py', 'r') as f:
    content = f.read()

# The broken lines are around 721 and 727 (1-indexed)
# We need to fix:
# 1. Remove the standalone line 721: "problem.history_records.filter(event_type="task_created").count(),"
# 2. Fix the self.assertTrue on line 727 to be complete
# 3. Ensure there's a second self.assertTrue for problem p2 if needed

# First, let's find and replace the problematic section
# The section from line 719 to 735 needs careful handling

# Original broken structure (approx lines 719-735):
# 719:         self.assertEqual(res2.data["sequence"], 1)
# 720:         self.assertEqual(res1.data["status"], "not_started")
# 721: problem.history_records.filter(event_type="task_created").count,
# 722:         self.assertEqual(
# 723:             problem.history_records.filter(event_type="task_created").count(),
# 724:             0,
# 725:         )  # tasks created for other problem
# 726:         # NOTE: ProblemHistory events are scoped to each problem
# 727:         self.assertTrue(
# 728:             ProblemHistory.objects.filter(problem=p1.pk, event_type="task_created").count()
# 729:             >= 1,
# 730:         )
# 731:         self.assertTrue(
# 732:             ProblemHistory.objects.filter(problem=p2.pk, event_type="task_created").count()
# 733:             >= 1,
# 734:         )

# What we want (after removing line 721 and fixing):
# 719:         self.assertEqual(res2.data["sequence"], 1)
# 720:         self.assertEqual(res1.data["status"], "not_started")
# 721:         self.assertEqual(  # was 722, now shifted
# 722:             problem.history_records.filter(event_type="task_created").count(),
# 723:             0,
# 724:         )  # tasks created for other problem
# 725:         # NOTE: ProblemHistory events are scoped to each problem
# 726:         self.assertTrue(  # was 727, now shifted
# 727:             ProblemHistory.objects.filter(problem=p1.pk, event_type="task_created").count()
# 728:             >= 1,
# 729:         )
# 730:         self.assertTrue(  # added for p2
# 731:             ProblemHistory.objects.filter(problem=p2.pk, event_type="task_created").count()
# 732:             >= 1,
# 733:         )

# Strategy: Replace the entire block from line 719 to 733
# Find the pattern and replace

old_block = '''        self.assertEqual(res2.data["sequence"], 1)
        self.assertEqual(res1.data["status"], "not_started")
problem.history_records.filter(event_type="task_created").count,
        self.assertEqual(
            problem.history_records.filter(event_type="task_created").count(),
            0,
        )  # tasks created for other problem
        # NOTE: ProblemHistory events are scoped to each problem
        self.assertTrue(
            ProblemHistory.objects.filter(problem=p1.pk, event_type="task_created").count()
            >= 1,
        )
        self.assertTrue(
            ProblemHistory.objects.filter(problem=p2.pk, event_type="task_created").count()
            >= 1,
        )'''

new_block = '''        self.assertEqual(res2.data["sequence"], 1)
        self.assertEqual(res1.data["status"], "not_started")
        self.assertEqual(
            problem.history_records.filter(event_type="task_created").count(),
            0,
        )  # tasks created for other problem
        # NOTE: ProblemHistory events are scoped to each problem
        self.assertTrue(
            ProblemHistory.objects.filter(problem=p1.pk, event_type="task_created").count()
            >= 1,
        )
        self.assertTrue(
            ProblemHistory.objects.filter(problem=p2.pk, event_type="task_created").count()
            >= 1,
        )'''

if old_block in content:
    content = content.replace(old_block, new_block)
    with open('backend/problem_management/tests.py', 'w') as f:
        f.write(content)
    print('File rewritten successfully')
else:
    print('Old block not found, trying alternative approach')
    # Try line-by-line fix
    lines = content.split('\n')
    # Find and remove the broken line 721
    # and fix the assertTrue sections
    print(f'File has {len(lines)} lines')
    # Show lines 718-735
    for i in range(717, min(736, len(lines))):
        print(f'{i+1}: {lines[i]}', end='')