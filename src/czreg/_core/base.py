import re
from datetime import date
from typing import ClassVar, get_args

from pydantic import BaseModel, ConfigDict, ValidationInfo, field_validator

# An XML Schema `xs:date` may carry a timezone ("1992-09-29Z", "1992-09-29+02:00");
# pydantic's `date` refuses it.
_XML_DATE_WITH_TIMEZONE = re.compile(r"(\d{4}-\d{2}-\d{2})(?:Z|[+-]\d{2}:\d{2})")


class CzregModel(BaseModel):
    """The base of the generated models: frozen, unknown fields ignored.

    The fields carry the names of the source 1:1 (`kodChyby`, not `kod_chyby`), so no aliases.
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", frozen=True)

    @field_validator("*", mode="before")
    @classmethod
    def _drop_date_timezone(cls, value: object, info: ValidationInfo):
        if not isinstance(value, str) or info.field_name is None:
            return value
        annotation = cls.model_fields[info.field_name].annotation
        if date in (annotation, *get_args(annotation)) and (
            match := _XML_DATE_WITH_TIMEZONE.fullmatch(value)
        ):
            return match.group(1)
        return value
