#!/usr/bin/env python
with open('backend/problem_management/tests.py', 'r') as f:
    lines = f.readlines()

# The broken section is around lines 718-735 (1-indexed), indices 717-734
# We need to replace lines 718-734 with correct assertions

# Current lines 718-734 (indices 717-733):
# 718:         self.assertEqual(res1.data["sequence"], 1)
# 719:         self.assertEqual(res2.data["sequence"], 1)
# 720:         self.assertEqual(res1.data["status"], "not_started")
# 721:         self.assertEqual(          <- starts assertEqual, spans to 724
# 722:             problem.history_records.filter(event_type="task_created").count(),
# 723:             0,
# 724:         )  # tasks created for other problem
# 725:         # NOTE: ProblemHistory events are scoped to each problem
# 726:         self.assertTrue(           <- starts assertTrue for p1, spans to 730
# 727:         self.assertTrue(          <- DUPLICATE, should be removed
# 728:             ProblemHistory.objects.filter(problem=p1.pk, event_type="task_created").count()
# 729:             >= 1,
# 730:         )
# 731:             >= 1,                   <- EXTRA, should be part of assertTrue for p2
# 732:         )                          <- EXTRA closing
# 733:         self.assertTrue(           <- starts assertTrue for p2
# 734:             ProblemHistory.objects.filter(problem=p2.pk, event_type="task_created").count()
#                         >= 1,

# What we want (lines 718-733 after fix):
# 718:         self.assertEqual(res1.data["sequence"], 1)
# 719:         self.assertEqual(res2.data["sequence"], 1)
# 720:         self.assertEqual(res1.data["status"], "not_started")
# 721:         self.assertEqual(
# 722:             problem.history_records.filter(event_type="task_created").count(),
# 723:             0,
# 724:         )  # tasks created for other problem
# 725:         # NOTE: ProblemHistory events are scoped to each problem
# 726:         self.assertTrue(
# 727:             ProblemHistory.objects.filter(problem=p1.pk, event_type="task_created").count()
# 728:             >= 1,
# 729:         )
# 730:         self.assertTrue(
# 731:             ProblemHistory.objects.filter(problem=p2.pk, event_type="task_created").count()
# 732:             >= 1,
# 733:         )

# Replace lines 718-733 (indices 717-732) with correct version
# Keep line 734+ (index 733+) intact

new_section = [
    '        self.assertEqual(res1.data["sequence"], 1)\n',
    '        self.assertEqual(res2.data["sequence"], 1)\n',
    '        self.assertEqual(res1.data["status"], "not_started")\n',
    '        self.assertEqual(\n',
    '            problem.history_records.filter(event_type="task_created").count(),\n',
    '            0,\n',
    '        )  # tasks created for other problem\n',
    '        # NOTE: ProblemHistory events are scoped to each problem\n',
    '        self.assertTrue(\n',
    '            ProblemHistory.objects.filter(problem=p1.pk, event_type="task_created").count()\n',
    '            >= 1,\n',
    '        )\n',
    '        self.assertTrue(\n',
    '            ProblemHistory.objects.filter(problem=p2.pk, event_type="task_created").count()\n',
    '            >= 1,\n',
    '        )\n',
]

# Replace lines 718-733 (indices 717 to 733 inclusive = 17 lines)
# Old lines 717-733 (17 lines: indices 717 through 733)
# New lines: 16 lines (we're removing the duplicate self.assertTrue line)

# Actually old lines 717-733 = 17 lines (717,718,...,733)
# new_section has 16 lines. We need to check.

# Let me just replace from index 717 to 733 (inclusive)
# That's lines 718-734 in 1-indexed

# Wait, let me re-count. The user asked for line 721 fix earlier.
# Let me just be precise: we want to replace the broken section.

# Current lines (0-indexed):
# 717: self.assertEqual(res1.data["sequence"], 1)  <- this is line 718
# 718: self.assertEqual(res2.data["sequence"], 1)  <- line 719
# 719: self.assertEqual(res1.data["status"], "not_started")  <- line 720
# 720: self.assertEqual(  <- line 721
# 721: problem.history_records.filter...  <- line 722
# 722: 0,  <- line 723
# 723: )  # tasks...  <- line 724
# 724: # NOTE...  <- line 725
# 725: self.assertTrue(  <- line 726
# 726: self.assertTrue(  <- line 727 (DUPLICATE)
# 727: ProblemHistory.objects.filter...  <- line 728
# 728: >= 1,  <- line 729
# 729: )  <- line 730
# 730: >= 1,  <- line 731 (EXTRA)
# 731: )  <- line 732 (EXTRA)
# 732: self.assertTrue(  <- line 733 (second assertTrue for p2)
# 733: ProblemHistory.objects.filter...  <- line 734
# 734: >= 1,  <- line 735

# We want to replace lines 717-734 (indices 717 to 734 inclusive, 18 lines)
# with new_section (10 lines? no, let me count)

# new_section has these lines:
# 1. self.assertEqual(res1.data["sequence"], 1)
# 2. self.assertEqual(res2.data["sequence"], 1)
# 3. self.assertEqual(res1.data["status"], "not_started")
# 4. self.assertEqual(
# 5. problem.history_records.filter...
# 6. 0,
# 7. )  # tasks...
# 8. # NOTE...
# 9. self.assertTrue(
# 10. ProblemHistory....
# 11. >= 1,
# 12. )
# 13. self.assertTrue(
# 14. ProblemHistory....
# 15. >= 1,
# 16. )

# That's 16 lines. Old lines 717-734 = 18 lines (indices 717,718,...,734).
# So we're removing 2 lines (the duplicate self.assertTrue and the extra >= 1, and ))

# Actually let me just do the replacement carefully

# We want to keep everything before line 718 (index 717) and after line 735 (index 734)
# And replace lines 718-735 (1-indexed) = indices 717-734

# Lines before: 0 to 716 (indices 0 to 716) = first 717 lines
# Lines after: 735 to end (index 735 onwards) = from line 736 onwards

before = lines[:717]  # up to and including line 717 (1-indexed: line 718)
after = lines[735:]  # from index 735 onwards (1-indexed: line 736 onwards)

# Wait, that's not right. Let me think again.
# 1-indexed line 718 = index 717
# 1-indexed line 735 = index 734

# We want to replace 1-indexed lines 718-735 with new content
# That's indices 717-734 (18 lines)

# before = lines[:717]  # indices 0 to 716, which is 1-indexed lines 1 to 717
# after = lines[735:]   # indices 735 onwards, which is 1-indexed lines 736+

# But we need to check: is line 735 (index 734) the last line we want to replace?
# Looking at the output, line 735 is: `            >= 1,`
# And line 736+ would be the rest of the test method.

# Actually, I need to be more careful. Let me just replace from index 717 to 734 inclusive.

# The section to replace (1-indexed lines 718-735):
# 718:         self.assertEqual(res1.data["sequence"], 1)
# 719:         self.assertEqual(res2.data["sequence"], 1)
# 720:         self.assertEqual(res1.data["status"], "not_started")
# 721:         self.assertEqual(
# 722:             problem.history_records.filter(event_type="task_created").count(),
# 723:             0,
# 724:         )  # tasks created for other problem
# 725:         # NOTE: ProblemHistory events are scoped to each problem
# 726:         self.assertTrue(
# 727:         self.assertTrue(
# 728:             ProblemHistory.objects.filter(problem=p1.pk, event_type="task_created").count()
# 729:             >= 1,
# 730:         )
# 731:             >= 1,
# 732:         )
# 733:         self.assertTrue(
# 734:             ProblemHistory.objects.filter(problem=p2.pk, event_type="task_created").count()
# 735:             >= 1,

# That's 18 lines (718 through 735 inclusive).

# New content should be 16 lines (removing the duplicate self.assertTrue on what was line 727 and the extra >= 1, ) on lines 731-732):

new_block = [
    '        self.assertEqual(res1.data["sequence"], 1)\n',
    '        self.assertEqual(res2.data["sequence"], 1)\n',
    '        self.assertEqual(res1.data["status"], "not_started")\n',
    '        self.assertEqual(\n',
    '            problem.history_records.filter(event_type="task_created").count(),\n',
    '            0,\n',
    '        )  # tasks created for other problem\n',
    '        # NOTE: ProblemHistory events are scoped to each problem\n',
    '        self.assertTrue(\n',
    '            ProblemHistory.objects.filter(problem=p1.pk, event_type="task_created").count()\n',
    '            >= 1,\n',
    '        )\n',
    '        self.assertTrue(\n',
    '            ProblemHistory.objects.filter(problem=p2.pk, event_type="task_created").count()\n',
    '            >= 1,\n',
    '        )\n',
]

# Replace lines 718-735 (1-indexed) = indices 717-734
# before = lines up to index 717 (exclusive) = lines[:717]
# after = lines from index 735 onwards = lines[735:]

before = lines[:717]
after = lines[735:]

with open('backend/problem_management/tests.py', 'w') as f:
    f.writelines(before + new_block + after)

print(f'Replaced lines 718-735 with {len(new_block)} new lines')
print(f'Total lines now: {len(before) + len(new_block) + len(after)}')