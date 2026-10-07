from datetime import date
from enum import StrEnum
from typing import ClassVar, cast, final

from pydantic import BaseModel, ConfigDict, GetCoreSchemaHandler
from pydantic_core import core_schema

from .ares.models import (
    Adresa,
    AngazovanaOsobaRzp,
    EkonomickySubjekt,
    FyzickaOsobaVr,
    PravnickaOsobaVr,
    ZaznamRos,
    ZaznamVr,
)
from .dph.models import (
    InformaceOSubjektuRozsireneType,
    NespolehlivyPlatceType,
    TypSubjektuDPHType,
    ZverejnenyUcetType,
)
from .isir.models import IsirWsCuzkData


class _Model(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)


class Source(StrEnum):
    """A source of the data. The registers come through ARES; their values are the ARES codes
    (`datovyZdroj`)."""

    ARES = "ares"
    VR = "vr"
    RES = "res"
    ROS = "ros"
    RZP = "rzp"
    NRPZS = "nrpzs"
    RCNS = "rcns"
    RPSH = "rpsh"
    RS = "rs"
    SZR = "szr"
    DPH = "dph"
    ISIR = "isir"


class Conflict[T](_Model):
    """The sources disagree: the value of each source."""

    values: dict[Source, T]


class Code(str):
    """A code from an ARES code list, a plain string otherwise; `czreg.describe` gives its name."""

    code_list: ClassVar[tuple[str, str]]  # (source, code list) in ARES

    @classmethod
    def __get_pydantic_core_schema__(cls, source: object, handler: GetCoreSchemaHandler):
        return core_schema.no_info_after_validator_function(cls, handler(str))


@final
class LegalForm(Code):
    code_list = ("res", "PravniForma")


@final
class Nace(Code):
    code_list = ("res", "CzNace")


@final
class Country(Code):
    code_list = ("com", "Stat")


@final
class DataBoxType(Code):
    code_list = ("ros", "TypDatoveSchranky")


class Address(_Model):
    text: str | None
    street: str | None
    house_number: str | None
    city: str | None
    city_part: str | None
    postal_code: str | None
    country_code: Country | None
    ruian_code: int | None


class VatStatus(StrEnum):
    PAYER = "payer"
    GROUP_MEMBER = "group_member"
    IDENTIFIED_PERSON = "identified_person"
    NOT_REGISTERED = "not_registered"


class BankAccount(_Model):
    number: str
    published_since: date


class Vat(_Model):
    """`dic` and `group_dic` come from ARES. The other fields come from DPH, and are None
    without `Part.VAT`, or when DPH did not answer (see `errors`)."""

    status: VatStatus | Conflict[VatStatus] | None
    dic: str | None
    group_dic: str | None
    unreliable: bool | None
    unreliable_since: date | None
    tax_office: str | None
    bank_accounts: list[BankAccount] | None


class DataBox(_Model):
    id: str
    type: DataBoxType | None


class _PersonName(_Model):
    title_before: str | None
    first_name: str | None
    last_name: str | None
    title_after: str | None
    birth_date: date | None


class Representative(_PersonName):
    body: str | None
    role: str | None
    since: date | None
    ico: str | None
    name: str | None


# ARES code list PravniForma (ČSÚ): the forms of a natural person; every other code is a legal one
PERSON_LEGAL_FORMS = frozenset(
    {"101", "102", "103", "104", "105", "106", "107", "108", "424", "425"}
)


class InsolvencyProceeding(_Model):
    file_number: str
    court: str | None
    state: str | None
    ongoing: bool
    declared: date | None
    ended: date | None
    url: str | None


class Insolvency(_Model):
    ongoing: bool
    proceedings: list[InsolvencyProceeding]


# https://isir.justice.cz/isir/help/Popis_WS_2_v1_13.pdf (chapter 3.2): the states of a finished
# proceeding; any other state, VYRIZENA too, is a proceeding still going on
_FINISHED_STATES = frozenset({"ODSKRTNUTA", "PRAVOMOCNA", "MYLNÝ ZÁP."})


class _Subject(_Model):
    ico: str
    name: str | None
    address: Address | None
    legal_form: LegalForm | None
    nace: list[Nace]
    established: date | None
    ceased: date | None
    vat: Vat | None
    data_boxes: list[DataBox] | None
    insolvency: Insolvency | None
    errors: dict[Source, str]  # the sources that did not answer, with the error
    in_ares: bool  # False: ARES does not know the IČO (any more), the data come from ISIR


class Company(_Subject):
    representatives: list[Representative] | None


class Sex(StrEnum):
    MALE = "male"
    FEMALE = "female"


class Person(_Subject, _PersonName):
    sex: Sex | None  # only when the DIČ is a birth number that matches `birth_date`


def sex_from(dic: str | None, birth_date: date | None):
    """The sex in a birth number, when the DIČ is a 10-digit birth number of exactly this
    `birth_date`. None otherwise.

    https://www.zakonyprolidi.cz/cs/2000-133#p13 (§ 13): `RRMMDD` + 4 digits, the month +50 for
    a woman; in an additional set +20 for a man, +70 for a woman.
    """
    digits = (dic or "").removeprefix("CZ")
    if birth_date is None or len(digits) != 10 or not digits.isdigit():
        return None
    year, month, day = int(digits[:2]), int(digits[2:4]), int(digits[4:6])
    sex = Sex.FEMALE if month > 50 else Sex.MALE
    month %= 50
    month -= 20 if month > 20 else 0
    matches = (year, month, day) == (birth_date.year % 100, birth_date.month, birth_date.day)
    return sex if matches else None


def address_from_ares(a: Adresa):
    number = f"{a.cisloDomovni or ''}"
    if a.cisloOrientacni is not None:
        number += f"/{a.cisloOrientacni}{a.cisloOrientacniPismeno or ''}"
    return Address(
        text=a.textovaAdresa,
        street=a.nazevUlice,
        house_number=number or None,
        city=a.nazevObce,
        city_part=a.nazevCastiObce,
        postal_code=str(a.psc) if a.psc is not None else a.pscTxt,
        country_code=Country(a.kodStatu) if a.kodStatu else None,
        ruian_code=a.kodAdresnihoMista,
    )


def _account_number(u: ZverejnenyUcetType):
    if (a := u.standardniUcet) is not None:
        return f"{a.predcisli + '-' if a.predcisli else ''}{a.cislo}/{a.kodBanky}"
    return u.nestandardniUcet.cislo if u.nestandardniUcet else ""


def vat_from(ico: str, s: EkonomickySubjekt, entries: list[InformaceOSubjektuRozsireneType]):
    by_dic = {e.dic: e for e in entries}
    own = by_dic.get((s.dic or ico).removeprefix("CZ"))
    group = by_dic.get(s.dicSkDph.removeprefix("CZ")) if s.dicSkDph else None

    if group and group.typSubjektu is TypSubjektuDPHType.SKUPINA_DPH:
        dph, source = VatStatus.GROUP_MEMBER, group
    elif own and own.typSubjektu is TypSubjektuDPHType.PLATCE_DPH:
        dph, source = VatStatus.PAYER, own
    elif own and own.typSubjektu is TypSubjektuDPHType.IDENTIFIKOVANA_OSOBA:
        dph, source = VatStatus.IDENTIFIED_PERSON, own
    else:
        dph, source = VatStatus.NOT_REGISTERED, own

    # the registration state, not the `dic`: ARES keeps the DIČ of an ended registration too
    r = s.seznamRegistraci
    if r and r.stavZdrojeSkDph == "AKTIVNI":
        ares = VatStatus.GROUP_MEMBER
    elif r and r.stavZdrojeDph == "AKTIVNI":
        ares = VatStatus.PAYER  # ARES does not tell a payer from an identified person
    else:
        ares = VatStatus.NOT_REGISTERED
    agree = ares == dph or (ares, dph) == (VatStatus.PAYER, VatStatus.IDENTIFIED_PERSON)

    unreliable = [
        e
        for e in (own, group)
        if e
        and (
            e.nespolehlivyPlatce is NespolehlivyPlatceType.ANO
            or e.typSubjektu is TypSubjektuDPHType.NESPOLEHLIVA_OSOBA
        )
    ]
    accounts = source.zverejneneUcty.ucet if source and source.zverejneneUcty else []
    return Vat(
        status=dph if agree else Conflict(values={Source.ARES: ares, Source.DPH: dph}),
        dic=s.dic,
        group_dic=s.dicSkDph,
        unreliable=bool(unreliable),
        unreliable_since=min(
            (
                e.datumZverejneniNespolehlivosti
                for e in unreliable
                if e.datumZverejneniNespolehlivosti
            ),
            default=None,
        ),
        tax_office=source.cisloFu if source else None,
        bank_accounts=[
            BankAccount(number=_account_number(u), published_since=u.datumZverejneni)
            for u in accounts
            if u.datumZverejneniUkonceni is None
        ],
    )


def vat_from_ares(s: EkonomickySubjekt):
    """The DIČ from ARES alone, without `Part.VAT` or when DPH did not answer."""
    return Vat(
        status=None,
        dic=s.dic,
        group_dic=s.dicSkDph,
        unreliable=None,
        unreliable_since=None,
        tax_office=None,
        bank_accounts=None,
    )


def data_boxes_from_ros(records: list[ZaznamRos]):
    current = [r for r in records if r.stavSubjektu == "AKTIVNI"]
    # ARES code list StavUdajeRos: ROS marks a wrong box `nespravny`; `nedefinovany` stays
    boxes = {
        d.identifikatorDs: d
        for r in current
        for d in r.datoveSchranky or []
        if d.identifikatorDs and d.platnostUdajeRos != "nespravny"
    }
    return [
        DataBox(id=i, type=DataBoxType(t) if (t := d.typDatoveSchranky) else None)
        for i, d in boxes.items()
    ]


def representatives_from_vr(records: list[ZaznamVr]):
    record = next((r for r in records if r.primarniZaznam), None)
    result: list[Representative] = []
    for body in record.statutarniOrgany or [] if record else []:
        for m in body.clenoveOrganu or []:
            role = m.clenstvi.funkce if m.clenstvi else None
            if m.datumVymazu or (role and role.zanikFunkce) or m.skrytyUdaj:
                continue
            f = m.fyzickaOsoba or FyzickaOsobaVr()
            c = m.pravnickaOsoba or PravnickaOsobaVr()
            result.append(
                Representative(
                    body=body.nazevOrganu,
                    role=role.nazev if role and role.nazev else m.nazevAngazma,
                    since=role.vznikFunkce if role and role.vznikFunkce else m.datumZapisu,
                    title_before=f.titulPredJmenem,
                    first_name=f.jmeno,
                    last_name=f.prijmeni,
                    title_after=f.titulZaJmenem,
                    birth_date=f.datumNarozeni,
                    ico=c.ico,
                    name=c.obchodniJmeno,
                )
            )
    return result


def insolvency_from(data: list[IsirWsCuzkData | None]):
    proceedings = [
        InsolvencyProceeding(
            file_number=f"{d.druhVec} {d.bcVec}/{d.rocnik}",
            court=d.nazevOrganizace,
            state=d.druhStavKonkursu,
            ongoing=d.druhStavKonkursu not in _FINISHED_STATES,
            declared=d.datumPmZahajeniUpadku,
            ended=d.datumPmUkonceniUpadku,
            url=d.urlDetailRizeni,
        )
        for d in data
        if d
    ]
    return Insolvency(ongoing=any(p.ongoing for p in proceedings), proceedings=proceedings)


def subject_from_ares(
    ico: str,
    s: EkonomickySubjekt,
    person: AngazovanaOsobaRzp | None,
    vat: Vat | None,
    data_boxes: list[DataBox] | None,
    representatives: list[Representative] | None,
    insolvency: Insolvency | None,
    errors: dict[Source, str],
) -> Company | Person:
    address = address_from_ares(s.sidlo) if s.sidlo else None
    legal_form = LegalForm(s.pravniForma) if s.pravniForma else None
    nace = [Nace(c) for c in s.czNace or []]
    if s.pravniForma not in PERSON_LEGAL_FORMS:
        return Company(
            ico=ico,
            name=s.obchodniJmeno,
            address=address,
            legal_form=legal_form,
            nace=nace,
            established=s.datumVzniku,
            ceased=s.datumZaniku,
            vat=vat,
            data_boxes=data_boxes,
            insolvency=insolvency,
            errors=errors,
            in_ares=True,
            representatives=representatives,
        )
    p = person or AngazovanaOsobaRzp()
    return Person(
        ico=ico,
        name=s.obchodniJmeno,
        address=address,
        legal_form=legal_form,
        nace=nace,
        established=s.datumVzniku,
        ceased=s.datumZaniku,
        vat=vat,
        data_boxes=data_boxes,
        insolvency=insolvency,
        errors=errors,
        in_ares=True,
        title_before=p.titulPredJmenem,
        first_name=p.jmeno,
        last_name=p.prijmeni,
        title_after=p.titulZaJmenem,
        birth_date=p.datumNarozeni,
        sex=sex_from(s.dic, p.datumNarozeni),
    )


def subject_from_isir(ico: str, d: IsirWsCuzkData, insolvency: Insolvency) -> Company | Person:
    """A subject that ARES no longer knows, from the debtor data of its ISIR proceeding."""
    address = Address(
        text=None,
        street=d.ulice,
        house_number=d.cisloPopisne,
        city=d.mesto,
        city_part=None,
        postal_code=d.psc.replace(" ", "") if d.psc else None,
        country_code=None,
        ruian_code=None,
    )
    if not (d.jmeno or d.datumNarozeni or d.rc):
        return Company(
            ico=ico,
            name=d.nazevOsoby,
            address=address,
            legal_form=None,
            nace=[],
            established=None,
            ceased=None,
            vat=None,
            data_boxes=None,
            insolvency=insolvency,
            errors={},
            in_ares=False,
            representatives=None,
        )
    return Person(
        ico=ico,
        name=None,
        address=address,
        legal_form=None,
        nace=[],
        established=None,
        ceased=None,
        vat=None,
        data_boxes=None,
        insolvency=insolvency,
        errors={},
        in_ares=False,
        title_before=d.titulPred,
        first_name=d.jmeno,
        last_name=d.nazevOsoby,
        title_after=d.titulZa,
        birth_date=d.datumNarozeni,
        sex=sex_from(d.rc.replace("/", "") if d.rc else None, d.datumNarozeni),
    )


class ChangeType(StrEnum):
    """ARES code list TypZmenyAres."""

    CREATED = "INS"
    UPDATED = "UPD"
    DELETED = "DEL"


class Cursor(_Model):
    """Where `czreg.changes` stopped: the last batch read from each ARES notification source.

    Store it as JSON (`cursor.model_dump_json()`, `Cursor.model_validate_json(...)`) and pass it
    to the next call. ARES keeps about four weeks of batches, so use it at least weekly.
    """

    batches: dict[Source, int]  # an ARES register → the number of its last batch


class Change(_Model):
    path: str  # "vat.unreliable", "address.city", "representatives"
    old: object
    new: object


def diff(old: BaseModel, new: BaseModel, path: str = "") -> list[Change]:
    """What changed between two snapshots of a subject, e.g. of `czreg.get_subject` today and a
    week ago. A nested model is compared field by field, a list as a whole.

    A part that was not requested, or whose source did not answer (see `errors`), is None and
    shows as a change too.
    """
    changes: list[Change] = []
    for name in type(old).model_fields:
        a = cast("object", getattr(old, name))
        b = cast("object", getattr(new, name, None))
        at = f"{path}.{name}" if path else name
        if a == b:
            continue
        if isinstance(a, BaseModel) and type(a) is type(b):
            changes += diff(a, cast("BaseModel", b), at)
        else:
            changes.append(Change(path=at, old=a, new=b))
    return changes
