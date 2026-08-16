"""
Rate-limit policy definition.

A Policy is just the two numbers the Token Bucket algorithm needs. Keeping
this as its own module (rather than inlined in the API schema) matters once
we add named/stored policies later (spec section 11, optional feature #2) —
the algorithm code should depend on this, not on the HTTP layer's request
shape.
"""

from pydantic import BaseModel, field_validator


class Policy(BaseModel):
    capacity: float
    refill_rate: float

    @field_validator("capacity")
    @classmethod
    def capacity_must_be_positive(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("capacity must be > 0")
        return v

    @field_validator("refill_rate")
    @classmethod
    def refill_rate_must_be_positive(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("refill_rate must be > 0")
        return v