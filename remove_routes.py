#!/usr/bin/env python3
import sys

with open('D:\\\\IT-Asset-Management-and-Ticketing-System\\\\frontend\\\\src\\\\App.jsx', 'r') as f:
    content = f.read()

# Find and remove the routes object
start_marker = '  const routes = {'
end_marker = '  return routes[route] ?? <Tickets />;  }'

start_pos = content.find(start_marker)
end_pos = content.find(end_marker, start_pos)
if start_pos >= 0 and end_pos >= 0:
    end_pos += len(end_marker)
    # Replace the routes object with just a comment and fallback
    new_content = content[:start_pos] + '  // All routing handled by explicit if checks above\n  return <Tickets />;\n}\n' + content[end_pos:]
    with open('D:\\\\IT-Asset-Management-and-Ticketing-System\\\\frontend\\\\src\\\\App.jsx', 'w') as f:
        f.write(new_content)
    print('Routes object removed successfully')
else:
    print(f'Could not find markers: start={start_pos}, end={end_pos}')
    sys.exit(1)