from __future__ import annotations

import hashlib
import re


_AUTH_PARAM_RE = re.compile(r'(\w+)=("([^"]*)"|([^,\s]+))')


def parse_www_authenticate(value: str) -> dict[str, str]:
    if value.lower().startswith("digest "):
        value = value[7:]
    params: dict[str, str] = {}
    for match in _AUTH_PARAM_RE.finditer(value):
        params[match.group(1).lower()] = match.group(3) or match.group(4) or ""
    return params


def build_digest_authorization(
    username: str,
    password: str,
    method: str,
    uri: str,
    challenge: dict[str, str],
) -> str:
    realm = challenge.get("realm", "")
    nonce = challenge.get("nonce", "")
    algorithm = challenge.get("algorithm", "MD5") or "MD5"
    ha1 = _md5(f"{username}:{realm}:{password}")
    ha2 = _md5(f"{method}:{uri}")
    response = _md5(f"{ha1}:{nonce}:{ha2}")
    return (
        f'Digest username="{username}", realm="{realm}", nonce="{nonce}", '
        f'uri="{uri}", response="{response}", algorithm={algorithm}'
    )


def _md5(value: str) -> str:
    return hashlib.md5(value.encode("utf-8")).hexdigest()
