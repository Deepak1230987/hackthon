from typing import Annotated, Literal

from pydantic import BaseModel, Field, TypeAdapter


class Cmp(BaseModel):
    type: Literal["cmp"]
    field: str
    op: Literal["eq", "ne", "lt", "lte", "gt", "gte", "in", "not_in"]
    value: bool | int | float | str | list[str]


# An empty group would be vacuously true, which would pass a citizen on nothing.
class And(BaseModel):
    type: Literal["and"]
    items: list["Expr"] = Field(min_length=1)


class Or(BaseModel):
    type: Literal["or"]
    items: list["Expr"] = Field(min_length=1)


class Not(BaseModel):
    type: Literal["not"]
    item: "Expr"


class Unevaluable(BaseModel):
    type: Literal["unevaluable"]
    source_text: str


Expr = Annotated[Cmp | And | Or | Not | Unevaluable, Field(discriminator="type")]
EXPR = TypeAdapter(Expr)


def comparisons(expr: Expr) -> list[Cmp]:
    match expr:
        case Cmp():
            return [expr]
        case And() | Or():
            return [cmp for item in expr.items for cmp in comparisons(item)]
        case Not():
            return comparisons(expr.item)
        case Unevaluable():
            return []
