import types
import xml.etree.ElementTree as ET
from typing import cast, get_args, get_origin

import httpx
from pydantic import BaseModel

from .exceptions import SourceUnavailable

_SOAP = "http://schemas.xmlsoap.org/soap/envelope/"
_XSI = "http://www.w3.org/2001/XMLSchema-instance"


def request(
    url: str,
    action: str,
    namespace: str,
    element: str,
    fields: dict[str, object],
    *,
    qualified: bool,
):
    """A POST with `<element>` in the SOAP body; each field is a child element, a list repeats it.

    `qualified` puts the children into `namespace` too (XSD `elementFormDefault="qualified"`).
    """
    envelope = ET.Element(f"{{{_SOAP}}}Envelope")
    body = ET.SubElement(envelope, f"{{{_SOAP}}}Body")
    parent = ET.SubElement(body, f"{{{namespace}}}{element}")
    prefix = f"{{{namespace}}}" if qualified else ""

    for name, value in fields.items():
        for item in cast("list[object]", value) if isinstance(value, list) else [value]:
            ET.SubElement(parent, prefix + name).text = str(item)

    return httpx.Request(
        "POST",
        url,
        content=ET.tostring(envelope),
        headers={"Content-Type": "text/xml; charset=utf-8", "SOAPAction": f'"{action}"'},
    )


def parse[T: BaseModel](
    content: bytes, namespace: str, element: str, model: type[T], *, source: str
):
    """Find `<element>` in the reply and validate it, attributes and children, as `model`."""
    try:
        root = ET.fromstring(content)
    except ET.ParseError as exc:
        raise SourceUnavailable(
            f"{source} returned a reply that is not XML", source=source
        ) from exc

    node = root.find(f".//{{{namespace}}}{element}")
    if node is None:
        raise SourceUnavailable(f"{source} returned no {element}", source=source)

    return model.model_validate(_to_dict(node, model))


def _to_dict(element: ET.Element, model: type[BaseModel]):
    """The attributes and the children of `element`, shaped by the fields of `model`.

    The keys are the XML names: a field's alias, where the generator renamed a field.
    """
    fields = {f.alias or n: f for n, f in model.model_fields.items()}
    data: dict[str, object] = {k: v for k, v in element.attrib.items() if "}" not in k}
    lists: dict[str, list[object]] = {}
    for child in element:
        name = child.tag.rsplit("}", 1)[-1]
        if (field := fields.get(name)) is None:
            continue

        target, is_list = _unwrap(field.annotation)
        if isinstance(target, type) and issubclass(target, BaseModel):
            nil = child.get(f"{{{_XSI}}}nil") == "true"
            value = None if nil else _to_dict(child, target)
        else:
            value = child.text

        if is_list:
            lists.setdefault(name, []).append(value)
        else:
            data[name] = value

    # a repeated element that did not come is an empty list, not a missing field
    missing: dict[str, object] = {
        name: [] for name, f in fields.items() if _unwrap(f.annotation)[1]
    }
    return data | missing | lists


def _unwrap(annotation: object):
    """The type inside `X | None` and `list[X]`, and whether a list was on the way."""
    is_list = False
    while True:
        args = cast("tuple[object, ...]", get_args(annotation))
        origin = get_origin(annotation)
        if origin is types.UnionType:
            annotation = next(a for a in args if a is not type(None))
        elif origin is list:
            is_list, annotation = True, args[0]
        else:
            return annotation, is_list
