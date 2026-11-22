#!/usr/bin/env python
"""Debug script to identify N+1 queries and performance issues."""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

import django
django.setup()

from django.db import connection, reset_queries
from django.test import Client
from tickets.models import Ticket
from assets.models import Asset
from accounts.models import User

def count_queries(description, func):
    """Run a function and count database queries."""
    reset_queries()
    query_count = len(connection.queries)
    result = func()
    after_count = len(connection.queries)
    print(f"\n{description}:")
    print(f"  Queries: {after_count - query_count}")
    for i, q in enumerate(connection.queries[query_count:], query_count + 1):
        print(f"  Query {i}: {q['sql'][:100]}...")
    return result

def test_ticket_listing():
    """Test ticket listing queries."""
    tickets = Ticket.objects.all()[:10]
    return list(tickets)

def test_asset_listing():
    """Test asset listing queries."""
    assets = Asset.objects.all()[:10]
    return list(assets)

def test_employee_lookup():
    """Test employee lookup queries."""
    users = User.objects.all()[:5]
    return list(users)

if __name__ == '__main__':
    print("=" * 60)
    print("DATABASE QUERY PERFORMANCE ANALYSIS")
    print("=" * 60)
    
    count_queries("Ticket listing (10 records)", test_ticket_listing)
    count_queries("Asset listing (10 records)", test_asset_listing)
    count_queries("Employee lookup (5 records)", test_employee_lookup)
    
    print("\n" + "=" * 60)