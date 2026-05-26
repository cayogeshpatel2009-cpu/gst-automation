from __future__ import annotations

import secrets


def new_trace_id() -> str:
    return secrets.token_hex(16)


def new_correlation_id() -> str:
    return secrets.token_hex(16)


def new_run_id() -> str:
    return secrets.token_hex(16)

