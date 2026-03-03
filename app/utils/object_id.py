from bson import ObjectId
from typing import Annotated, Any
from pydantic import GetJsonSchemaHandler
from pydantic.json_schema import JsonSchemaValue
from pydantic_core import CoreSchema, core_schema


class _ObjectIdValidator:
    """Custom Pydantic v2 type for MongoDB ObjectId."""

    @classmethod
    def __get_pydantic_core_schema__(cls, _source_type: Any, _handler: Any) -> CoreSchema:
        return core_schema.no_info_plain_validator_function(
            cls.validate,
            serialization=core_schema.to_string_ser_schema(),
        )

    @classmethod
    def __get_pydantic_json_schema__(
        cls, _core_schema: CoreSchema, handler: GetJsonSchemaHandler
    ) -> JsonSchemaValue:
        return {"type": "string", "example": "507f1f77bcf86cd799439011"}

    @classmethod
    def validate(cls, v: Any) -> str:
        if isinstance(v, ObjectId):
            return str(v)
        if isinstance(v, str) and ObjectId.is_valid(v):
            return str(v)
        raise ValueError(f"Invalid ObjectId: {v}")


PyObjectId = Annotated[str, _ObjectIdValidator]
