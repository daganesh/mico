"""Tests for the declarative query-spec object (M1.5, AD-04)."""

from __future__ import annotations

import pytest

from mico.brain.query import And, Condition, Operator, Or, QuerySpec


def test_simple_single_condition_spec() -> None:
    spec = QuerySpec(filter=Condition(field="status", operator="eq", value="active"))

    assert isinstance(spec.filter, Condition)
    assert spec.filter.field == "status"
    assert spec.filter.operator == "eq"
    assert spec.filter.value == "active"
    assert spec.order_by == []
    assert spec.limit is None
    assert spec.offset is None


def test_no_filter_means_all_rows() -> None:
    spec = QuerySpec()

    assert spec.filter is None


def test_nested_and_or_combination() -> None:
    spec = QuerySpec(
        filter=Or(
            And(
                Condition(field="status", operator="eq", value="active"),
                Condition(field="priority", operator="gt", value=2),
            ),
            Condition(field="owner", operator="is_null"),
        ),
        order_by=[("priority", "desc"), ("name", "asc")],
        limit=10,
        offset=20,
    )

    assert isinstance(spec.filter, Or)
    assert len(spec.filter.conditions) == 2

    nested_and = spec.filter.conditions[0]
    assert isinstance(nested_and, And)
    assert nested_and.conditions == (
        Condition(field="status", operator="eq", value="active"),
        Condition(field="priority", operator="gt", value=2),
    )

    tail_condition = spec.filter.conditions[1]
    assert isinstance(tail_condition, Condition)
    assert tail_condition.operator == "is_null"

    assert spec.order_by == [("priority", "desc"), ("name", "asc")]
    assert spec.limit == 10
    assert spec.offset == 20


@pytest.mark.parametrize(
    "operator,value",
    [
        ("eq", "x"),
        ("ne", "x"),
        ("lt", 1),
        ("gt", 1),
        ("in", ["a", "b"]),
        ("contains", "sub"),
        ("is_null", None),
    ],
)
def test_each_supported_operator_constructs(operator: Operator, value: object) -> None:
    condition = Condition(field="f", operator=operator, value=value)

    assert condition.operator == operator


def test_unsupported_operator_is_rejected() -> None:
    with pytest.raises(ValueError, match="Unsupported operator"):
        Condition(field="f", operator="like", value="%x%")  # type: ignore[arg-type]
