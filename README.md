# czreg

Typed async clients for the Czech public registers: ARES (VR, RES, RŽP, ROS, NRPZS, RPSH, RCNS, SZR, RŠ, CEÚ), ISIR, and the VAT payer register (DPH).

## Installation

```sh
uv add czreg
uv add 'czreg[ratelimit]'  # with the rate limits of the registers
```

## Usage

`czreg` puts all the registers together into one subject:

```python
from czreg import czreg

async with czreg() as cz:
    subject = await cz.get_subject("45274649")
    print(subject.name)  # ČEZ, a. s.
    print(subject.legal_form)  # 121
    print(await cz.describe(subject.legal_form))  # Akciová společnost
```

The basic data cost one ARES request. By default, `get_subject` also fetches every `Part`: `VAT`, `DATA_BOXES`, `REPRESENTATIVES`, and `INSOLVENCY`, one more request each. `include` picks only some of them; a part left out is `None`:

```python
from czreg import Part

subject = await cz.get_subject("45274649", include=Part.VAT | Part.INSOLVENCY)
print(subject.vat.status)  # payer
print(subject.insolvency.ongoing)  # False
print(subject.data_boxes)  # None
```

`Part.NONE` gives only the basic data from ARES: the IČO, DIČ (`vat.dic`), name, address, legal form, NACE codes, and the dates of establishment and cessation. For a natural person (a `Person`, not a `Company`), also the name, title, birth date, and sex from RŽP.

A subject that ARES no longer knows, but ISIR does (often a deleted one in insolvency), comes back from the ISIR data with `in_ares=False`; one that neither knows raises `NotFound`:

```python
subject = await cz.get_subject("27604128")
print(subject.in_ares)  # False
print(subject.name)  # Obchodní areál Prachanda, s.r.o.
print(subject.insolvency.proceedings[0].file_number)  # INS 4471/2015
```

`search` finds subjects in ARES by their name, 20 by default:

```python
from czreg import TooManyResults

result = await cz.search("cez distribuce", limit=10)
print(result.total)  # 1
print(result.hits[0].ico, result.hits[0].name)  # 24729035 ČEZ Distribuce, a. s.

try:
    await cz.search("novák")
except TooManyResults as exc:
    print(exc.found)  # 8579
```

ARES finds whole words only, in any order, with any case and diacritics: "Distribu" finds nothing. Over 1 000 matches, ARES returns none of them, and `offset` does not help: make the query narrower. A hit has the basic data only; `get_subject` gives the rest.

`diff` tells what changed between two snapshots of a subject, e.g. one saved a week ago and one from today:

```python
from czreg import Company, diff

old = Company.model_validate_json(saved_json)
new = await cz.get_subject("45274649")
for change in diff(old, new):
    print(change)  # path='address.city' old='Brno' new='Praha'
```

A nested part is compared field by field, a list as a whole. A part left out by `include`, or whose source did not answer (see `subject.errors`), is `None` and shows as a change too. `vat` is the exception: it always has the DIČ from ARES, and only its fields from DPH are `None`.

`changes` tells which subjects changed in the ARES registers, from the ARES notification batches. Store the cursor and pass it to the next call; then fetch only the subjects that changed:

```python
from czreg import Cursor, CursorExpired

cursor = await cz.changes_cursor()  # the first time
cursor_json = cursor.model_dump_json()

cursor = Cursor.model_validate_json(cursor_json)  # a day later
try:
    changed, cursor = await cz.changes(cursor)
except CursorExpired:  # ARES keeps about four weeks of batches
    ...  # fetch all the subjects again, and start with cz.changes_cursor()
else:
    for ico in changed.keys() & my_icos:
        print(ico, changed[ico])  # 45274649 {<Source.VR: 'vr'>: <ChangeType.UPDATED: 'UPD'>}
```

It costs one ARES request per register and one per new batch, however many subjects you watch. DPH (unreliable payers) and ISIR (insolvency) are not in the batches.

Each register also has its own client:

```python
from czreg.ares import AresClient
from czreg.dph import DphClient
from czreg.isir import IsirClient

async with AresClient() as ares:
    vr = await ares.get_vr("45274649")
    print(vr.zaznamy[0].obchodniJmeno[0].hodnota)  # ČEZ, a. s.

async with DphClient() as dph:
    status = await dph.get_status("45274649")
    print(status.statusPlatceDPH[0].nespolehlivyPlatce)  # NE

async with IsirClient() as isir:
    proceedings = await isir.get_by_ico("45274649")
    print(proceedings.data)  # []
```

To keep to the limits of the registers (ARES 500 requests a minute, ISIR 50 a minute and 3000 a day), install the `ratelimit` extra and turn them on:

```python
async with czreg(rate_limit=True) as cz: ...
async with AresClient(rate_limit=True) as ares: ...
```

Without asyncio:

```python
from czreg import get_subject_sync

subject = get_subject_sync("45274649")
```
