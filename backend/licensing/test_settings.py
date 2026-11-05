"""Isolated test settings for licensing test runner.

Inherits full project settings while isolating licensing test runs from
incomplete concurrent migrations in other workstreams.
"""

from config.settings import *  # noqa: F403

# Exclude in-progress concurrent apps if they break test database syncdb
INSTALLED_APPS = [app for app in INSTALLED_APPS if app != "changes"]  # noqa: F405
