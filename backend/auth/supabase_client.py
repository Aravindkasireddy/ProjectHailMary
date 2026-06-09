# backend/auth/supabase_client.py

"""Supabase client utilities moved to backend package."""

import os
import json
import time
import jwt
import requests
from typing import Union
from supabase import create_client, Client
from dotenv import load_dotenv
from jobsearch_paths import workspace_root

# Load env variables
load_dotenv(dotenv_path=os.path.join(workspace_root(), ".env"))

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
SUPABASE_JWT_SECRET = os.environ.get("SUPABASE_JWT_SECRET")
SUPABASE_ANON_KEY = os.environ.get("SUPABASE_ANON_KEY")

# Cached client
_supabase_client: Union[Client, None] = None

def get_supabase_client() -> Client:
    """Return a cached Supabase client, creating it if necessary."""
    global _supabase_client
    if _supabase_client is not None:
        return _supabase_client
    if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
        raise ValueError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set in .env")
    _supabase_client = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)
    return _supabase_client

# JWKS cache for JWT verification
_jwks_cache = None
_jwks_last_fetch = 0

def get_jwks_keys():
    """Fetch and cache JWKS keys from Supabase for up to 1 hour."""
    global _jwks_cache, _jwks_last_fetch
    # Cache for 1 hour
    if _jwks_cache is not None and (time.time() - _jwks_last_fetch) < 3600:
        return _jwks_cache
    try:
        if not SUPABASE_URL:
            return None
        apikey = SUPABASE_SERVICE_ROLE_KEY or SUPABASE_ANON_KEY
        headers = {"apikey": apikey} if apikey else {}
        res = requests.get(
            f"{SUPABASE_URL}/auth/v1/.well-known/jwks.json",
            headers=headers,
            timeout=5,
        )
        if res.status_code == 200:
            _jwks_cache = res.json().get("keys", [])
            _jwks_last_fetch = time.time()
            return _jwks_cache
    except Exception as e:
        print(f"Error fetching JWKS keys: {e}")
    return None

def verify_supabase_jwt(token: str) -> Union[dict, None]:
    """Verify a Supabase JWT, supporting asymmetric (ES256/RS256) and fallback HS256."""
    try:
        unverified_header = jwt.get_unverified_header(token)
        alg = unverified_header.get("alg")
        kid = unverified_header.get("kid")
    except Exception as e:
        print(f"Failed to parse JWT header: {e}")
        return None

    # Asymmetric verification using JWKS
    if alg in ["ES256", "RS256"] and kid:
        keys = get_jwks_keys()
        if keys:
            for key in keys:
                if key.get("kid") == kid:
                    try:
                        pub_key = None
                        if key.get("kty") == "EC":
                            from jwt.algorithms import ECAlgorithm
                            pub_key = ECAlgorithm.from_jwk(key)
                        elif key.get("kty") == "RSA":
                            from jwt.algorithms import RSAAlgorithm
                            pub_key = RSAAlgorithm.from_jwk(key)
                        if pub_key:
                            payload = jwt.decode(
                                token,
                                pub_key,
                                algorithms=[alg],
                                options={"verify_aud": False},
                            )
                            return payload
                    except Exception as e:
                        print(f"Failed decoding asymmetric token with kid {kid}: {e}")

    # Symmetric fallback (HS256) using Supabase JWT secret
    if not SUPABASE_JWT_SECRET:
        print("ERROR: SUPABASE_JWT_SECRET is not set in environment.")
        return None
    try:
        payload = jwt.decode(
            token,
            SUPABASE_JWT_SECRET,
            algorithms=["HS256"],
            options={"verify_aud": False},
        )
        return payload
    except jwt.ExpiredSignatureError:
        print("JWT Token expired")
        return None
    except jwt.InvalidTokenError as e:
        print(f"Invalid JWT Token: {e}")
        return None
