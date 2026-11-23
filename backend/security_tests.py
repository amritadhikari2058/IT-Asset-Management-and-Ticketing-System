"""
Security Regression Test Suite for IT Asset and Ticketing System

This test suite validates the security hardening changes implemented as part of
Engineering Assignment 4. It covers authentication, authorization, object-level
data isolation, sensitive data leakage, and other security domains.

Synthetic canary values are used to test for information leakage without using
actual production credentials or personal records.
"""
import pytest
from django.test import override_settings, tag
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from accounts.models import User
from tickets.models import Ticket
from assets.models import Asset
from common.permissions import IsActiveAuthenticated, IsSystemAdmin, IsITStaff


# Synthetic canary values - these are fake values used only for security testing.
# Never use actual production credentials or personal records as test data.
CANARY_EMPLOYEE_ID = "CAN-SEC-001"
CANARY_TICKET_TITLE = "SECURITY-CANARY-TEST"
CANARY_ASSET_TAG = "CAN-SEC-ASSET"
CANARY_PASSWORD = "synthetic_canary_password_12345"