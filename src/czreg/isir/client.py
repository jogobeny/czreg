from typing import ClassVar

from .._core import soap
from .._core.exceptions import InvalidRequest, SourceUnavailable
from .._core.transport import HttpClient
from .._core.validation import normalize_ico
from .models import (
    GetIsirWsCuzkDataRequest,
    GetIsirWsCuzkDataResponse,
    KodChybyType,
    PriznakType,
)

_URL = "https://isir.justice.cz:8443/isir_cuzk_ws/IsirWsCuzkService"
_TYPES = "http://isirws.cca.cz/types/"
_INVALID_REQUEST_CODES = {KodChybyType.WS1, KodChybyType.WS3}


class IsirClient(HttpClient):
    """Insolvenční rejstřík (ISIR): the public SOAP service ISIR_CUZK_WS of the Ministry of Justice.

    It answers whether a person has an insolvency proceeding and in which state. For the course of
    the proceeding, follow `urlDetailRizeni`.
    """

    # https://isir.justice.cz/isir/help/Popis_WS_2_v1_13.pdf (chapter 1.3.3)
    rates: ClassVar[tuple[tuple[int, int], ...]] = ((50, 60), (3000, 86400))

    async def get_by_ico(self, ico: str | int, *, active_only: bool = False):
        """Is the subject with this IČO in insolvency? An empty `data` means no.

        `active_only` leaves out the finished proceedings (`filtrAktualniRizeni=T`).

        Raises:
            InvalidIco: the IČO failed the local validation. No request was sent.
        """
        return await self.search(
            GetIsirWsCuzkDataRequest(
                ic=normalize_ico(ico),
                filtrAktualniRizeni=PriznakType.T if active_only else None,
            )
        )

    async def search(self, request: GetIsirWsCuzkDataRequest):
        """The full query of `getIsirWsCuzkData`. An empty `data` means no proceeding.

        Raises:
            InvalidRequest: ISIR refused the criteria (WS1, WS3).
        """
        fields: dict[str, object] = request.model_dump(mode="json", exclude_none=True)
        response = await self.send(
            soap.request(_URL, "", _TYPES, "getIsirWsCuzkDataRequest", fields, qualified=False)
        )

        if response.status_code >= 400:
            raise SourceUnavailable(f"ISIR returned HTTP {response.status_code}", source="isir")

        result = soap.parse(
            response.content,
            _TYPES,
            "getIsirWsCuzkDataResponse",
            GetIsirWsCuzkDataResponse,
            source="isir",
        )
        code = result.stav.kodChyby
        if code is None or code is KodChybyType.WS2:
            return result
        message = result.stav.popisChyby or result.stav.textChyby or code.value
        error = InvalidRequest if code in _INVALID_REQUEST_CODES else SourceUnavailable
        raise error(message, source="isir", code=code.value)
