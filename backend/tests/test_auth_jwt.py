import os
import unittest
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

import jwt
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import HTTPException

from app import auth


SUPABASE_URL = "https://project.supabase.co"
ISSUER = f"{SUPABASE_URL}/auth/v1"


def token_claims():
    now = datetime.now(UTC)
    return {
        "sub": "user-1",
        "email": "user@example.com",
        "role": "authenticated",
        "aud": "authenticated",
        "iss": ISSUER,
        "iat": now,
        "exp": now + timedelta(minutes=5),
    }


class AuthenticationTests(unittest.IsolatedAsyncioTestCase):
    async def test_hs256_token_is_verified_locally(self):
        secret = "a-production-secret-with-enough-entropy"
        token = jwt.encode(token_claims(), secret, algorithm="HS256")

        with patch.dict(
            os.environ,
            {
                "SUPABASE_URL": SUPABASE_URL,
                "SUPABASE_JWT_SECRET": secret,
            },
        ):
            user = await auth.get_current_user(f"Bearer {token}")

        self.assertEqual(user.id, "user-1")
        self.assertEqual(user.email, "user@example.com")

    async def test_es256_token_uses_cached_public_key(self):
        private_key = ec.generate_private_key(ec.SECP256R1())
        public_key = private_key.public_key()
        token = jwt.encode(
            token_claims(),
            private_key,
            algorithm="ES256",
            headers={"kid": "key-1"},
        )
        jwks_client = SimpleNamespace(
            get_signing_key_from_jwt=lambda _token: SimpleNamespace(key=public_key)
        )

        with (
            patch.dict(os.environ, {"SUPABASE_URL": SUPABASE_URL}),
            patch.object(auth, "get_jwks_client", return_value=jwks_client),
        ):
            user = await auth.get_current_user(f"Bearer {token}")

        self.assertEqual(user.id, "user-1")

    async def test_wrong_audience_is_rejected(self):
        secret = "a-production-secret-with-enough-entropy"
        claims = token_claims()
        claims["aud"] = "wrong"
        token = jwt.encode(claims, secret, algorithm="HS256")

        with patch.dict(
            os.environ,
            {
                "SUPABASE_URL": SUPABASE_URL,
                "SUPABASE_JWT_SECRET": secret,
            },
        ):
            with self.assertRaises(HTTPException) as raised:
                await auth.get_current_user(f"Bearer {token}")

        self.assertEqual(raised.exception.status_code, 401)

    async def test_non_user_role_is_rejected(self):
        secret = "a-production-secret-with-enough-entropy"
        claims = token_claims()
        claims["role"] = "service_role"
        token = jwt.encode(claims, secret, algorithm="HS256")

        with patch.dict(
            os.environ,
            {
                "SUPABASE_URL": SUPABASE_URL,
                "SUPABASE_JWT_SECRET": secret,
            },
        ):
            with self.assertRaises(HTTPException) as raised:
                await auth.get_current_user(f"Bearer {token}")

        self.assertEqual(raised.exception.status_code, 401)


if __name__ == "__main__":
    unittest.main()
