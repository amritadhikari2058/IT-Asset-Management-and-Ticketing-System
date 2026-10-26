from rest_framework import serializers

from accounts.models import Department, User


class DepartmentSerializer(serializers.ModelSerializer):
    head_email = serializers.CharField(source="head.email", read_only=True)
    member_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Department
        fields = ["id", "name", "code", "description", "head", "head_email",
                  "is_active", "member_count", "created_at", "updated_at"]
        read_only_fields = ["id", "created_at", "updated_at"]


class UserSerializer(serializers.ModelSerializer):
    """Ordinary representation. Role/permission changes go via admin endpoint.

    Bulk/ordinary updates MUST NOT touch role or can_create_tickets
    (enforced in views by popping those keys).
    """
    home_department_name = serializers.CharField(
        source="home_department.name", read_only=True
    )

    class Meta:
        model = User
        fields = ["id", "employee_id", "username", "email", "email_verified",
                  "first_name",
                  "last_name", "role", "home_department",
                  "home_department_name", "phone", "job_title",
                  "can_create_tickets", "is_active", "is_deleted",
                  "date_joined"]
        read_only_fields = ["id", "role", "can_create_tickets",
                            "is_deleted", "date_joined", "email_verified"]


class UserCreateSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, min_length=8)

    class Meta:
        model = User
        fields = ["employee_id", "username", "email", "password", "first_name",
                  "last_name", "role", "home_department", "phone",
                  "job_title", "can_create_tickets"]

    def create(self, validated_data):
        password = validated_data.pop("password")
        user = User(**validated_data)
        user.set_password(password)
        user.save()
        return user


class BulkEmployeeRowSerializer(serializers.Serializer):
    """One CSV/Excel row for preview. Employee ID is the matching key."""
    employee_id = serializers.CharField()
    username = serializers.CharField(required=False, allow_blank=True)
    email = serializers.EmailField(required=False, allow_blank=True)
    first_name = serializers.CharField(required=False, allow_blank=True)
    last_name = serializers.CharField(required=False, allow_blank=True)
    phone = serializers.CharField(required=False, allow_blank=True)
    job_title = serializers.CharField(required=False, allow_blank=True)
    home_department = serializers.CharField(required=False, allow_blank=True)
    is_active = serializers.BooleanField(required=False)
    receive_ticket_emails = serializers.BooleanField(required=False)
