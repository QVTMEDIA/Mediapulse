"""Shared test-fixture helper for the auth dependency introduced in Phase 3.

Every router except app/routers/auth.py's register/login now sits behind
`Depends(get_current_user)` (directly, or via `require_role(...)`, which
wraps it). Rather than minting a real JWT per test, fixtures override the
`get_current_user` FastAPI dependency directly with a fixed in-memory
UserRecord — the same pattern already used for repository overrides
elsewhere in this test suite (see e.g. tests/test_matches.py).

Overriding `get_current_user` this way also satisfies `require_role(...)`
gated routes: `require_role` returns a closure whose own sub-dependency is
`Depends(get_current_user)`, so FastAPI substitutes this override there too
— the closure's role check then runs for real against whatever role is set
on the returned UserRecord, so passing role='member' still gets a real 403
from an owner/admin-only route.
"""

from datetime import datetime, timezone

from app.repositories.users import UserRecord


def make_test_user(role: str = 'owner', user_id: str = 'test-user-id', email: str = 'test@example.com') -> UserRecord:
    return UserRecord(
        id=user_id,
        email=email,
        display_name='Test User',
        password_hash=None,
        role=role,
        created_at=datetime.now(timezone.utc),
    )
