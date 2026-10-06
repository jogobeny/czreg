from .exceptions import InvalidIco

_ICO_WEIGHTS = (8, 7, 6, 5, 4, 3, 2)


def normalize_ico(value: str | int):
    """Return the IČO in the canonical eight-digit form, with the leading zeros.

    Raises:
        InvalidIco: the value is not up to eight digits, or the modulo-11 check digit
                    (https://w.wiki/Tqv6) does not match.
    """
    digits = str(value)
    if not (digits.isascii() and digits.isdigit() and len(digits) <= 8):
        raise InvalidIco(f"Invalid IČO {value!r}: an IČO has one to eight digits")

    ico = digits.zfill(8)
    total = sum(int(d) * w for d, w in zip(ico[:7], _ICO_WEIGHTS, strict=True))
    if int(ico[7]) != (11 - total % 11) % 10:
        raise InvalidIco(f"Invalid IČO {value!r}: the check digit does not match")
    return ico
