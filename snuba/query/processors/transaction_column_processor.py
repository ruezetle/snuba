from snuba.query.expressions import Column, Expression, FunctionCall, Literal
from snuba.query.query import Query
from snuba.query.query_processor import QueryProcessor
from snuba.request.request_settings import RequestSettings


class TransactionColumnProcessor(QueryProcessor):
    """
    Strip any dashes out of the event ID to match what is stored internally.
    """

    def process_query(self, query: Query, request_settings: RequestSettings) -> None:
        def process_column(exp: Expression) -> Expression:
            if isinstance(exp, Column):
                if exp.column_name == "event_id":
                    return FunctionCall(
                        exp.alias,
                        "replaceAll",
                        (
                            FunctionCall(
                                None, "toString", (Column(None, "event_id", None),),
                            ),
                            Literal(None, "-"),
                            Literal(None, ""),
                        ),
                    )

            return exp

        query.transform_expressions(process_column)
