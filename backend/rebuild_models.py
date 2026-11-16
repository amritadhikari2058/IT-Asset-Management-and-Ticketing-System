"""Rebuild monitoring models.py cleanly."""
content = open('backend/monitoring/models.py').read()
# Keep only lines up to MonitoringEvent class (line 123)
lines = content.split('\n')
# Find the first class definition after MonitoringEvent
keep_lines = []
in_monitoring_event = False
brace_depth = 0
for i, line in enumerate(lines):
    if 'class MonitoringEvent(models.Model):' in line:
        in_monitoring_event = True
    if in_monitoring_event:
        keep_lines.append(line)
        # Count braces to find end of class
        brace_depth += line.count('{') - line.count('}')
        if brace_depth <= 0 and 'class ' in line and 'MonitoringEvent' not in line:
            break

# Actually, simpler: keep lines 1-123 (MonitoringSource + MonitoringEvent)
# Then add remaining models manually
keep_lines = lines[:123]  # Up to end of MonitoringEvent (line 123 is last line before MonitoringEvent class)

# Wait, line 124 is MonitoringEvent class definition. Let me keep up to line 123.
# But MonitoringEvent class spans multiple lines. Let me find its end.
open('backend/monitoring/models.py', 'w').write('\n'.join(keep_lines))
print(f'Kept {len(keep_lines)} lines')