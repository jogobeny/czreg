from .._core import soap
from .._core.exceptions import SourceUnavailable
from .._core.transport import HttpClient
from .models import (
    SeznamNespolehlivyPlatceResponse,
    StatusNespolehlivyPlatceResponse,
    StatusNespolehlivyPlatceRozsirenyResponse,
    StatusNespolehlivySubjektRozsirenyResponse,
)

_URL = "https://mojedane.gov.cz/dpr/axis2/services/rozhraniCRPDPH.rozhraniCRPDPHSOAP"
_NS = "http://adis.mfcr.cz/rozhraniCRPDPH/"
_MAX_DIC = 100  # statusCode 1 in the WSDL: more DIČ in one request are cut


class DphClient(HttpClient):
    """Registr plátců DPH: the public SOAP service of the Financial Administration.

    Whether a VAT payer is unreliable, its published bank accounts, and its tax office. A DIČ
    goes with or without the `CZ` prefix, up to 100 in one call.
    """

    async def get_status(self, *dic: str):
        """`getStatusNespolehlivyPlatce`: the reliability and the bank accounts."""
        return await self._call(
            "getStatusNespolehlivyPlatce",
            "StatusNespolehlivyPlatceRequest",
            StatusNespolehlivyPlatceResponse,
            dic,
        )

    async def get_status_extended(self, *dic: str):
        """`getStatusNespolehlivyPlatceRozsireny`: `get_status` with the name and the address."""
        return await self._call(
            "getStatusNespolehlivyPlatceRozsireny",
            "StatusNespolehlivyPlatceRozsirenyRequest",
            StatusNespolehlivyPlatceRozsirenyResponse,
            dic,
        )

    async def get_subject_status(self, *dic: str):
        """`getStatusNespolehlivySubjektRozsirenyV2`: also identified and unreliable persons."""
        return await self._call(
            "getStatusNespolehlivySubjektRozsirenyV2",
            "StatusNespolehlivySubjektRozsirenyV2Request",
            StatusNespolehlivySubjektRozsirenyResponse,
            dic,
        )

    async def get_unreliable_payers(self):
        """`getSeznamNespolehlivyPlatce`: all the unreliable payers, without the bank accounts."""
        return await self._call(
            "getSeznamNespolehlivyPlatce",
            "SeznamNespolehlivyPlatceRequest",
            SeznamNespolehlivyPlatceResponse,
            (),
        )

    async def _call[
        T: (
            StatusNespolehlivyPlatceResponse,
            StatusNespolehlivyPlatceRozsirenyResponse,
            StatusNespolehlivySubjektRozsirenyResponse,
            SeznamNespolehlivyPlatceResponse,
        )
    ](self, operation: str, element: str, model: type[T], dic: tuple[str, ...]):
        """Send the request and parse the reply. A `statusCode` other than 0 raises.

        Raises:
            ValueError: more than 100 DIČ.
            SourceUnavailable: HTTP error, the nightly maintenance (statusCode 2, 0:00-0:10),
                or the service is down (3).
        """
        if len(dic) > _MAX_DIC:
            raise ValueError(f"{len(dic)} DIČ, the service takes at most {_MAX_DIC} in one call")

        fields: dict[str, object] = {"dic": [d.removeprefix("CZ") for d in dic]} if dic else {}
        response = await self.send(
            soap.request(_URL, f"{_NS}{operation}", _NS, element, fields, qualified=True)
        )

        if response.status_code >= 400:
            raise SourceUnavailable(f"DPH returned HTTP {response.status_code}", source="dph")

        result = soap.parse(response.content, _NS, model.__name__, model, source="dph")
        if result.status.statusCode != 0:
            raise SourceUnavailable(
                result.status.statusText, source="dph", code=str(result.status.statusCode)
            )

        return result
