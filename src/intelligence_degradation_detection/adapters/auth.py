"""Manage an operator-owned YAML token and revocable signed sessions."""

import hashlib
import hmac
import os
import secrets
from pathlib import Path

import yaml
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ..domain.models import DomainError


class AuthDocument(BaseModel):
    """Validate persisted secrets without silently repairing a damaged file."""

    model_config = ConfigDict(extra="forbid")
    access_token: str = Field(min_length=24, max_length=512)
    session_secret: str = Field(min_length=32)


class TokenAuth:
    """Own token storage and invalidate every session during token rotation."""

    def __init__(self, path: Path) -> None:
        """Load an existing token or exclusively create it on first startup."""
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            initial = AuthDocument(
                access_token=secrets.token_urlsafe(32),
                session_secret=secrets.token_urlsafe(48),
            )
            try:
                descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            except FileExistsError:
                pass
            else:
                with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                    yaml.safe_dump(initial.model_dump(), handle)
        try:
            self.document = AuthDocument.model_validate(
                yaml.safe_load(path.read_text(encoding="utf-8"))
            )
            # Validate write access without modifying an existing operator-owned token.
            descriptor = os.open(path, os.O_WRONLY)
            os.close(descriptor)
        except OSError as exc:
            raise RuntimeError(
                "The authentication file must be readable and writable."
            ) from exc
        except (ValueError, ValidationError, yaml.YAMLError) as exc:
            raise RuntimeError(
                "Invalid authentication YAML; repair it explicitly."
            ) from exc
        self.signer = URLSafeTimedSerializer(
            self.document.session_secret, salt="idd-session-v1"
        )

    def login(self, token: str) -> str:
        """Issue a session only after a constant-time token comparison."""
        if not hmac.compare_digest(token.encode(), self.document.access_token.encode()):
            raise DomainError("unauthorized", "Invalid access token.", 401)
        return self.signer.dumps(
            {"revision": self._revision(), "nonce": secrets.token_hex(16)}
        )

    def _revision(self) -> str:
        return hashlib.sha256(self.document.access_token.encode()).hexdigest()

    def verify(self, session: str | None) -> bool:
        """Validate session age and its current token revision."""
        if not session:
            return False
        try:
            value = self.signer.loads(session, max_age=7 * 86400)
        except (BadSignature, SignatureExpired):
            return False
        return isinstance(value, dict) and hmac.compare_digest(
            str(value.get("revision", "")), self._revision()
        )

    def rotate(self, token: str) -> None:
        """Atomically replace the token and signing key, revoking old sessions."""
        document = AuthDocument(
            access_token=token, session_secret=secrets.token_urlsafe(48)
        )
        temporary = self.path.with_name(f".auth-{secrets.token_hex(8)}.tmp")
        try:
            descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                yaml.safe_dump(document.model_dump(), handle)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        finally:
            temporary.unlink(missing_ok=True)
        self.document = document
        self.signer = URLSafeTimedSerializer(
            document.session_secret, salt="idd-session-v1"
        )
