"""Fix urls.py - rewrite completely."""
content = open('backend/monitoring/urls.py').read()
# Remove everything from line 41 onward that's broken
lines = content.split('\n')
# Find the problematic line 41 (which is actually a comma)
for i, line in enumerate(lines):
    # Remove lines that are just commas or extra brackets
    stripped = line.strip()
    if stripped == ',' or stripped == ']' or stripped == ']':
        # Keep the first occurrence of pattern, but skip the problematic ones
        # Look for the target-coverage line to find the pattern
        if 'path("reports/target-coverage/' in ''.join(lines[max(0,i-20):i]):
            # Find the full correct line
            for j in range(i, len(lines)):
                if 'path("reports/target-coverage/' in lines[j]:
                    # Find the closing bracket line that belongs to this path
                    # Check if next lines are properly formed
                    if j+1 < len(lines) and lines[j+1].strip() == ']':
                        # This is the end of urlpatterns
                        lines = lines[:j+1]
                        break
            break

with open('backend/monitoring/urls.py', 'w') as f:
    f.write('\n'.join(lines))
print('Rewritten urls.py')
print('Lines:', len(lines))