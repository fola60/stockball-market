# API Accounts Module

## Purpose

Owns user and admin identity inside the API service.

## Responsibilities

- Create and read user accounts.
- Authenticate users.
- Manage sessions or tokens.
- Distinguish real users, admins, and synthetic trader accounts where needed for API views.
- Enforce admin permissions for admin-only endpoints.

## Boundaries

- May write user, session, and role records.
- Must not mutate portfolio cash, holdings, trades, or asset prices.
- Synthetic trader strategy configuration belongs to the worker service, not this module.
