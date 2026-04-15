# API Accounts Module

## Purpose

Owns user and admin identity inside the API service.

## Responsibilities

- Create and read user accounts.
- Provision tagged synthetic trader accounts for internal workflows.
- Authenticate users.
- Manage sessions or tokens.
- Distinguish real users, admins, and synthetic trader accounts where needed for API views.
- Enforce admin permissions for admin-only endpoints.

## Boundaries

- May write user, session, and role records.
- Must not mutate portfolio cash, positions, trades, or instrument prices.
- Synthetic trader strategy configuration belongs to the worker service, not this module.
