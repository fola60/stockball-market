from __future__ import annotations

import hashlib
import re
import secrets
import unicodedata
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.accounts.models import AccountStatus, AccountType
from app.accounts.repository import AccountAlreadyExistsError
from app.auth.models import AuthenticatedSession, CurrentPrincipal
from app.auth.passwords import hash_password, verify_password
from app.auth.repository import AuthRepository


class InvalidCredentialsError(Exception):
    pass


class InvalidSessionError(Exception):
    pass


class AccountUnavailableError(Exception):
    pass


class AuthService:
    def __init__(
        self,
        repository: AuthRepository,
        *,
        opening_balance: Decimal,
        session_ttl: timedelta = timedelta(days=7),
    ) -> None:
        self._repository = repository
        self._opening_balance = opening_balance
        self._session_ttl = session_ttl

    def register(self, *, display_name: str, email: str, password: str) -> AuthenticatedSession:
        password_hash = hash_password(password)
        for attempt in range(3):
            try:
                account = self._repository.register_user(
                    handle=_generated_handle(display_name),
                    display_name=display_name,
                    email=email.lower(),
                    password_hash=password_hash,
                    opening_balance=self._opening_balance,
                )
                break
            except AccountAlreadyExistsError as exc:
                if exc.field_name != "handle" or attempt == 2:
                    raise
        return self._new_session(account.id)

    def login(self, *, email: str, password: str) -> AuthenticatedSession:
        credential = self._repository.get_credential_by_email(email.lower())
        if credential is None or not verify_password(password, credential.password_hash):
            raise InvalidCredentialsError("email or password is incorrect")
        self._assert_account_available(credential.account.status, credential.account.account_type)
        return self._new_session(credential.account.id)

    def authenticate(self, token: str) -> CurrentPrincipal:
        session = self._repository.get_session(_token_hash(token), datetime.now(UTC))
        if session is None:
            raise InvalidSessionError("session is invalid or expired")
        self._assert_account_available(session.account.status, session.account.account_type)
        return CurrentPrincipal(
            account_id=session.account.id,
            portfolio_id=session.account.portfolio.id,
            account_type=session.account.account_type,
            session_id=session.id,
        )

    def logout(self, token: str) -> None:
        self._repository.revoke_session(_token_hash(token))

    def _new_session(self, account_id) -> AuthenticatedSession:
        token = secrets.token_urlsafe(32)
        expires_at = datetime.now(UTC) + self._session_ttl
        session = self._repository.create_session(account_id, _token_hash(token), expires_at)
        return AuthenticatedSession(token=token, expires_at=expires_at, account=session.account)

    @staticmethod
    def _assert_account_available(status: AccountStatus, account_type: AccountType) -> None:
        if status is not AccountStatus.ACTIVE or account_type is not AccountType.USER:
            raise AccountUnavailableError("account is not permitted to sign in")


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _generated_handle(display_name: str) -> str:
    ascii_name = unicodedata.normalize("NFKD", display_name).encode("ascii", "ignore").decode()
    base = re.sub(r"[^a-z0-9]+", "-", ascii_name.lower()).strip("-") or "player"
    return f"{base[:54].rstrip('-')}-{secrets.token_hex(4)}"
