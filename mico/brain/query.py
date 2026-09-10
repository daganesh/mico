"""Declarative query-spec object (AD-04).

The "load-bearing piece" of the storage abstraction: a small, closed
vocabulary that `mico.logic` uses to describe *what* to fetch, so that
backends translate the spec themselves and never receive raw SQL (or any
other backend-specific query language).

Pure data structure only — no execution logic, no SQL, no dependency on
any storage backend. A future `MetadataStore` implementation pattern-matches
over `Condition` / `And` / `Or` / `QuerySpec` to build actual queries.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Union

Operator = Literal["eq", "ne", "lt", "gt", "in", "contains", "is_null"]
Direction = Literal["asc", "desc"]

_OPERATORS: frozenset[str] = frozenset({"eq", "ne", "lt", "gt", "in", "contains", "is_null"})


@dataclass(frozen=True)
class Condition:
    """A single field/operator/value predicate.

    `value` is ignored for the `is_null` operator, which tests for
    NULL/absence and needs no comparison value.
    """

    field: str
    operator: Operator
    value: object = None

    def __post_init__(self) -> None:
        if self.operator not in _OPERATORS:
            raise ValueError(
                f"Unsupported operator {self.operator!r}; must be one of {sorted(_OPERATORS)}"
            )


# A predicate is either a leaf Condition or a boolean combination of predicates.
Predicate = Union[Condition, "And", "Or"]


@dataclass(frozen=True, init=False)
class And:
    """All of `conditions` must hold. Each may itself be a `Condition`, `And`, or `Or`."""

    conditions: tuple[Predicate, ...]

    def __init__(self, *conditions: Predicate) -> None:
        object.__setattr__(self, "conditions", tuple(conditions))


@dataclass(frozen=True, init=False)
class Or:
    """At least one of `conditions` must hold. Each may itself be a `Condition`, `And`, or `Or`."""

    conditions: tuple[Predicate, ...]

    def __init__(self, *conditions: Predicate) -> None:
        object.__setattr__(self, "conditions", tuple(conditions))


@dataclass(frozen=True)
class QuerySpec:
    """A declarative description of a query, translated by each backend.

    No filter means "all rows". `order_by` is applied in list order
    (primary sort first).
    """

    filter: Predicate | None = None
    order_by: list[tuple[str, Direction]] = field(default_factory=list)
    limit: int | None = None
    offset: int | None = None
