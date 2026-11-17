import subprocess
import os
import time

runDir = os.environ['TEMP'] + '\\monitoring_policy_single_test'
os.makedirs(runDir, exist_ok=True)
stdout = runDir + '\\future_effective.stdout.log'
stderr = runDir + '\\future_effective.stderr.log'
exitFile = runDir + '\\future_effective.exit.txt'
pidFile = runDir + '\\future_effective.pid.txt'
startFile = runDir + '\\future_effective.start.txt'

# Remove stale files
for f in [stdout, stderr, exitFile, pidFile, startFile]:
    if os.path.exists(f):
        os.remove(f)

# Write start time
with open(startFile, 'w', encoding='utf-8') as f:
    f.write(time.strftime('%Y-%m-%dT%H:%M:%S.%f%z'))

# Run test in background
cmd = [
    'python', 'backend/manage.py', 'test',
    'monitoring.test_ticket_automation.PolicyTestCase.test_policy_before_effective_date_fails_closed',
    '--verbosity', '3', '--keepdb', '--noinput'
]
with open(stdout, 'w', encoding='utf-8') as outf, \
     open(stderr, 'w', encoding='utf-8') as errf:
    proc = subprocess.Popen(cmd, cwd=r'D:\IT-Asset-Management-and-Ticketing-System',
                          stdout=outf, stderr=errf)

with open(pidFile, 'w', encoding='ascii') as f:
    f.write(str(proc.pid))

print('BACKGROUND_STARTED', proc.pid)