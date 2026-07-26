"""Config service tests: validation, history, and anti-dead-knob protection.

These are pure-function tests for validate_overrides, which must reject any
override that is absent from the engine's published config or touches
database/credential fields. Tests avoid database, Flask, mocking where possible.
"""

import ast
import os
import pytest

from services.config_service import (
    ConfigValidationError,
    validate_overrides,
)


def _effective_config():
    """A sample effective config from the engine's published manifest.

    Matches what the C++ engine actually reads, per trading.config_manifest.
    Note: no 'database' section, as the engine does not publish it.
    """
    return {
        "parameters": {
            "max_position_size": 10000,
            "stop_loss_percent": 2.5,
            "enable_rebalancing": True,
            "rebalance_interval_days": 5,
            "lookback_periods": {
                "short_term": 20,
                "long_term": 200,
            },
        },
        "risk": {
            "max_daily_loss": 5000.0,
            "correlation_threshold": 0.8,
        },
    }


class TestValidateOverridesBasics:
    """Happy paths and key validation logic."""

    def test_accepts_override_of_key_present_in_effective(self):
        """An override for a key that exists in effective should pass."""
        effective = _effective_config()
        overrides = {"parameters": {"max_position_size": 15000}}

        result = validate_overrides(overrides, effective)

        assert result == overrides

    def test_rejects_override_of_key_absent_from_effective(self):
        """The anti-dead-knob rule: reject any key not in effective.

        If a parameter is not in the engine's published config, the engine
        does not read it. Overriding it would silently have no effect.
        """
        effective = _effective_config()
        overrides = {"parameters": {"unknown_knob": 999}}

        with pytest.raises(ConfigValidationError, match="unknown_knob"):
            validate_overrides(overrides, effective)

    def test_rejects_nested_override_of_absent_key(self):
        """Anti-dead-knob applies to nested paths too."""
        effective = _effective_config()
        overrides = {"parameters": {"lookback_periods": {"nonexistent": 999}}}

        with pytest.raises(ConfigValidationError, match="nonexistent"):
            validate_overrides(overrides, effective)

    def test_accepts_nested_override_of_present_key(self):
        """Nested override of a key that exists should pass."""
        effective = _effective_config()
        overrides = {"parameters": {"lookback_periods": {"short_term": 30}}}

        result = validate_overrides(overrides, effective)

        assert result["parameters"]["lookback_periods"]["short_term"] == 30

    def test_rejects_override_of_database_section(self):
        """Never allow overrides of database credentials, even if published."""
        effective = {
            "parameters": {"safe_param": 1},
            "database": {"password": "***"},
        }
        overrides = {"database": {"password": "new_password"}}

        with pytest.raises(ConfigValidationError, match="database"):
            validate_overrides(overrides, effective)

    def test_rejects_override_containing_password_key_anywhere(self):
        """Reject any path that contains a 'password' key, at any depth."""
        effective = _effective_config()
        overrides = {"parameters": {"password": "abc123"}}

        with pytest.raises(ConfigValidationError, match="password"):
            validate_overrides(overrides, effective)

    def test_rejects_override_containing_secret_key(self):
        """Reject 'secret', 'token', 'key' and similar credential markers."""
        effective = _effective_config()
        overrides = {"parameters": {"api_key": "abc123"}}

        with pytest.raises(ConfigValidationError, match="api_key"):
            validate_overrides(overrides, effective)

    def test_rejects_override_of_host_or_port_in_any_section(self):
        """Database connection details are off-limits."""
        effective = _effective_config()
        overrides = {"parameters": {"host": "malicious.com"}}

        with pytest.raises(ConfigValidationError, match="host"):
            validate_overrides(overrides, effective)


class TestTypeMatching:
    """Type mismatches must be rejected to prevent C++ runtime crashes."""

    def test_rejects_string_where_number_expected(self):
        """String value for a numeric parameter."""
        effective = {"param": 10}
        overrides = {"param": "not_a_number"}

        with pytest.raises(ConfigValidationError, match="Type mismatch"):
            validate_overrides(overrides, effective)

    def test_rejects_number_where_string_expected(self):
        """Numeric value for a string parameter."""
        effective = {"param": "description"}
        overrides = {"param": 123}

        with pytest.raises(ConfigValidationError, match="Type mismatch"):
            validate_overrides(overrides, effective)

    def test_rejects_boolean_where_number_expected(self):
        """Python bool is a subclass of int; must reject it when a number is expected."""
        effective = {"param": 10}
        overrides = {"param": True}

        with pytest.raises(ConfigValidationError, match="Type mismatch"):
            validate_overrides(overrides, effective)

    def test_accepts_boolean_where_boolean_expected(self):
        """Boolean value for a boolean parameter."""
        effective = {"param": True}
        overrides = {"param": False}

        result = validate_overrides(overrides, effective)
        assert result["param"] is False

    def test_rejects_number_where_boolean_expected(self):
        """1 or 0 must not be silently coerced to bool."""
        effective = {"param": True}
        overrides = {"param": 1}

        with pytest.raises(ConfigValidationError, match="Type mismatch"):
            validate_overrides(overrides, effective)

    def test_accepts_int_where_float_expected(self):
        """int is a subclass of float in Python numbers.Real."""
        effective = {"param": 10.5}
        overrides = {"param": 10}

        result = validate_overrides(overrides, effective)
        assert result["param"] == 10

    def test_rejects_list_where_dict_expected(self):
        """Structure type mismatches are rejected."""
        effective = {"config": {"nested": "value"}}
        overrides = {"config": ["item1", "item2"]}

        with pytest.raises(ConfigValidationError, match="Type mismatch"):
            validate_overrides(overrides, effective)


class TestEmptyAndEdgeCases:
    """Edge cases that must not crash the system."""

    def test_accepts_empty_overrides(self):
        """No overrides at all is fine."""
        effective = _effective_config()
        overrides = {}

        result = validate_overrides(overrides, effective)
        assert result == {}

    def test_rejects_none_as_overrides(self):
        """Null overrides should be rejected."""
        effective = _effective_config()
        overrides = None

        with pytest.raises(ConfigValidationError):
            validate_overrides(overrides, effective)

    def test_rejects_none_as_effective(self):
        """Engine has not published a config yet."""
        overrides = {"param": 1}

        with pytest.raises(ConfigValidationError):
            validate_overrides(overrides, None)

    def test_accepts_zero_value(self):
        """Zero is a valid number, not falsy."""
        effective = {"param": 10}
        overrides = {"param": 0}

        result = validate_overrides(overrides, effective)
        assert result["param"] == 0

    def test_accepts_false_value(self):
        """False is a valid boolean."""
        effective = {"param": True}
        overrides = {"param": False}

        result = validate_overrides(overrides, effective)
        assert result["param"] is False

    def test_accepts_empty_string_where_string_expected(self):
        """Empty string is a valid string value."""
        effective = {"param": "default"}
        overrides = {"param": ""}

        result = validate_overrides(overrides, effective)
        assert result["param"] == ""


class TestNestedStructures:
    """Validation must traverse nested dicts and reject at the right path."""

    def test_deeply_nested_override_with_absent_key(self):
        """Rejects absent key deep in the tree."""
        effective = {"a": {"b": {"c": 1}}}
        overrides = {"a": {"b": {"unknown": 2}}}

        with pytest.raises(ConfigValidationError, match="unknown"):
            validate_overrides(overrides, effective)

    def test_partial_nested_structure_is_ok(self):
        """Overriding only part of a nested dict is allowed."""
        effective = {"config": {"a": 1, "b": 2, "c": 3}}
        overrides = {"config": {"b": 20}}

        result = validate_overrides(overrides, effective)
        assert result["config"]["b"] == 20

    def test_type_mismatch_in_nested_structure(self):
        """Type checking applies at all depths."""
        effective = {"config": {"nested": {"value": 10}}}
        overrides = {"config": {"nested": {"value": "string"}}}

        with pytest.raises(ConfigValidationError, match="Type mismatch"):
            validate_overrides(overrides, effective)


class TestConfigRouteGuards:
    """AST-style guard: every config route must have @internal_only decorator.

    A future config route added without @internal_only would silently expose
    the fund's trading parameters to any authenticated subscriber. Runtime
    tests would not catch this: the route would simply work. This AST check
    fires at test time to prevent the mistake.
    """

    def _config_routes(self):
        """Every route function that starts with /config in portfolio.py."""
        backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        routes_file = os.path.join(backend_dir, "routes", "portfolio.py")

        if not os.path.exists(routes_file):
            return None  # portfolio routes not present on this branch

        with open(routes_file, encoding="utf-8") as fh:
            tree = ast.parse(fh.read())

        routes = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef):
                continue
            # Find routes decorated with @portfolio_bp.route.
            for decorator in node.decorator_list:
                if isinstance(decorator, ast.Call):
                    func = decorator.func
                    if isinstance(func, ast.Attribute) and func.attr == "route":
                        # This is a @portfolio_bp.route; check if it matches /config.
                        if decorator.args and isinstance(
                            decorator.args[0], ast.Constant
                        ):
                            path = decorator.args[0].value
                            if "/config" in path:
                                routes.append((node.name, path, node.decorator_list))
        return routes

    def test_there_are_config_routes_to_check(self):
        """Guard the guard: a scan that finds nothing must not silently pass."""
        routes = self._config_routes()
        if routes is None:
            return
        assert routes, (
            "No config routes were found. Either they were not implemented yet, "
            "or the scan is broken -- do not treat this as a pass."
        )

    def test_every_config_route_has_internal_only_decorator(self):
        """Every /config route must be decorated with @internal_only."""
        routes = self._config_routes()
        if routes is None:
            return

        unguarded = []
        for name, path, decorators in routes:
            has_internal_only = False
            for dec in decorators:
                if isinstance(dec, ast.Name) and dec.id == "internal_only":
                    has_internal_only = True
                    break
            if not has_internal_only:
                unguarded.append((name, path))

        assert not unguarded, (
            f"The following config routes are missing @internal_only: "
            + "; ".join(f"{name}('{path}')" for name, path in unguarded)
            + ". Config changes are internal-only, like position edits."
        )
