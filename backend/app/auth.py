import asyncio
import os
from dataclasses import dataclass
from pathlib import Path

import jwt
from dotenv import load_dotenv
from fastapi import Header, HTTPException
from jwt import InvalidTokenError, PyJWKClient, PyJWKClientConnectionError


load_dotenv()
load_dotenv(Path(__file__).resolve().parents[2] / ".env")


ASYMMETRIC_ALGORITHMS = frozenset({"ES256", "RS256"})
jwks_clients: dict[str, PyJWKClient] = {}


@dataclass
class CurrentUser:
    id: str
    email: str | None


def get_supabase_url():
    return (
        os.getenv("SUPABASE_URL")
        or os.getenv("EXPO_PUBLIC_SUPABASE_URL")
        or ""
    ).rstrip("/")


def get_jwks_client(supabase_url: str):
    client = jwks_clients.get(supabase_url)

    if client is None:
        client = PyJWKClient(
            f"{supabase_url}/auth/v1/.well-known/jwks.json",
            cache_keys=True,
            max_cached_keys=16,
            cache_jwk_set=True,
            lifespan=600,
            timeout=5,
        )
        jwks_clients[supabase_url] = client

    return client


def get_bearer_token(authorization: str | None):
    if not authorization:
        raise HTTPException(status_code=401, detail="Authentication required")

    parts = authorization.split(" ", 1)

    if len(parts) != 2 or parts[0].lower() != "bearer" or not parts[1].strip():
        raise HTTPException(status_code=401, detail="Invalid authorization header")

    return parts[1].strip()


async def verify_access_token(token: str):
    supabase_url = get_supabase_url()

    if not supabase_url:
        raise HTTPException(
            status_code=503,
            detail="Supabase authentication is not configured",
        )

    issuer = f"{supabase_url}/auth/v1"
    audience = os.getenv("SUPABASE_JWT_AUDIENCE", "authenticated")

    try:
        algorithm = jwt.get_unverified_header(token).get("alg")

        if algorithm in ASYMMETRIC_ALGORITHMS:
            signing_key = await asyncio.to_thread(
                get_jwks_client(supabase_url).get_signing_key_from_jwt,
                token,
            )
            key = signing_key.key
            algorithms = [algorithm]
        elif algorithm == "HS256":
            key = os.getenv("SUPABASE_JWT_SECRET")

            if not key:
                raise HTTPException(
                    status_code=503,
                    detail="Legacy JWT verification is not configured",
                )

            algorithms = ["HS256"]
        else:
            raise HTTPException(status_code=401, detail="Unsupported access token")

        return jwt.decode(
            token,
            key,
            algorithms=algorithms,
            audience=audience,
            issuer=issuer,
            options={
                "require": ["sub", "exp", "iat", "aud", "iss"],
            },
        )
    except HTTPException:
        raise
    except PyJWKClientConnectionError as error:
        raise HTTPException(
            status_code=503,
            detail="Authentication keys are temporarily unavailable",
        ) from error
    except InvalidTokenError as error:
        raise HTTPException(
            status_code=401,
            detail="Session expired or invalid",
        ) from error


async def get_current_user(
    authorization: str | None = Header(default=None),
) -> CurrentUser:
    token = get_bearer_token(authorization)
    claims = await verify_access_token(token)
    user_id = claims.get("sub")

    if (
        not isinstance(user_id, str)
        or not user_id
        or claims.get("role") != "authenticated"
    ):
        raise HTTPException(status_code=401, detail="Session expired or invalid")

    return CurrentUser(
        id=user_id,
        email=claims.get("email"),
    )
