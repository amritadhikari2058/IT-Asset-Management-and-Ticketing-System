#!/usr/bin/env python
import sys
sys.path.insert(0, '.')

# Test 1: Check if kb_services imports correctly
try:
    import backend.assets.kb_services
    print("TEST 1 PASS: kb_services imports successfully")
except Exception as e:
    print(f"TEST 1 FAIL: kb_services import error: {e}")

# Test 2: Check if we can find KB article tests
try:
    import backend.assets.tests as tests_mod
    # Look for KB-related test functions
    import inspect
    members = [m for m in dir(tests_mod) if m.startswith('test_')]
    kb_tests = [m for m in members if 'article' in m.lower() or 'kb' in m.lower() or 'knowledge' in m.lower()]
    print(f"TEST 2: Found {len(kb_tests)} KB-related test functions: {kb_tests[:10]}")
except Exception as e:
    print(f"TEST 2 error: {e}")

# Test 3: Try running a simple KB-related test
try:
    # Just try collecting tests
    import pytest
    print("TEST 3: pytest available")
except:
    print("TEST 3: pytest not available directly")

print("\nAll basic tests completed")