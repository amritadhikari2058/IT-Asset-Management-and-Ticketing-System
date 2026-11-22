with open(r'tickets\views.py', 'r') as f:
    content = f.read()

# Find _iter_normalized_rows function
start = content.find('def _iter_normalized_rows')
if start >= 0:
    # Find end of function (next def or end of class)
    end = content.find('\n        def ', start + 1)
    if end < 0:
        end = content.find('\n    def ', start + 1)
    if end < 0:
        end = start + 3000
    print(content[start:end])