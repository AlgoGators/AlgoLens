"""Configuration management for trading parameters.

This service enforces the anti-dead-knob rule: parameters may only be overridden
if they are present in the engine's published config (trading.config_manifest).
Validation also prevents any override of database or credential fields.

The form is rendered from what the ENGINE PUBLISHES, never from a list this repo
maintains. If a parameter is not in the manifest, the engine does not read it,
and it must not appear in the UI.
"""

import json
from numbers import Real


class ConfigValidationError(Exception):
    """Invalid override attempt. Maps to HTTP 400."""


# Credential field markers that must never appear in overrides, at any depth.
FORBIDDEN_KEYS = frozenset(
    {
        "password",
        "secret",
        "token",
        "api_key",
        "private_key",
        "auth",
        "credential",
        "host",
        "port",
        "user",
        "username",
    }
)

# Top-level sections that should never be overridden.
FORBIDDEN_SECTIONS = frozenset(
    {
        "database",
    }
)


def _contains_forbidden_key(key):
    """Check if a key contains any forbidden markers."""
    key_lower = str(key).lower()
    for forbidden in FORBIDDEN_KEYS:
        if forbidden in key_lower:
            return True
    return False


def _is_type_match(override_value, effective_value):
    """Verify that override and effective values have compatible types.

    Python's bool is a subclass of int, so True would be accepted as an int.
    We must reject this: they are distinct types for the engine.
    """
    override_type = type(override_value)
    effective_type = type(effective_value)

    # Exact type match is always OK.
    if override_type == effective_type:
        return True

    # int is compatible with float (numbers.Real subclass hierarchy).
    if isinstance(effective_value, Real) and isinstance(override_value, Real):
        # But bool is not a number, even though bool is a subclass of int.
        if isinstance(override_value, bool) or isinstance(effective_value, bool):
            return False
        return True

    return False


def _validate_dict_against_schema(overrides_dict, effective_dict, path=""):
    """Recursively validate overrides against effective schema.

    Raises ConfigValidationError on any violation:
    - key not in effective (anti-dead-knob rule)
    - key is forbidden (database, password, etc.)
    - type mismatch between override and effective values
    """
    if not isinstance(overrides_dict, dict):
        raise ConfigValidationError(
            f"At {path or 'root'}: expected dict, got {type(overrides_dict).__name__}"
        )

    if not isinstance(effective_dict, dict):
        raise ConfigValidationError(
            f"At {path or 'root'}: effective config is not a dict"
        )

    for key, override_value in overrides_dict.items():
        current_path = f"{path}.{key}" if path else key

        # Reject forbidden keys.
        if _contains_forbidden_key(key):
            raise ConfigValidationError(
                f"Override of '{current_path}' is forbidden: credential fields "
                f"may not be overridden"
            )

        # Anti-dead-knob rule: reject keys not in effective.
        if key not in effective_dict:
            raise ConfigValidationError(
                f"Override key '{current_path}' is not present in the engine's "
                f"published config. The engine does not read this parameter."
            )

        effective_value = effective_dict[key]

        # If both are dicts, recurse. Otherwise, check type match.
        if isinstance(override_value, dict) and isinstance(effective_value, dict):
            _validate_dict_against_schema(override_value, effective_value, current_path)
        else:
            # Type mismatch is a hard error.
            if not _is_type_match(override_value, effective_value):
                raise ConfigValidationError(
                    f"Type mismatch at '{current_path}': override is "
                    f"{type(override_value).__name__}, effective is "
                    f"{type(effective_value).__name__}"
                )


def validate_overrides(overrides, effective):
    """Normalize and validate a proposed config override.

    Args:
        overrides: dict of parameter overrides proposed by the caller.
        effective: dict of parameters the engine actually reads (from manifest).

    Returns:
        The overrides dict, validated.

    Raises:
        ConfigValidationError if:
        - overrides or effective is None
        - any override key is absent from effective (anti-dead-knob rule)
        - any override key is forbidden (database, password, etc.)
        - a value's type does not match the effective value's type
    """
    if overrides is None:
        raise ConfigValidationError("Overrides must not be null")

    if effective is None:
        raise ConfigValidationError(
            "Engine has not published a config yet (manifest is empty)"
        )

    if not isinstance(overrides, dict):
        raise ConfigValidationError(
            f"Overrides must be a dict, not {type(overrides).__name__}"
        )

    # Reject any attempt to override the entire database section.
    if "database" in overrides:
        raise ConfigValidationError("Override of 'database' section is forbidden")

    # Validate each override against the effective schema.
    _validate_dict_against_schema(overrides, effective)

    return overrides


def get_effective_config(cursor, portfolio_id):
    """The newest manifest row's effective config, or None if unpublished.

    Returns the 'effective' JSONB column from the most recent row in
    trading.config_manifest for this portfolio, or None if the engine has
    never published a config yet.

    **None must be distinguishable from an empty config.** The caller must
    say "engine has not published yet" rather than showing an empty form.
    """
    cursor.execute(
        """
        SELECT effective FROM trading.config_manifest
        WHERE portfolio_id = %s
        ORDER BY published_at DESC
        LIMIT 1
        """,
        (portfolio_id,),
    )
    row = cursor.fetchone()
    if row is None:
        return None
    return row["effective"]


def get_active_overrides(cursor, portfolio_id):
    """The active strategy_config row for this portfolio, or None.

    Returns the dict-like row from trading.strategy_config where is_active=true,
    or None if no active version exists.
    """
    cursor.execute(
        """
        SELECT id, version, overrides, reason, created_by, created_at
        FROM trading.strategy_config
        WHERE portfolio_id = %s AND is_active = true
        LIMIT 1
        """,
        (portfolio_id,),
    )
    return cursor.fetchone()


def get_config_history(cursor, portfolio_id, limit=50):
    """All versions of the config for this portfolio, newest first.

    Returns a list of dicts with id, version, overrides, reason, created_by,
    created_at, is_active. Newest rows come first.
    """
    cursor.execute(
        """
        SELECT id, version, overrides, reason, created_by, created_at, is_active
        FROM trading.strategy_config
        WHERE portfolio_id = %s
        ORDER BY created_at DESC
        LIMIT %s
        """,
        (portfolio_id, limit),
    )
    return cursor.fetchall()


def create_version(conn, portfolio_id, overrides, reason, user_id):
    """Create a new config version and make it active.

    Inserts a new row into trading.strategy_config with version = max+1 for
    this portfolio, and sets is_active = true. Deactivates any previous active
    row in the same transaction to maintain the invariant: at most one active
    row per portfolio.

    Args:
        conn: psycopg2 connection (must support transactions)
        portfolio_id: the portfolio this config applies to
        overrides: validated overrides dict
        reason: human-readable explanation for this version
        user_id: the user creating this version

    Returns:
        A dict with version, created_at, and other row metadata.

    Raises:
        ConfigValidationError if validation fails.
    """
    with conn.cursor() as cursor:
        # Get the max version for this portfolio.
        cursor.execute(
            """
            SELECT COALESCE(MAX(version), 0) as max_version
            FROM trading.strategy_config
            WHERE portfolio_id = %s
            """,
            (portfolio_id,),
        )
        row = cursor.fetchone()
        next_version = (row["max_version"] or 0) + 1

        # Deactivate the current active row (if any).
        cursor.execute(
            """
            UPDATE trading.strategy_config
            SET is_active = false
            WHERE portfolio_id = %s AND is_active = true
            """,
            (portfolio_id,),
        )

        # Insert the new active row.
        cursor.execute(
            """
            INSERT INTO trading.strategy_config
            (portfolio_id, version, overrides, reason, created_by, is_active, created_at)
            VALUES (%s, %s, %s, %s, %s, true, now())
            RETURNING id, version, overrides, reason, created_by, is_active, created_at
            """,
            # json.dumps, not the dict itself: psycopg2 cannot adapt a dict to
            # JSONB and raises "can't adapt type 'dict'" at execute time. The
            # unit tests here are pure-function and never reach the driver, so
            # this only shows up against a real database.
            (portfolio_id, next_version, json.dumps(overrides), reason, user_id),
        )
        row = cursor.fetchone()

    conn.commit()
    return dict(row) if row else {}


def activate_version(conn, portfolio_id, version, reason, user_id):
    """Revert to an earlier version by creating a new row copying its overrides.

    Does NOT flip is_active back on the old row. Instead, fetches the overrides
    from the historical row and inserts a new row as the active one, preserving
    the append-only audit trail.

    Args:
        conn: psycopg2 connection
        portfolio_id: the portfolio this config applies to
        version: the historical version number to reactivate
        reason: explanation for reverting (e.g. "Reverting to v5")
        user_id: the user making this revert

    Returns:
        A dict with the newly created row's metadata.

    Raises:
        ConfigValidationError if the version does not exist.
    """
    with conn.cursor() as cursor:
        # Fetch the historical row.
        cursor.execute(
            """
            SELECT overrides FROM trading.strategy_config
            WHERE portfolio_id = %s AND version = %s
            """,
            (portfolio_id, version),
        )
        row = cursor.fetchone()
        if row is None:
            raise ConfigValidationError(
                f"Version {version} does not exist for portfolio {portfolio_id}"
            )

        old_overrides = row["overrides"]

        # Get the next version number.
        cursor.execute(
            """
            SELECT COALESCE(MAX(version), 0) as max_version
            FROM trading.strategy_config
            WHERE portfolio_id = %s
            """,
            (portfolio_id,),
        )
        max_row = cursor.fetchone()
        next_version = (max_row["max_version"] or 0) + 1

        # Deactivate the current active row.
        cursor.execute(
            """
            UPDATE trading.strategy_config
            SET is_active = false
            WHERE portfolio_id = %s AND is_active = true
            """,
            (portfolio_id,),
        )

        # Insert a new row copying the old overrides.
        cursor.execute(
            """
            INSERT INTO trading.strategy_config
            (portfolio_id, version, overrides, reason, created_by, is_active, created_at)
            VALUES (%s, %s, %s, %s, %s, true, now())
            RETURNING id, version, overrides, reason, created_by, is_active, created_at
            """,
            # Same dict-to-JSONB adaptation as create_version above.
            (portfolio_id, next_version, json.dumps(old_overrides), reason, user_id),
        )
        new_row = cursor.fetchone()

    conn.commit()
    return dict(new_row) if new_row else {}
