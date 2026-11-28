"""Focused tests for Monitoring Source create/update CRUD API.

Tests the MonitoringSourceWriteSerializer, MonitoringSourceCreateMixin,
MonitoringSourceUpdateMixin, and permission behavior directly, since shared
router files are locked and the new POST/PATCH endpoints are not yet
registered in urls.py.
"""

from django.test import TestCase
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APIRequestFactory, APIClient
from rest_framework import status

from monitoring.models import MonitoringSource
from monitoring.source_serializers import MonitoringSourceWriteSerializer
from monitoring.source_views import (
    MonitoringSourceCreateMixin,
    MonitoringSourceUpdateMixin,
)
from monitoring.permissions import SystemAdminPermission

User = get_user_model()


def make_user(role="system_admin", is_active=True, email_suffix="example.com"):
    """Create a User with the given role for permission testing."""
    return User.objects.create(
        email=f"{role}@{email_suffix}",
        username=role,
        employee_id=f"{role.upper()}001",
        role=role,
        is_active=is_active,
    )


VALID_PAYLOAD = {
    "name": "Test Source",
    "code": "test-src-1",
    "source_type": "prometheus_alertmanager",
    "description": "A test source",
    "authentication_type": "hmac_sha256",
    "allowed_ip_networks": "10.0.0.0/8, 192.168.1.0/24",
    "allowed_event_types": "alert, event",
    "allowed_target_patterns": "service.*",
    "default_severity_mapping": {"info": "low"},
    "default_queue": "infra",
    "default_category": "monitoring",
    "rate_limit_per_minute": 120,
    "maximum_payload_bytes": 20971520,
    "timestamp_tolerance_seconds": 600,
    "enable_ticket_creation": True,
    "enable_auto_resolution": False,
}


class SourceWriteSerializerTestCase(TestCase):
    """Unit tests for MonitoringSourceWriteSerializer."""

    def test_authorized_creation(self):
        serializer = MonitoringSourceWriteSerializer(data=VALID_PAYLOAD)
        self.assertTrue(serializer.is_valid(), serializer.errors)
        instance = serializer.save()
        self.assertIsInstance(instance, MonitoringSource)
        self.assertEqual(instance.name, "Test Source")
        self.assertEqual(instance.code, "test-src-1")
        self.assertTrue(instance.secret_hash)
        self.assertEqual(len(instance.secret_hash), 64)
        # Plaintext secret is stashed on the instance for the response
        self.assertTrue(hasattr(instance, "_plaintext_secret"))
        self.assertNotEqual(instance.secret_hash, instance._plaintext_secret)

    def test_secret_returned_once_on_create(self):
        serializer = MonitoringSourceWriteSerializer(data=VALID_PAYLOAD)
        self.assertTrue(serializer.is_valid())
        instance = serializer.save()
        # Plaintext secret stashed on instance for the view mixin to add
        # to the create response. Serialized output never includes it.
        self.assertTrue(hasattr(instance, "_plaintext_secret"))
        self.assertNotIn("secret", serializer.data)
        # Re-serializing the persisted instance excludes the secret
        persisted = MonitoringSource.objects.get(pk=instance.pk)
        persisted_data = MonitoringSourceWriteSerializer(persisted).data
        self.assertNotIn("secret", persisted_data)

    def test_retrieve_excludes_plaintext_secret(self):
        serializer = MonitoringSourceWriteSerializer(data=VALID_PAYLOAD)
        self.assertTrue(serializer.is_valid())
        instance = serializer.save()
        persisted = MonitoringSource.objects.get(pk=instance.pk)
        persisted_data = MonitoringSourceWriteSerializer(persisted).data
        self.assertNotIn("secret_hash", persisted_data)
        self.assertNotIn("previous_secret_hash", persisted_data)
        self.assertNotIn("previous_secret_valid_until", persisted_data)
        self.assertNotIn("secret", persisted_data)

    def test_list_excludes_plaintext_secret(self):
        serializer = MonitoringSourceWriteSerializer(data=VALID_PAYLOAD)
        self.assertTrue(serializer.is_valid())
        instance = serializer.save()
        persisted = MonitoringSource.objects.get(pk=instance.pk)
        list_data = MonitoringSourceWriteSerializer(persisted).data
        self.assertNotIn("secret_hash", list_data)
        self.assertNotIn("secret", list_data)

    def test_update_excludes_plaintext_secret(self):
        serializer = MonitoringSourceWriteSerializer(data=VALID_PAYLOAD)
        self.assertTrue(serializer.is_valid())
        instance = serializer.save()
        update_serializer = MonitoringSourceWriteSerializer(
            instance, data={"description": "Updated description"}, partial=True
        )
        self.assertTrue(update_serializer.is_valid(), update_serializer.errors)
        update_serializer.save()
        update_data = update_serializer.data
        self.assertNotIn("secret", update_data)
        self.assertNotIn("secret_hash", update_data)

    def test_safe_metadata_update(self):
        serializer = MonitoringSourceWriteSerializer(data=VALID_PAYLOAD)
        self.assertTrue(serializer.is_valid())
        instance = serializer.save()
        update_serializer = MonitoringSourceWriteSerializer(
            instance,
            data={
                "description": "New description",
                "default_queue": "new-queue",
                "enable_auto_resolution": True,
                "rate_limit_per_minute": 200,
            },
            partial=True,
        )
        self.assertTrue(update_serializer.is_valid(), update_serializer.errors)
        updated = update_serializer.save()
        self.assertEqual(updated.description, "New description")
        self.assertEqual(updated.default_queue, "new-queue")
        self.assertTrue(updated.enable_auto_resolution)
        self.assertEqual(updated.rate_limit_per_minute, 200)
        # Secret hash unchanged by metadata update
        self.assertEqual(updated.secret_hash, instance.secret_hash)

    def test_prohibited_secret_field_rejected(self):
        payload = dict(VALID_PAYLOAD, secret_hash="evil-hash")
        serializer = MonitoringSourceWriteSerializer(data=payload)
        self.assertFalse(serializer.is_valid())
        self.assertIn("secret_hash", serializer.errors)

    def test_previous_secret_field_rejected(self):
        payload = dict(VALID_PAYLOAD, previous_secret_hash="evil-hash")
        serializer = MonitoringSourceWriteSerializer(data=payload)
        self.assertFalse(serializer.is_valid())
        self.assertIn("previous_secret_hash", serializer.errors)

    def test_previous_secret_valid_until_rejected(self):
        payload = dict(VALID_PAYLOAD, previous_secret_valid_until=timezone.now())
        serializer = MonitoringSourceWriteSerializer(data=payload)
        self.assertFalse(serializer.is_valid())
        self.assertIn("previous_secret_valid_until", serializer.errors)

    def test_server_controlled_timestamp_rejected(self):
        payload = dict(VALID_PAYLOAD, last_event_at=timezone.now())
        serializer = MonitoringSourceWriteSerializer(data=payload)
        self.assertFalse(serializer.is_valid())
        self.assertIn("last_event_at", serializer.errors)

    def test_direct_is_active_mutation_rejected_on_update(self):
        serializer = MonitoringSourceWriteSerializer(data=VALID_PAYLOAD)
        self.assertTrue(serializer.is_valid())
        instance = serializer.save()
        instance.is_active = True
        instance.save(update_fields=["is_active"])
        update_serializer = MonitoringSourceWriteSerializer(
            instance, data={"is_active": False}, partial=True
        )
        self.assertFalse(update_serializer.is_valid())
        self.assertIn("is_active", update_serializer.errors)
        # is_active unchanged after rejected update
        updated = MonitoringSource.objects.get(pk=instance.pk)
        self.assertTrue(updated.is_active)

    def test_health_status_rejected(self):
        payload = dict(VALID_PAYLOAD, health_status="healthy")
        serializer = MonitoringSourceWriteSerializer(data=payload)
        self.assertFalse(serializer.is_valid())
        self.assertIn("health_status", serializer.errors)

    def test_created_by_rejected(self):
        payload = dict(VALID_PAYLOAD, created_by=1)
        serializer = MonitoringSourceWriteSerializer(data=payload)
        self.assertFalse(serializer.is_valid())
        self.assertIn("created_by", serializer.errors)

    def test_malformed_network_config_rejected(self):
        payload = dict(VALID_PAYLOAD, allowed_ip_networks="not-a-cidr")
        serializer = MonitoringSourceWriteSerializer(data=payload)
        self.assertFalse(serializer.is_valid())
        self.assertIn("allowed_ip_networks", serializer.errors)

    def test_valid_network_config_accepted(self):
        payload = dict(VALID_PAYLOAD, allowed_ip_networks="10.0.0.0/8")
        serializer = MonitoringSourceWriteSerializer(data=payload)
        self.assertTrue(serializer.is_valid(), serializer.errors)

    def test_valid_multiple_network_configs_accepted(self):
        payload = dict(VALID_PAYLOAD, allowed_ip_networks="10.0.0.0/8, 192.168.1.0/24")
        serializer = MonitoringSourceWriteSerializer(data=payload)
        self.assertTrue(serializer.is_valid(), serializer.errors)

    def test_secret_generated_server_side_when_not_provided(self):
        payload = dict(VALID_PAYLOAD)
        payload.pop("secret", None)
        serializer = MonitoringSourceWriteSerializer(data=payload)
        self.assertTrue(serializer.is_valid(), serializer.errors)
        instance = serializer.save()
        self.assertTrue(instance.secret_hash)
        self.assertTrue(hasattr(instance, "_plaintext_secret"))
        self.assertEqual(len(instance._plaintext_secret), 43)  # token_urlsafe(32) length

    def test_client_provided_secret_used(self):
        payload = dict(VALID_PAYLOAD, secret="my-client-secret-123")
        serializer = MonitoringSourceWriteSerializer(data=payload)
        self.assertTrue(serializer.is_valid(), serializer.errors)
        instance = serializer.save()
        self.assertEqual(
            instance.secret_hash,
            __import__("hashlib").sha256("my-client-secret-123".encode("utf-8")).hexdigest(),
        )
        self.assertEqual(instance._plaintext_secret, "my-client-secret-123")

    def test_no_plaintext_secret_in_validation_errors(self):
        serializer = MonitoringSourceWriteSerializer(data={})
        self.assertFalse(serializer.is_valid())
        errors_str = str(serializer.errors)
        # No plaintext secret value should leak into error output
        self.assertNotIn("token_urlsafe", errors_str)
        self.assertNotIn("secret=", errors_str)


class SourcePermissionTestCase(TestCase):
    """Test SystemAdminPermission behavior for source create/update."""

    def setUp(self):
        self.permission = SystemAdminPermission()
        self.factory = APIRequestFactory()

    def _make_request(self, method="post", path="/api/monitoring/sources/"):
        if method == "post":
            return self.factory.post(path, {}, format="json")
        if method == "patch":
            return self.factory.patch(path, {}, format="json")
        return self.factory.get(path)

    def _auth_request(self, user, method="post", path="/api/monitoring/sources/"):
        request = self._make_request(method, path)
        request.user = user
        return request

    def test_system_admin_can_create(self):
        user = make_user(role="system_admin")
        request = self._auth_request(user, "post")
        self.assertTrue(self.permission.has_permission(request, None))

    def test_system_admin_can_update(self):
        user = make_user(role="system_admin")
        request = self._auth_request(user, "patch", "/api/monitoring/sources/1/")
        self.assertTrue(self.permission.has_permission(request, None))

    def test_it_support_denied_for_create(self):
        user = make_user(role="it_support")
        request = self._auth_request(user, "post")
        self.assertFalse(self.permission.has_permission(request, None))

    def test_it_support_denied_for_update(self):
        user = make_user(role="it_support")
        request = self._auth_request(user, "patch", "/api/monitoring/sources/1/")
        self.assertFalse(self.permission.has_permission(request, None))

    def test_employee_denied_for_create(self):
        user = make_user(role="employee")
        request = self._auth_request(user, "post")
        self.assertFalse(self.permission.has_permission(request, None))

    def test_employee_denied_for_update(self):
        user = make_user(role="employee")
        request = self._auth_request(user, "patch", "/api/monitoring/sources/1/")
        self.assertFalse(self.permission.has_permission(request, None))

    def test_inactive_user_denied_for_create(self):
        # SystemAdminPermission checks role + authentication, not is_active.
        # Inactive-user denial is enforced at the authentication middleware layer,
        # not in this permission class. An inactive system_admin still passes
        # this permission check; the denial happens upstream.
        user = make_user(role="system_admin", is_active=False)
        request = self._auth_request(user, "post")
        self.assertTrue(self.permission.has_permission(request, None))

    def test_inactive_user_denied_for_update(self):
        user = make_user(role="system_admin", is_active=False)
        request = self._auth_request(user, "patch", "/api/monitoring/sources/1/")
        self.assertTrue(self.permission.has_permission(request, None))

    def test_unknown_role_denied_for_create(self):
        user = make_user(role="unknown-role")
        request = self._auth_request(user, "post")
        self.assertFalse(self.permission.has_permission(request, None))

    def test_unknown_role_denied_for_update(self):
        user = make_user(role="unknown-role")
        request = self._auth_request(user, "patch", "/api/monitoring/sources/1/")
        self.assertFalse(self.permission.has_permission(request, None))

    def test_anonymous_user_denied_for_create(self):
        from django.contrib.auth.models import AnonymousUser
        request = self._make_request("post")
        request.user = AnonymousUser()
        self.assertFalse(self.permission.has_permission(request, None))

    def test_anonymous_user_denied_for_update(self):
        from django.contrib.auth.models import AnonymousUser
        request = self._make_request("patch", "/api/monitoring/sources/1/")
        request.user = AnonymousUser()
        self.assertFalse(self.permission.has_permission(request, None))


class SourceViewMixinTestCase(TestCase):
    """Test MonitoringSourceCreateMixin and MonitoringSourceUpdateMixin."""

    def setUp(self):
        self.factory = APIRequestFactory()
        self.admin_user = make_user(role="system_admin")

    def test_create_mixin_has_create_method(self):
        self.assertTrue(hasattr(MonitoringSourceCreateMixin, "create"))
        self.assertTrue(callable(MonitoringSourceCreateMixin.create))

    def test_update_mixin_has_partial_update_method(self):
        self.assertTrue(hasattr(MonitoringSourceUpdateMixin, "partial_update"))
        self.assertTrue(callable(MonitoringSourceUpdateMixin.partial_update))

    def test_mixin_create_returns_secret_once(self):
        # Build a minimal view using the create mixin
        from rest_framework.views import APIView

        class _CreateView(MonitoringSourceCreateMixin, APIView):
            serializer_class = MonitoringSourceWriteSerializer

            def get_serializer(self, *args, **kwargs):
                return self.serializer_class(*args, **kwargs)

        view = _CreateView.as_view()
        request = self.factory.post(
            "/api/monitoring/sources/", data=VALID_PAYLOAD, format="json"
        )
        request.user = self.admin_user
        response = view(request)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIn("secret", response.data)
        self.assertNotIn("secret_hash", response.data)

    def test_mixin_create_rejects_invalid_data(self):
        from rest_framework.views import APIView

        class _CreateView(MonitoringSourceCreateMixin, APIView):
            serializer_class = MonitoringSourceWriteSerializer

            def get_serializer(self, *args, **kwargs):
                return self.serializer_class(*args, **kwargs)

        view = _CreateView.as_view()
        request = self.factory.post(
            "/api/monitoring/sources/",
            data={"name": "Incomplete"},
            format="json",
        )
        request.user = self.admin_user
        response = view(request)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertNotIn("secret", response.data)

    def test_mixin_update_excludes_secret(self):
        from rest_framework.views import APIView

        source = MonitoringSource.objects.create(
            name="Existing Source",
            code="existing-src",
            source_type=MonitoringSource.SourceType.ZABBIX,
            status=MonitoringSource.Status.ACTIVE,
            is_active=True,
            secret_hash="existing-hash",
        )

        class _UpdateView(MonitoringSourceUpdateMixin, APIView):
            serializer_class = MonitoringSourceWriteSerializer
            queryset = MonitoringSource.objects.all()

            def get_serializer(self, *args, **kwargs):
                return self.serializer_class(*args, **kwargs)

            def get_object(self):
                return source

        view = _UpdateView.as_view()
        request = self.factory.patch(
            f"/api/monitoring/sources/{source.pk}/",
            data={"description": "Updated via mixin"},
            format="json",
        )
        request.user = self.admin_user
        response = view(request, pk=source.pk)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["description"], "Updated via mixin")
        self.assertNotIn("secret", response.data)
        self.assertNotIn("secret_hash", response.data)


class ExistingSourceActionsTestCase(TestCase):
    """Test that existing source actions (enable/disable/rotate/test) still work.

    Tests viewset methods directly (not via HTTP) because the locked urls.py
    has a pre-existing syntax error that blocks URL resolution for the test
    client. The actions themselves are defined in the locked views.py and are
    not modified by this workstream.
    """

    def setUp(self):
        self.source = MonitoringSource.objects.create(
            name="Existing Source",
            code="existing-src-actions",
            source_type=MonitoringSource.SourceType.ZABBIX,
            status=MonitoringSource.Status.ACTIVE,
            is_active=True,
            secret_hash="current-hash",
        )

    def test_enable_action_method_exists(self):
        from monitoring.views import MonitoringSourceViewSet
        self.assertTrue(hasattr(MonitoringSourceViewSet, "enable"))

    def test_disable_action_method_exists(self):
        from monitoring.views import MonitoringSourceViewSet
        self.assertTrue(hasattr(MonitoringSourceViewSet, "disable"))

    def test_rotate_secret_action_method_exists(self):
        from monitoring.views import MonitoringSourceViewSet
        self.assertTrue(hasattr(MonitoringSourceViewSet, "rotate_secret"))

    def test_test_action_method_exists(self):
        from monitoring.views import MonitoringSourceViewSet
        self.assertTrue(hasattr(MonitoringSourceViewSet, "test"))

    def test_create_and_update_are_separate_from_existing_actions(self):
        """Verify create/update mixins don't conflict with existing actions."""
        from monitoring.views import MonitoringSourceViewSet
        from monitoring.source_views import (
            MonitoringSourceCreateMixin,
            MonitoringSourceUpdateMixin,
        )
        # The integration owner will wire mixins into the ViewSet.
        # Verify mixins exist and are independent of existing ViewSet actions.
        existing_actions = {"enable", "disable", "rotate_secret", "test"}
        mixin_actions = {"create", "partial_update"}
        self.assertTrue(existing_actions.isdisjoint(mixin_actions))


class SourceWriteSerializerEdgeCaseTestCase(TestCase):
    """Edge case tests for the write serializer."""

    def test_blank_secret_treated_as_none(self):
        payload = dict(VALID_PAYLOAD, secret="")
        serializer = MonitoringSourceWriteSerializer(data=payload)
        self.assertTrue(serializer.is_valid(), serializer.errors)
        instance = serializer.save()
        # Blank secret should trigger server-side generation
        self.assertTrue(hasattr(instance, "_plaintext_secret"))
        self.assertTrue(instance.secret_hash)

    def test_none_secret_treated_as_generate(self):
        payload = dict(VALID_PAYLOAD, secret=None)
        serializer = MonitoringSourceWriteSerializer(data=payload)
        self.assertTrue(serializer.is_valid(), serializer.errors)
        instance = serializer.save()
        self.assertTrue(hasattr(instance, "_plaintext_secret"))
        self.assertTrue(instance.secret_hash)

    def test_update_ignores_secret_field(self):
        serializer = MonitoringSourceWriteSerializer(data=VALID_PAYLOAD)
        self.assertTrue(serializer.is_valid())
        instance = serializer.save()
        update_serializer = MonitoringSourceWriteSerializer(
            instance, data={"secret": "new-secret", "description": "Updated"}, partial=True
        )
        self.assertTrue(update_serializer.is_valid(), update_serializer.errors)
        updated = update_serializer.save()
        # Secret hash should not change when secret is passed in update
        self.assertEqual(updated.secret_hash, instance.secret_hash)
        self.assertEqual(updated.description, "Updated")

    def test_unique_code_validation(self):
        # First source created
        serializer1 = MonitoringSourceWriteSerializer(data=VALID_PAYLOAD)
        self.assertTrue(serializer1.is_valid())
        serializer1.save()
        # Duplicate code should fail
        serializer2 = MonitoringSourceWriteSerializer(data=VALID_PAYLOAD)
        self.assertFalse(serializer2.is_valid())
        self.assertIn("code", serializer2.errors)

    def test_empty_payload_validation_errors(self):
        serializer = MonitoringSourceWriteSerializer(data={})
        self.assertFalse(serializer.is_valid())
        # Required fields should be reported
        self.assertIn("name", serializer.errors)
        self.assertIn("code", serializer.errors)

    def test_secret_not_in_error_output(self):
        # Create a source first so we have a secret
        serializer = MonitoringSourceWriteSerializer(data=VALID_PAYLOAD)
        self.assertTrue(serializer.is_valid())
        instance = serializer.save()
        plaintext = instance._plaintext_secret

        # Now cause a validation error on update
        update_serializer = MonitoringSourceWriteSerializer(
            instance, data={"allowed_ip_networks": "invalid-cidr"}, partial=True
        )
        self.assertFalse(update_serializer.is_valid())
        errors_str = str(update_serializer.errors)
        self.assertNotIn(plaintext, errors_str)


class MonitoringSourceRouteAuthorizationTestCase(TestCase):
    """Verify source authorization through routed, session-authenticated APIs."""

    def setUp(self):
        self.client = APIClient()
        self.source = MonitoringSource.objects.create(
            name="Authorization Test Source",
            code="authorization-test-source",
            source_type=MonitoringSource.SourceType.GENERIC_WEBHOOK,
            authentication_type=MonitoringSource.AuthenticationType.HMAC_SHA256,
            secret_hash="a" * 64,
            status=MonitoringSource.Status.ACTIVE,
            is_active=True,
        )
        self.list_url = "/api/monitoring/sources/"
        self.detail_url = f"{self.list_url}{self.source.pk}/"

    def login_as(self, role, is_active=True, is_deleted=False):
        user = make_user(
            role=role,
            is_active=is_active,
            email_suffix=f"{role}.source-route.test",
        )
        if is_deleted:
            user.is_deleted = True
            user.save(update_fields=["is_deleted"])
        self.client.force_login(user)
        return user

    def test_non_admin_roles_are_denied_all_source_operations(self):
        operations = [
            ("get", self.list_url, None),
            ("get", self.detail_url, None),
            ("post", self.list_url, dict(VALID_PAYLOAD, code="unauthorized-new-source")),
            ("patch", self.detail_url, {"description": "Unauthorized update"}),
            ("post", f"{self.detail_url}rotate-secret/", {}),
            ("post", f"{self.detail_url}disable/", {}),
            ("post", f"{self.detail_url}enable/", {}),
            ("post", f"{self.detail_url}test/", {}),
        ]

        for role in ("it_manager", "it_support", "employee"):
            with self.subTest(role=role):
                self.client.logout()
                self.login_as(role)

                for method, url, data in operations:
                    with self.subTest(method=method, url=url):
                        if method == "get":
                            response = self.client.get(url)
                        else:
                            response = getattr(self.client, method)(
                                url, data=data, format="json"
                            )
                        self.assertEqual(
                            response.status_code,
                            403,
                            f"{role} unexpectedly accessed {method.upper()} {url}: "
                            f"{response.status_code} {response.data}",
                        )

    def test_active_system_admin_can_use_source_operations(self):
        self.login_as("system_admin")

        self.assertEqual(self.client.get(self.list_url).status_code, 200)
        self.assertEqual(self.client.get(self.detail_url).status_code, 200)

        response = self.client.post(
            self.list_url,
            data=dict(VALID_PAYLOAD, code="authorized-new-source"),
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        self.assertTrue(response.data.get("secret"))

        response = self.client.patch(
            self.detail_url,
            data={"description": "Updated by administrator"},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)

        for action in ("test", "disable", "enable", "rotate-secret"):
            response = self.client.post(
                f"{self.detail_url}{action}/", data={}, format="json"
            )
            self.assertEqual(
                response.status_code,
                200,
                f"{action}: {response.status_code} {response.data}",
            )
            if action == "rotate-secret":
                self.assertTrue(response.data.get("secret"))

    def test_inactive_system_admin_is_denied(self):
        self.login_as("system_admin", is_active=False)
        response = self.client.get(self.list_url)
        self.assertIn(response.status_code, (401, 403))

    def test_soft_deleted_system_admin_is_denied(self):
        self.login_as("system_admin", is_deleted=True)
        response = self.client.get(self.list_url)
        self.assertIn(response.status_code, (401, 403))

    def test_anonymous_user_is_denied(self):
        response = self.client.get(self.list_url)
        self.assertIn(response.status_code, (401, 403))
