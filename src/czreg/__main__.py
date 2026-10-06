import argparse
import asyncio
from typing import cast

from .client import Part, czreg


async def _print(icos: list[str], include: Part):
    async with czreg() as cz:
        for subject in await asyncio.gather(*(cz.get_subject(i, include=include) for i in icos)):
            print(subject.model_dump_json())


def main():
    parser = argparse.ArgumentParser(prog="czreg", description=__doc__)
    parser.add_argument("ico", nargs="+")
    parser.add_argument(
        "--only",
        nargs="*",
        choices=[name.lower() for name in Part.__members__ if name not in ("NONE", "ALL")],
        help="the parts beyond the basic data (default: all); --only alone gives none",
    )
    args = parser.parse_args()
    icos = cast("list[str]", args.ico)
    only = cast("list[str] | None", args.only)
    include = Part.ALL if only is None else Part.NONE
    for name in only or []:
        include |= Part[name.upper()]
    asyncio.run(_print(icos, include))


if __name__ == "__main__":
    main()
