"""Test suite aggregator for the Software Licensing app."""

from licensing.test_security import LicenseSecretSecurityTests
from licensing.test_services import LicensingServicesTests
from licensing.test_permissions import LicensingPermissionsTests
from licensing.test_reconciliation import LicensingReconciliationTests
from licensing.test_tasks import LicensingTasksTests
from licensing.test_exports import LicensingExportsTests
from licensing.test_commands import LicensingManagementCommandsTests
from licensing.test_views import LicensingViewsTests

__all__ = [
    "LicenseSecretSecurityTests",
    "LicensingServicesTests",
    "LicensingPermissionsTests",
    "LicensingReconciliationTests",
    "LicensingTasksTests",
    "LicensingExportsTests",
    "LicensingManagementCommandsTests",
    "LicensingViewsTests",
]
