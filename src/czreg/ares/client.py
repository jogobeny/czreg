from typing import ClassVar

import httpx
from pydantic import BaseModel, ValidationError

from .._core.base import CzregModel
from .._core.exceptions import InvalidRequest, NotFound, SourceUnavailable, TooManyResults
from .._core.transport import HttpClient
from .._core.validation import normalize_ico
from .models import (
    CiselnikyNazevnikSeznam,
    CiselnikyZakladniFiltr,
    EkonomickeSubjektyCeuSeznam,
    EkonomickeSubjektyKomplexFiltr,
    EkonomickeSubjektyNotifikaceFiltr,
    EkonomickeSubjektyNrpzsSeznam,
    EkonomickeSubjektyRcnsSeznam,
    EkonomickeSubjektyRegistraceFiltr,
    EkonomickeSubjektyResSeznam,
    EkonomickeSubjektyRosSeznam,
    EkonomickeSubjektyRpshSeznam,
    EkonomickeSubjektyRsSeznam,
    EkonomickeSubjektyRzpSeznam,
    EkonomickeSubjektySeznam,
    EkonomickeSubjektySzrSeznam,
    EkonomickeSubjektyVrSeznam,
    EkonomickySubjekt,
    EkonomickySubjektCeu,
    EkonomickySubjektNrpzs,
    EkonomickySubjektRcns,
    EkonomickySubjektRes,
    EkonomickySubjektRos,
    EkonomickySubjektRpsh,
    EkonomickySubjektRs,
    EkonomickySubjektRzp,
    EkonomickySubjektSzr,
    EkonomickySubjektVr,
    NotifikacniDavkaZaznam,
    SeznamNotifikacnichDavek,
    StandardizovanaAdresaFiltr,
    StandardizovaneAdresySeznam,
)

_URL = "https://ares.gov.cz/ekonomicke-subjekty-v-be/rest"


class _Chyba(CzregModel):
    """The body of an ARES error. Not the generated `Chyba`: its `kod` enum fails on a new code."""

    kod: str | None = None
    popis: str | None = None
    subKod: str | None = None


class AresClient(HttpClient):
    """ARES, the Czech business registry: the base subject, the registers, and the code lists.

    `get_<register>(ico)` and `search_<register>(filter)` exist for `vr`, `res`, `rzp`, `nrpzs`,
    `rpsh`, `rcns`, `szr`, `rs`, `ros`, and `ceu`. A register that does not know the subject raises
    `NotFound`.
    """

    # https://ares.gov.cz/stranky/podminky-provozu
    rates: ClassVar[tuple[tuple[int, int], ...]] = ((500, 60),)

    async def _request[T: BaseModel](
        self, model: type[T], method: str, path: str, filter: CzregModel | None = None
    ) -> T:
        """Send the request and parse the reply into `model`.

        Raises:
            NotFound: HTTP 404 or `NENALEZENO`.
            TooManyResults: a search with more than 1 000 results.
            InvalidRequest: HTTP 400 or `CHYBA_VSTUPU`, for example an empty filter.
            SourceUnavailable: any other error, or a reply that does not match the spec.
        """
        json = filter.model_dump(mode="json", exclude_none=True) if filter else None
        response = await self.send(httpx.Request(method, f"{_URL}/{path}", json=json))

        if response.status_code >= 400:
            try:
                chyba = _Chyba.model_validate_json(response.content)
            except ValidationError:
                chyba = _Chyba()

            message = chyba.popis or f"ARES returned HTTP {response.status_code}"
            code = chyba.subKod or chyba.kod

            if response.status_code == 404 or chyba.kod == "NENALEZENO":
                raise NotFound(message, source="ares", code=code)
            if code == "VYSTUP_PRILIS_MNOHO_VYSLEDKU":
                raise TooManyResults(message, source="ares", code=code)
            if response.status_code == 400 or chyba.kod == "CHYBA_VSTUPU":
                raise InvalidRequest(message, source="ares", code=code)
            raise SourceUnavailable(message, source="ares", code=code)

        try:
            return model.model_validate_json(response.content)
        except ValidationError as exc:
            raise SourceUnavailable("ARES returned a reply off the spec", source="ares") from exc

    async def _get[T: BaseModel](self, model: type[T], register: str, ico: str | int) -> T:
        """`GET /{register}/{ico}`. Raises `InvalidIco` before any request."""
        return await self._request(model, "GET", f"{register}/{normalize_ico(ico)}")

    async def _search[T: BaseModel](self, model: type[T], register: str, filter: CzregModel) -> T:
        return await self._request(model, "POST", f"{register}/vyhledat", filter)

    async def get_subject(self, ico: str | int):
        """The base subject, `GET /ekonomicke-subjekty/{ico}`."""
        return await self._get(EkonomickySubjekt, "ekonomicke-subjekty", ico)

    async def search(self, filter: EkonomickeSubjektyKomplexFiltr):
        """The subjects that match the filter. ARES never returns more than 1 000."""
        return await self._search(EkonomickeSubjektySeznam, "ekonomicke-subjekty", filter)

    async def search_code_lists(self, filter: CiselnikyZakladniFiltr):
        """The code lists, the names of the codes in fields like `pravniForma`."""
        return await self._search(CiselnikyNazevnikSeznam, "ciselniky-nazevniky", filter)

    async def search_addresses(self, filter: StandardizovanaAdresaFiltr):
        """The RÚIAN standardized addresses."""
        return await self._search(StandardizovaneAdresySeznam, "standardizovane-adresy", filter)

    async def search_notifications(self, filter: EkonomickeSubjektyNotifikaceFiltr):
        return await self._search(
            SeznamNotifikacnichDavek, "ekonomicke-subjekty-notifikace", filter
        )

    async def get_notification_batch(self, datovy_zdroj: str, cislo_davky: int):
        path = (
            f"ekonomicke-subjekty-notifikace/datovy-zdroj/{datovy_zdroj}/cislo-davky/{cislo_davky}"
        )
        return await self._request(NotifikacniDavkaZaznam, "GET", path)

    async def get_vr(self, ico: str | int):
        return await self._get(EkonomickySubjektVr, "ekonomicke-subjekty-vr", ico)

    async def search_vr(self, filter: EkonomickeSubjektyRegistraceFiltr):
        return await self._search(EkonomickeSubjektyVrSeznam, "ekonomicke-subjekty-vr", filter)

    async def get_res(self, ico: str | int):
        return await self._get(EkonomickySubjektRes, "ekonomicke-subjekty-res", ico)

    async def search_res(self, filter: EkonomickeSubjektyRegistraceFiltr):
        return await self._search(EkonomickeSubjektyResSeznam, "ekonomicke-subjekty-res", filter)

    async def get_rzp(self, ico: str | int):
        return await self._get(EkonomickySubjektRzp, "ekonomicke-subjekty-rzp", ico)

    async def search_rzp(self, filter: EkonomickeSubjektyRegistraceFiltr):
        return await self._search(EkonomickeSubjektyRzpSeznam, "ekonomicke-subjekty-rzp", filter)

    async def get_nrpzs(self, ico: str | int):
        return await self._get(EkonomickySubjektNrpzs, "ekonomicke-subjekty-nrpzs", ico)

    async def search_nrpzs(self, filter: EkonomickeSubjektyRegistraceFiltr):
        return await self._search(
            EkonomickeSubjektyNrpzsSeznam, "ekonomicke-subjekty-nrpzs", filter
        )

    async def get_rpsh(self, ico: str | int):
        return await self._get(EkonomickySubjektRpsh, "ekonomicke-subjekty-rpsh", ico)

    async def search_rpsh(self, filter: EkonomickeSubjektyRegistraceFiltr):
        return await self._search(EkonomickeSubjektyRpshSeznam, "ekonomicke-subjekty-rpsh", filter)

    async def get_rcns(self, ico: str | int):
        return await self._get(EkonomickySubjektRcns, "ekonomicke-subjekty-rcns", ico)

    async def search_rcns(self, filter: EkonomickeSubjektyRegistraceFiltr):
        return await self._search(EkonomickeSubjektyRcnsSeznam, "ekonomicke-subjekty-rcns", filter)

    async def get_szr(self, ico: str | int):
        return await self._get(EkonomickySubjektSzr, "ekonomicke-subjekty-szr", ico)

    async def search_szr(self, filter: EkonomickeSubjektyRegistraceFiltr):
        return await self._search(EkonomickeSubjektySzrSeznam, "ekonomicke-subjekty-szr", filter)

    async def get_rs(self, ico: str | int):
        return await self._get(EkonomickySubjektRs, "ekonomicke-subjekty-rs", ico)

    async def search_rs(self, filter: EkonomickeSubjektyRegistraceFiltr):
        return await self._search(EkonomickeSubjektyRsSeznam, "ekonomicke-subjekty-rs", filter)

    async def get_ros(self, ico: str | int):
        return await self._get(EkonomickySubjektRos, "ekonomicke-subjekty-ros", ico)

    async def search_ros(self, filter: EkonomickeSubjektyRegistraceFiltr):
        return await self._search(EkonomickeSubjektyRosSeznam, "ekonomicke-subjekty-ros", filter)

    async def get_ceu(self, ico: str | int):
        return await self._get(EkonomickySubjektCeu, "ekonomicke-subjekty-ceu", ico)

    async def search_ceu(self, filter: EkonomickeSubjektyRegistraceFiltr):
        return await self._search(EkonomickeSubjektyCeuSeznam, "ekonomicke-subjekty-ceu", filter)
