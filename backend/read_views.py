with open(r'accounts\views.py', 'r') as f:
    content = f.read()
# Find UserViewSet
start = content.find('class UserViewSet')
if start >= 0:
    # Print until next class or end
    end = content.find('\nclass ', start + 1)
    if end < 0:
        end = len(content)
    print(content[start:end])
else:
    print("UserViewSet not found")
    # Show file size
    print(f"File size: {len(content)} chars")