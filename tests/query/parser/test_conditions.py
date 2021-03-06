import pytest

from typing import Any, Sequence

from snuba.datasets.factory import get_dataset
from snuba.query.expressions import (
    Column,
    Expression,
    FunctionCall,
    Lambda,
    Literal,
    Argument,
)
from snuba.query.conditions import (
    ConditionFunctions,
    BooleanFunctions,
)
from snuba.query.parser.conditions import parse_conditions_to_expr
from snuba.util import tuplify

test_conditions = [
    ([], None,),
    ([[[]], []], None,),
    (
        [["a", "=", 1]],
        FunctionCall(
            None, ConditionFunctions.EQ, (Column(None, "a", None), Literal(None, 1))
        ),
    ),
    (
        [[["a", "=", 1]]],
        FunctionCall(
            None, ConditionFunctions.EQ, (Column(None, "a", None), Literal(None, 1))
        ),
    ),
    (
        [["a", "=", 1], ["b", "=", 2]],
        FunctionCall(
            None,
            BooleanFunctions.AND,
            (
                FunctionCall(
                    None,
                    ConditionFunctions.EQ,
                    (Column(None, "a", None), Literal(None, 1)),
                ),
                FunctionCall(
                    None,
                    ConditionFunctions.EQ,
                    (Column(None, "b", None), Literal(None, 2)),
                ),
            ),
        ),
    ),
    (
        [["a", "=", 1], ["b", "=", 2], ["c", "=", 3]],
        FunctionCall(
            None,
            BooleanFunctions.AND,
            (
                FunctionCall(
                    None,
                    ConditionFunctions.EQ,
                    (Column(None, "a", None), Literal(None, 1)),
                ),
                FunctionCall(
                    None,
                    BooleanFunctions.AND,
                    (
                        FunctionCall(
                            None,
                            ConditionFunctions.EQ,
                            (Column(None, "b", None), Literal(None, 2)),
                        ),
                        FunctionCall(
                            None,
                            ConditionFunctions.EQ,
                            (Column(None, "c", None), Literal(None, 3)),
                        ),
                    ),
                ),
            ),
        ),
    ),  # Odd number of conditions. Right associative expression
    (
        [[["a", "=", 1], ["b", "=", 2]]],
        FunctionCall(
            None,
            BooleanFunctions.OR,
            (
                FunctionCall(
                    None,
                    ConditionFunctions.EQ,
                    (Column(None, "a", None), Literal(None, 1)),
                ),
                FunctionCall(
                    None,
                    ConditionFunctions.EQ,
                    (Column(None, "b", None), Literal(None, 2)),
                ),
            ),
        ),
    ),
    (
        [[["a", "=", 1], ["b", "=", 2], ["c", "=", 3]]],
        FunctionCall(
            None,
            BooleanFunctions.OR,
            (
                FunctionCall(
                    None,
                    ConditionFunctions.EQ,
                    (Column(None, "a", None), Literal(None, 1)),
                ),
                FunctionCall(
                    None,
                    BooleanFunctions.OR,
                    (
                        FunctionCall(
                            None,
                            ConditionFunctions.EQ,
                            (Column(None, "b", None), Literal(None, 2)),
                        ),
                        FunctionCall(
                            None,
                            ConditionFunctions.EQ,
                            (Column(None, "c", None), Literal(None, 3)),
                        ),
                    ),
                ),
            ),
        ),
    ),  # Odd number of conditions. Right associative expression
    (
        [[["a", "=", 1], ["b", "=", 2]], ["c", "=", 3]],
        FunctionCall(
            None,
            BooleanFunctions.AND,
            (
                FunctionCall(
                    None,
                    BooleanFunctions.OR,
                    (
                        FunctionCall(
                            None,
                            ConditionFunctions.EQ,
                            (Column(None, "a", None), Literal(None, 1)),
                        ),
                        FunctionCall(
                            None,
                            ConditionFunctions.EQ,
                            (Column(None, "b", None), Literal(None, 2)),
                        ),
                    ),
                ),
                FunctionCall(
                    None,
                    ConditionFunctions.EQ,
                    (Column(None, "c", None), Literal(None, 3)),
                ),
            ),
        ),
    ),
    (
        [[["a", "=", 1], ["b", "=", 2]], [["c", "=", 3], ["d", "=", 4]]],
        FunctionCall(
            None,
            BooleanFunctions.AND,
            (
                FunctionCall(
                    None,
                    BooleanFunctions.OR,
                    (
                        FunctionCall(
                            None,
                            ConditionFunctions.EQ,
                            (Column(None, "a", None), Literal(None, 1)),
                        ),
                        FunctionCall(
                            None,
                            ConditionFunctions.EQ,
                            (Column(None, "b", None), Literal(None, 2)),
                        ),
                    ),
                ),
                FunctionCall(
                    None,
                    BooleanFunctions.OR,
                    (
                        FunctionCall(
                            None,
                            ConditionFunctions.EQ,
                            (Column(None, "c", None), Literal(None, 3)),
                        ),
                        FunctionCall(
                            None,
                            ConditionFunctions.EQ,
                            (Column(None, "d", None), Literal(None, 4)),
                        ),
                    ),
                ),
            ),
        ),
    ),
    (
        [[["a", "=", 1], []]],
        FunctionCall(
            None, ConditionFunctions.EQ, (Column(None, "a", None), Literal(None, 1)),
        ),
    ),  # Malformed Condition Input
    (
        [[[["tag", ["foo"]], "=", 1], ["b", "=", 2]]],
        FunctionCall(
            None,
            BooleanFunctions.OR,
            (
                FunctionCall(
                    None,
                    ConditionFunctions.EQ,
                    (
                        FunctionCall(None, "tag", (Column(None, "foo", None),)),
                        Literal(None, 1),
                    ),
                ),
                FunctionCall(
                    None,
                    ConditionFunctions.EQ,
                    (Column(None, "b", None), Literal(None, 2)),
                ),
            ),
        ),
    ),  # Test functions in conditions
    (
        [["primary_hash", "LIKE", "%foo%"]],
        FunctionCall(
            None,
            ConditionFunctions.LIKE,
            (Column(None, "primary_hash", None), Literal(None, "%foo%")),
        ),
    ),  # Test output format of LIKE
    (
        [[["notEmpty", ["arrayElement", ["exception_stacks.type", 1]]], "=", 1]],
        FunctionCall(
            None,
            ConditionFunctions.EQ,
            (
                FunctionCall(
                    None,
                    "notEmpty",
                    (
                        FunctionCall(
                            None,
                            "arrayElement",
                            (
                                Column(None, "exception_stacks.type", None),
                                Literal(None, 1),
                            ),
                        ),
                    ),
                ),
                Literal(None, 1),
            ),
        ),
    ),
    (
        [["exception_frames.filename", "LIKE", "%foo%"]],
        FunctionCall(
            None,
            "arrayExists",
            (
                Lambda(
                    None,
                    ("x",),
                    FunctionCall(
                        None,
                        "assumeNotNull",
                        (
                            FunctionCall(
                                None,
                                ConditionFunctions.LIKE,
                                (Argument(None, "x"), Literal(None, "%foo%")),
                            ),
                        ),
                    ),
                ),
                Column(None, "exception_frames.filename", None),
            ),
        ),
    ),  # Test scalar condition on array column is expanded as an iterator.
    (
        [["exception_frames.filename", "NOT LIKE", "%foo%"]],
        FunctionCall(
            None,
            "arrayAll",
            (
                Lambda(
                    None,
                    ("x",),
                    FunctionCall(
                        None,
                        "assumeNotNull",
                        (
                            FunctionCall(
                                None,
                                ConditionFunctions.NOT_LIKE,
                                (Argument(None, "x"), Literal(None, "%foo%")),
                            ),
                        ),
                    ),
                ),
                Column(None, "exception_frames.filename", None),
            ),
        ),
    ),  # Test negative scalar condition on array column is expanded as an all() type iterator.
    (
        tuplify(
            [["platform", "IN", ["a", "b", "c"]], ["platform", "IN", ["c", "b", "a"]]]
        ),
        FunctionCall(
            None,
            ConditionFunctions.IN,
            (
                Column(None, "platform", None),
                FunctionCall(
                    None,
                    "tuple",
                    (Literal(None, "a"), Literal(None, "b"), Literal(None, "c")),
                ),
            ),
        ),
    ),  # Test that a duplicate IN condition is deduplicated even if the lists are in different orders.
]


@pytest.mark.parametrize("conditions, expected", test_conditions)
def test_conditions_expr(conditions: Sequence[Any], expected: Expression) -> None:
    dataset = get_dataset("events")
    assert parse_conditions_to_expr(conditions, dataset, None) == expected
