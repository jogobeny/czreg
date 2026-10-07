import asyncio
from collections.abc import Coroutine
from datetime import date
from enum import Flag, auto

import httpx

from ._core.exceptions import CursorExpired, NotFound, SourceError
from ._core.validation import normalize_ico
from .ares import AresClient
from .ares.models import (
    CiselnikyZakladniFiltr,
    EkonomickeSubjektyKomplexFiltr,
    EkonomickeSubjektyNotifikaceFiltr,
    EkonomickySubjekt,
)
from .dph import DphClient
from .isir import IsirClient
from .subject import (
    PERSON_LEGAL_FORMS,
    ChangeType,
    Code,
    Company,
    Cursor,
    DataBox,
    Person,
    Representative,
    SearchResult,
    Source,
    data_boxes_from_ros,
    hit_from_ares,
    insolvency_from,
    representatives_from_vr,
    subject_from_ares,
    subject_from_isir,
    vat_from,
    vat_from_ares,
)

_UNAVAILABLE = (SourceError, httpx.TransportError)


def _registered(state: str | None):
    """A `stavZdroje*` of ARES `seznamRegistraci`: the register has a record (current or not)."""
    return state not in (None, "NEEXISTUJICI")


class Part(Flag):
    """The parts of `czreg.get_subject` beyond the basic data, each one request more."""

    NONE = 0
    VAT = auto()
    DATA_BOXES = auto()
    REPRESENTATIVES = auto()
    INSOLVENCY = auto()
    ALL = VAT | DATA_BOXES | REPRESENTATIVES | INSOLVENCY


# the ARES registers with notification batches (EkonomickeSubjektyNotifikaceFiltr.datovyZdroj)
_NOTIFICATION_SOURCES = (
    Source.VR,
    Source.RES,
    Source.ROS,
    Source.RZP,
    Source.NRPZS,
    Source.RCNS,
    Source.RPSH,
    Source.RS,
    Source.SZR,
)


class czreg:
    def __init__(self, *, rate_limit: bool = False, timeout: float = 10.0):
        self.ares: AresClient = AresClient(rate_limit=rate_limit, timeout=timeout)
        self.dph: DphClient = DphClient(rate_limit=rate_limit, timeout=timeout)
        self.isir: IsirClient = IsirClient(rate_limit=rate_limit, timeout=timeout)
        self._code_lists: dict[tuple[str, str], dict[str, str]] = {}

    async def describe(self, code: Code | None):
        """The Czech name of a code: `describe(subject.legal_form)` → "Společnost s ručením
        omezeným". None for None or an unknown code. One ARES request per code list for this
        instance.
        """
        if code is None:
            return None
        code_list = code.code_list
        if code_list not in self._code_lists:
            source, name = code_list
            found = await self.ares.search_code_lists(
                CiselnikyZakladniFiltr(zdrojCiselniku=source, kodCiselniku=name)
            )
            items = [i for c in found.ciselniky or [] for i in c.polozkyCiselniku or []]
            # a code may have older names: sort by validity, so that the current one wins
            items.sort(key=lambda i: i.platnostOd or date.min)
            self._code_lists[code_list] = {
                i.kod: n.nazev
                for i in items
                for n in i.nazev or []
                if i.kod and n.nazev and n.kodJazyka == "cs"
            }
        return self._code_lists[code_list].get(code)

    async def get_subject(self, ico: str | int, *, include: Part = Part.ALL) -> Company | Person:
        """The subject with this IČO: a `Company`, or a `Person` with the name from RŽP.

        The basic data cost one ARES request; each part in `include` one more. A part left out
        is None, and so is one whose source did not answer. `vat` is the exception: it always
        has the DIČ from ARES, and the fields from DPH are None. An empty list means the source
        has none.

        Raises:
            InvalidIco: the IČO failed the local validation. No request was sent.
            NotFound: neither ARES nor ISIR know the IČO. A subject only ISIR knows (often a
                deleted one in insolvency) comes back with `in_ares=False`.
        """
        ico = normalize_ico(ico)
        try:
            subject = await self.ares.get_subject(ico)
        except NotFound:
            return await self._from_isir(ico)
        errors: dict[Source, str] = {}

        async def part[T](flag: Part, source: Source, call: Coroutine[object, object, T]):
            if flag not in include:
                call.close()
                return None
            try:
                return await call
            except _UNAVAILABLE as exc:
                errors[source] = str(exc) or type(exc).__name__
                return None

        person, vat_, boxes, reps, insolvency = await asyncio.gather(
            part(Part.NONE, Source.RZP, self._person(ico, subject)),
            part(Part.VAT, Source.DPH, self._vat(ico, subject)),
            part(Part.DATA_BOXES, Source.ROS, self._data_boxes(ico, subject)),
            part(Part.REPRESENTATIVES, Source.VR, self._representatives(ico, subject)),
            part(Part.INSOLVENCY, Source.ISIR, self._insolvency(ico)),
        )
        if vat_ is None:
            vat_ = vat_from_ares(subject)
        return subject_from_ares(ico, subject, person, vat_, boxes, reps, insolvency, errors)

    async def search(self, name: str, *, limit: int = 20, offset: int = 0):
        """The subjects in ARES whose name has all the words of `name`. One ARES request.

        ARES finds whole words only, in any order, with any case and diacritics: "cez distribuce"
        finds "ČEZ Distribuce, a. s.", but "Distribu" finds nothing. A blank `name` gives no
        hits, without a request.

        Raises:
            TooManyResults: more than 1 000 subjects match. Paging does not help.
        """
        if not name.strip():
            return SearchResult(total=0, hits=[])
        found = await self.ares.search(
            EkonomickeSubjektyKomplexFiltr(obchodniJmeno=name.strip(), pocet=limit, start=offset)
        )
        return SearchResult(
            total=found.pocetCelkem or 0,
            hits=[hit_from_ares(s) for s in found.ekonomickeSubjekty or []],
        )

    async def _person(self, ico: str, subject: EkonomickySubjekt):
        registrace = subject.seznamRegistraci
        if subject.pravniForma not in PERSON_LEGAL_FORMS or not (
            registrace and _registered(registrace.stavZdrojeRzp)
        ):
            return None
        try:
            rzp = await self.ares.get_rzp(ico)
        except NotFound:
            return None
        return next((z.osobaPodnikatel for z in rzp.zaznamy or [] if z.osobaPodnikatel), None)

    async def _vat(self, ico: str, subject: EkonomickySubjekt):
        # an 8-digit DIČ always comes from the IČO, so the IČO is a safe fallback
        dic = [subject.dic or ico, *([subject.dicSkDph] if subject.dicSkDph else [])]
        status = await self.dph.get_subject_status(*dic)
        return vat_from(ico, subject, status.statusSubjektu or [])

    async def _data_boxes(self, ico: str, subject: EkonomickySubjekt) -> list[DataBox] | None:
        registrace = subject.seznamRegistraci
        if not (registrace and _registered(registrace.stavZdrojeRos)):
            return []
        try:
            ros = await self.ares.get_ros(ico)
        except NotFound:
            return []
        return data_boxes_from_ros(ros.zaznamy or [])

    async def _representatives(
        self, ico: str, subject: EkonomickySubjekt
    ) -> list[Representative] | None:
        registrace = subject.seznamRegistraci
        if subject.pravniForma in PERSON_LEGAL_FORMS or not (
            registrace and _registered(registrace.stavZdrojeVr)
        ):
            return []
        try:
            vr = await self.ares.get_vr(ico)
        except NotFound:
            return []
        return representatives_from_vr(vr.zaznamy or [])

    async def _from_isir(self, ico: str):
        """ARES does not know the IČO: a deleted subject is often still a debtor in ISIR."""
        isir = await self.isir.get_by_ico(ico)
        debtor = next((d for d in isir.data or [] if d), None)
        if debtor is None:
            raise NotFound(f"Neither ARES nor ISIR know the IČO {ico}", source="ares")
        return subject_from_isir(ico, debtor, insolvency_from(isir.data or []))

    async def _insolvency(self, ico: str):
        isir = await self.isir.get_by_ico(ico)
        return insolvency_from(isir.data or [])

    async def changes_cursor(self):
        """A `Cursor` at the newest ARES notification batches: the start for `changes`.

        One ARES request per notification source.
        """

        async def last(source: Source):
            found = await self.ares.search_notifications(
                EkonomickeSubjektyNotifikaceFiltr(datovyZdroj=source)
            )
            return max((b.cisloDavky or 0 for b in found.notifikacniDavky or []), default=0)

        numbers = await asyncio.gather(*(last(source) for source in _NOTIFICATION_SOURCES))
        return Cursor(batches=dict(zip(_NOTIFICATION_SOURCES, numbers, strict=True)))

    async def changes(self, cursor: Cursor):
        """The subjects changed in the ARES registers since `cursor`, and the cursor to store for
        the next call: `{ico: {Source.VR: ChangeType.UPDATED, …}}`. A register missing from
        `cursor` starts now.

        One ARES request per register, and one per new batch. Does not cover DPH and ISIR.

        Raises:
            CursorExpired: ARES no longer has the batches after `cursor`.
        """

        async def read(source: Source):
            found = await self.ares.search_notifications(
                EkonomickeSubjektyNotifikaceFiltr(datovyZdroj=source)
            )
            numbers = sorted(b.cisloDavky for b in found.notifikacniDavky or [] if b.cisloDavky)
            last = cursor.batches.get(source, numbers[-1] if numbers else 0)
            # 0: the register had no batch yet, so nothing can be lost
            if last and numbers and last < numbers[0] - 1:
                raise CursorExpired(
                    f"ARES keeps the {source} batches since {numbers[0]}, not {last}"
                )
            new = [n for n in numbers if n > last]
            return (
                source,
                max([last, *new]),
                await asyncio.gather(*(self.ares.get_notification_batch(source, n) for n in new)),
            )

        changed: dict[str, dict[Source, ChangeType]] = {}
        read_all = await asyncio.gather(*(read(source) for source in _NOTIFICATION_SOURCES))
        for source, _, batches in read_all:
            for batch in batches:
                for change in batch.seznamNotifikaci or []:
                    if change.icoId and change.typZmeny:
                        changed.setdefault(change.icoId, {})[source] = ChangeType(change.typZmeny)
        return changed, Cursor(batches={source: last for source, last, _ in read_all})

    async def aclose(self):
        await asyncio.gather(self.ares.aclose(), self.dph.aclose(), self.isir.aclose())

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_: object):
        await self.aclose()


def get_subject_sync(ico: str | int, *, include: Part = Part.ALL) -> Company | Person:
    """`czreg.get_subject` for code without asyncio: a script, a notebook, a sync web framework.

    Each call opens and closes its own clients, so the rate limits do not span calls; for many
    subjects, use `czreg` in async code.
    """

    async def run():
        async with czreg() as cz:
            return await cz.get_subject(ico, include=include)

    return asyncio.run(run())
