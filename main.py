import asyncio
import json
import math
import re
from pathlib import Path
from urllib.parse import quote
from prime import is_prime
import aiohttp


CLUB_ID = 52818

SEARCHES = [
    "Ditchfest",
    "DF",
]

REQUEST_DELAY = 2.0
TMX_REQUEST_DELAY = 0.3

HEADERS = {
    "User-Agent": "(personal project; contact: bowlergraveyard@mail.ru)",
    "Accept": "application/json",
}

CACHE_DIR = Path("cache")
CAMPAIGN_SEARCH_CACHE_DIR = CACHE_DIR / "campaign_search"
CAMPAIGN_CACHE_DIR = CACHE_DIR / "campaigns"
TMX_CACHE_DIR = CACHE_DIR / "tmx"

RESULTS_DIR = Path("results")


def clean_tm_name(name: str) -> str:
    # Цветовые коды: $f90, $0aa, $fff ...
    name = re.sub(
        r"\$[0-9a-fA-F]{3}",
        "",
        name,
    )

    # Форматирование: $w, $s, $o, $g ...
    name = re.sub(
        r"\$[A-Za-z]",
        "",
        name,
    )

    return name.strip()


def is_ditchfest_campaign(name: str) -> bool:
    clean = clean_tm_name(name)

    return (
        re.match(
            r"^(?:DITCHFEST|DF)\s+\d",
            clean,
            flags=re.IGNORECASE,
        )
        is not None
    )


# def is_prime(n: int) -> bool:
#     if n < 2:
#         return False

#     if n == 2:
#         return True

#     if n % 2 == 0:
#         return False

#     limit = math.isqrt(n)

#     divisor = 3

#     while divisor <= limit:
#         if n % divisor == 0:
#             return False

#         divisor += 2

#     return True


def ensure_directories():
    CACHE_DIR.mkdir(
        exist_ok=True,
    )

    CAMPAIGN_SEARCH_CACHE_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    CAMPAIGN_CACHE_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    TMX_CACHE_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    RESULTS_DIR.mkdir(
        exist_ok=True,
    )


def load_json(path: Path):
    with path.open(
        "r",
        encoding="utf-8",
    ) as f:
        return json.load(f)


def save_json(
    path: Path,
    data,
):
    with path.open(
        "w",
        encoding="utf-8",
    ) as f:
        json.dump(
            data,
            f,
            ensure_ascii=False,
            indent=2,
        )


def safe_filename(value: str) -> str:
    return re.sub(
        r"[^A-Za-z0-9_-]",
        "_",
        value,
    )


async def get_json(
    session: aiohttp.ClientSession,
    url: str,
):
    max_retries = 10

    for attempt in range(max_retries):
        async with session.get(url) as response:
            text = await response.text()

            if response.status == 429:
                retry_after = response.headers.get(
                    "Retry-After"
                )

                if retry_after:
                    try:
                        delay = float(
                            retry_after
                        )
                    except ValueError:
                        delay = 10
                else:
                    delay = min(
                        10 + attempt * 5,
                        60,
                    )

                print(
                    f"    RATE LIMIT 429 — "
                    f"waiting {delay:.0f}s..."
                )

                await asyncio.sleep(
                    delay
                )

                continue

            if response.status != 200:
                raise RuntimeError(
                    f"HTTP {response.status}\n"
                    f"URL: {url}\n"
                    f"{text[:1000]}"
                )

            try:
                return json.loads(
                    text
                )

            except json.JSONDecodeError as e:
                raise RuntimeError(
                    f"Response is not JSON\n"
                    f"URL: {url}\n"
                    f"Content-Type: "
                    f"{response.headers.get('Content-Type')}\n"
                    f"{text[:1000]}"
                ) from e

    raise RuntimeError(
        f"Too many 429 responses for {url}"
    )


async def get_json_cached(
    session: aiohttp.ClientSession,
    url: str,
    cache_path: Path,
):
    if cache_path.exists():
        print(
            f"    cache: {cache_path}"
        )

        return load_json(
            cache_path
        )

    data = await get_json(
        session,
        url,
    )

    save_json(
        cache_path,
        data,
    )

    await asyncio.sleep(
        REQUEST_DELAY
    )

    return data


async def search_campaigns(
    session: aiohttp.ClientSession,
    search: str,
):
    safe_search = re.sub(
        r"[^A-Za-z0-9_-]",
        "_",
        search,
    )

    first_cache = (
        CAMPAIGN_SEARCH_CACHE_DIR
        / f"{safe_search}_page_0.json"
    )

    first_url = (
        "https://trackmania.io/api/campaigns/club/0"
        f"?search={quote(search)}"
    )

    first = await get_json_cached(
        session,
        first_url,
        first_cache,
    )

    page_count = first[
        "pageCount"
    ]

    print()

    print(
        f'Search "{search}": '
        f"{page_count} pages"
    )

    campaigns = []

    for page in range(
        page_count
    ):
        print(
            f'  "{search}" page '
            f"{page + 1}/{page_count}"
        )

        if page == 0:
            data = first

        else:
            cache_path = (
                CAMPAIGN_SEARCH_CACHE_DIR
                / f"{safe_search}_page_{page}.json"
            )

            url = (
                "https://trackmania.io/api/"
                f"campaigns/club/{page}"
                f"?search={quote(search)}"
            )

            data = await get_json_cached(
                session,
                url,
                cache_path,
            )

        campaigns.extend(
            data.get(
                "campaigns",
                [],
            )
        )

    return campaigns


async def get_campaigns(
    session: aiohttp.ClientSession,
):
    campaigns_by_id = {}

    for search in SEARCHES:
        campaigns = await search_campaigns(
            session,
            search,
        )

        for campaign in campaigns:
            if (
                campaign.get("clubid")
                != CLUB_ID
            ):
                continue

            if not is_ditchfest_campaign(
                campaign.get(
                    "name",
                    "",
                )
            ):
                continue

            campaigns_by_id[
                campaign["id"]
            ] = campaign

    campaigns = list(
        campaigns_by_id.values()
    )

    campaigns.sort(
        key=lambda c: clean_tm_name(
            c["name"]
        )
    )

    return campaigns


async def load_campaign(
    session: aiohttp.ClientSession,
    campaign: dict,
):
    campaign_id = campaign[
        "id"
    ]

    cache_path = (
        CAMPAIGN_CACHE_DIR
        / f"{campaign_id}.json"
    )

    url = (
        "https://trackmania.io/api/campaign/"
        f"{CLUB_ID}/{campaign_id}"
    )

    return await get_json_cached(
        session,
        url,
        cache_path,
    )


async def get_tmx_map_by_uid(
    session: aiohttp.ClientSession,
    uid: str,
):
    cache_path = (
        TMX_CACHE_DIR
        / f"{safe_filename(uid)}.json"
    )

    if cache_path.exists():
        return load_json(
            cache_path
        )

    url = (
        "https://trackmania.exchange/"
        "api/maps/get_map_info/multi/"
        f"{quote(uid, safe='')}"
    )

    max_retries = 5

    for attempt in range(
        max_retries
    ):
        async with session.get(
            url
        ) as response:
            text = await response.text()

            if response.status == 429:
                delay = min(
                    5 + attempt * 5,
                    30,
                )

                print(
                    f"        TMX 429 — "
                    f"waiting {delay}s..."
                )

                await asyncio.sleep(
                    delay
                )

                continue

            if response.status == 404:
                data = []

                save_json(
                    cache_path,
                    data,
                )

                return data

            if response.status != 200:
                print(
                    f"        TMX HTTP "
                    f"{response.status}"
                )

                print(
                    f"        {text[:300]}"
                )

                return None

            try:
                data = json.loads(
                    text
                )

            except json.JSONDecodeError:
                print(
                    "        TMX returned "
                    "non-JSON response"
                )

                print(
                    f"        {text[:300]}"
                )

                return None

            save_json(
                cache_path,
                data,
            )

            await asyncio.sleep(
                TMX_REQUEST_DELAY
            )

            return data

    return None


def extract_tmx_id(
    tmx_data,
):
    if isinstance(
        tmx_data,
        list,
    ):
        if not tmx_data:
            return None

        tmx_map = tmx_data[0]

    elif isinstance(
        tmx_data,
        dict,
    ):
        # На случай ответа вида:
        # {"Results": [...]}
        for key in (
            "Results",
            "results",
            "Maps",
            "maps",
        ):
            value = tmx_data.get(
                key
            )

            if (
                isinstance(value, list)
                and value
            ):
                tmx_map = value[0]
                break

        else:
            tmx_map = tmx_data

    else:
        return None

    if not isinstance(
        tmx_map,
        dict,
    ):
        return None

    possible_fields = (
        "TrackID",
        "TrackId",
        "trackID",
        "trackId",
        "MapID",
        "MapId",
        "mapID",
        "mapId",
        "ID",
        "Id",
        "id",
    )

    for field in possible_fields:
        value = tmx_map.get(
            field
        )

        if value:
            try:
                return int(
                    value
                )
            except (
                TypeError,
                ValueError,
            ):
                pass

    return None


async def get_all_maps(
    session: aiohttp.ClientSession,
    campaigns: list[dict],
):
    maps_by_exchange_id = {}

    total_map_entries = 0

    trackmania_io_missing_exchangeid = 0
    tmx_recovered = 0
    really_missing_tmx = 0
    tmx_lookup_errors = 0

    tmx_entries = 0

    total = len(
        campaigns
    )

    for index, campaign in enumerate(
        campaigns,
        start=1,
    ):
        campaign_id = campaign[
            "id"
        ]

        campaign_name = clean_tm_name(
            campaign[
                "name"
            ]
        )

        print(
            f"[{index}/{total}] "
            f"{campaign_name} "
            f"(campaign ID {campaign_id})"
        )

        data = await load_campaign(
            session,
            campaign,
        )

        playlist = data.get(
            "playlist",
            [],
        )

        print(
            f"    maps: "
            f"{len(playlist)}"
        )

        for map_data in playlist:
            total_map_entries += 1

            exchange_id = map_data.get(
                "exchangeid"
            )

            uid = map_data.get(
                "mapUid"
            )

            map_name = clean_tm_name(
                map_data.get(
                    "name",
                    "",
                )
            )

            if not exchange_id:
                trackmania_io_missing_exchangeid += 1

                print(
                    f"    NO TMIO TMX ID: "
                    f"{map_name}"
                )

                if not uid:
                    print(
                        "        no UID"
                    )

                    really_missing_tmx += 1

                    continue

                tmx_data = await get_tmx_map_by_uid(
                    session,
                    uid,
                )

                if tmx_data is None:
                    print(
                        "        TMX lookup error"
                    )

                    tmx_lookup_errors += 1

                    continue

                if (
                    isinstance(
                        tmx_data,
                        list,
                    )
                    and len(
                        tmx_data
                    ) == 0
                ):
                    print(
                        "        NOT FOUND ON TMX"
                    )

                    really_missing_tmx += 1

                    continue

                exchange_id = extract_tmx_id(
                    tmx_data
                )

                if not exchange_id:
                    print(
                        "        TMX response received, "
                        "but map ID was not recognized"
                    )

                    if isinstance(
                        tmx_data,
                        dict,
                    ):
                        print(
                            "        top-level fields:",
                            list(
                                tmx_data.keys()
                            ),
                        )

                    elif (
                        isinstance(
                            tmx_data,
                            list,
                        )
                        and tmx_data
                        and isinstance(
                            tmx_data[0],
                            dict,
                        )
                    ):
                        print(
                            "        map fields:",
                            list(
                                tmx_data[0].keys()
                            ),
                        )

                    tmx_lookup_errors += 1

                    continue

                tmx_recovered += 1

                print(
                    f"        recovered: "
                    f"TMX {exchange_id}"
                )

            try:
                exchange_id = int(
                    exchange_id
                )
            except (
                TypeError,
                ValueError,
            ):
                print(
                    f"    INVALID TMX ID: "
                    f"{exchange_id}"
                )

                continue

            tmx_entries += 1

            if (
                exchange_id
                not in maps_by_exchange_id
            ):
                maps_by_exchange_id[
                    exchange_id
                ] = {
                    "exchange_id": (
                        exchange_id
                    ),
                    "name": (
                        map_name
                    ),
                    "uid": (
                        uid
                    ),
                    "campaigns": [
                        campaign_name
                    ],
                }

            else:
                existing = (
                    maps_by_exchange_id[
                        exchange_id
                    ]
                )

                if (
                    campaign_name
                    not in existing[
                        "campaigns"
                    ]
                ):
                    existing[
                        "campaigns"
                    ].append(
                        campaign_name
                    )

    stats = {
        "total_map_entries": (
            total_map_entries
        ),

        "trackmania_io_missing_exchangeid": (
            trackmania_io_missing_exchangeid
        ),

        "tmx_recovered": (
            tmx_recovered
        ),

        "really_missing_tmx": (
            really_missing_tmx
        ),

        "tmx_lookup_errors": (
            tmx_lookup_errors
        ),

        "tmx_entries": (
            tmx_entries
        ),

        "unique_tmx_maps": (
            len(
                maps_by_exchange_id
            )
        ),

        "duplicate_tmx_entries": (
            tmx_entries
            - len(
                maps_by_exchange_id
            )
        ),
    }

    return (
        maps_by_exchange_id,
        stats,
    )


def save_results(
    campaigns: list[dict],
    maps: dict,
    prime_maps: list[dict],
    stats: dict,
):
    campaign_output = []

    for campaign in campaigns:
        campaign_output.append(
            {
                "id": campaign[
                    "id"
                ],
                "name": clean_tm_name(
                    campaign[
                        "name"
                    ]
                ),
                "mapcount": (
                    campaign.get(
                        "mapcount"
                    )
                ),
            }
        )

    save_json(
        RESULTS_DIR
        / "campaigns.json",
        campaign_output,
    )

    all_maps = sorted(
        maps.values(),
        key=lambda m: m[
            "exchange_id"
        ],
    )

    save_json(
        RESULTS_DIR
        / "all_tmx_maps.json",
        all_maps,
    )

    save_json(
        RESULTS_DIR
        / "prime_tmx_maps.json",
        prime_maps,
    )

    save_json(
        RESULTS_DIR
        / "stats.json",
        stats,
    )

    txt_path = (
        RESULTS_DIR
        / "prime_tmx_maps.txt"
    )

    with txt_path.open(
        "w",
        encoding="utf-8",
    ) as f:
        for m in prime_maps:
            exchange_id = m[
                "exchange_id"
            ]

            name = m[
                "name"
            ]

            url = (
                "https://trackmania.exchange/"
                f"maps/{exchange_id}"
            )

            f.write(
                f"{exchange_id} — "
                f"{name} — "
                f"{url}\n"
            )

    markdown_path = (
        RESULTS_DIR
        / "prime_tmx_maps.md"
    )

    with markdown_path.open(
        "w",
        encoding="utf-8",
    ) as f:
        for m in prime_maps:
            exchange_id = m[
                "exchange_id"
            ]

            name = m[
                "name"
            ]

            url = (
                "https://trackmania.exchange/"
                f"maps/{exchange_id}"
            )

            f.write(
                f"{exchange_id} — "
                f"[{name}]({url})\n"
            )


async def main():
    ensure_directories()

    async with aiohttp.ClientSession(
        headers=HEADERS
    ) as session:

        print(
            "=" * 70
        )

        print(
            "SEARCHING CAMPAIGNS"
        )

        print(
            "=" * 70
        )

        campaigns = await get_campaigns(
            session
        )

        print()

        print(
            "Matching Ditchfest campaigns:",
            len(
                campaigns
            ),
        )

        print()

        for campaign in campaigns:
            print(
                campaign[
                    "id"
                ],
                clean_tm_name(
                    campaign[
                        "name"
                    ]
                ),
                f"({campaign.get('mapcount')} maps)",
            )

        print()

        print(
            "=" * 70
        )

        print(
            "LOADING MAPS"
        )

        print(
            "=" * 70
        )

        print()

        (
            maps,
            stats,
        ) = await get_all_maps(
            session,
            campaigns,
        )

        print()

        print(
            "=" * 70
        )

        print(
            "MAP STATISTICS"
        )

        print(
            "=" * 70
        )

        print(
            "Total campaign map entries:",
            stats[
                "total_map_entries"
            ],
        )

        print(
            "Missing exchangeid in TMIO:",
            stats[
                "trackmania_io_missing_exchangeid"
            ],
        )

        print(
            "Recovered via TMX UID:     ",
            stats[
                "tmx_recovered"
            ],
        )

        print(
            "Really missing from TMX:   ",
            stats[
                "really_missing_tmx"
            ],
        )

        print(
            "TMX lookup errors:         ",
            stats[
                "tmx_lookup_errors"
            ],
        )

        print(
            "Entries with TMX:          ",
            stats[
                "tmx_entries"
            ],
        )

        print(
            "Unique TMX maps:           ",
            stats[
                "unique_tmx_maps"
            ],
        )

        print(
            "Duplicate TMX entries:     ",
            stats[
                "duplicate_tmx_entries"
            ],
        )

        prime_maps = [
            m
            for m in maps.values()
            if is_prime(
                m[
                    "exchange_id"
                ]
            )
        ]

        prime_maps.sort(
            key=lambda m: m[
                "exchange_id"
            ]
        )

        print()

        print(
            "=" * 70
        )

        print(
            "RESULT"
        )

        print(
            "=" * 70
        )

        print(
            "Maps with prime TMX ID:",
            len(
                prime_maps
            ),
        )

        print()

        for m in prime_maps:
            exchange_id = m[
                "exchange_id"
            ]

            name = m[
                "name"
            ]

            url = (
                "https://trackmania.exchange/"
                f"maps/{exchange_id}"
            )

            print(
                f"{exchange_id} — "
                f"{name} — "
                f"{url}"
            )

        save_results(
            campaigns,
            maps,
            prime_maps,
            stats,
        )

        print()

        print(
            "=" * 70
        )

        print(
            "SAVED"
        )

        print(
            "=" * 70
        )

        print(
            "results/campaigns.json"
        )

        print(
            "results/all_tmx_maps.json"
        )

        print(
            "results/prime_tmx_maps.json"
        )

        print(
            "results/prime_tmx_maps.txt"
        )

        print(
            "results/prime_tmx_maps.md"
        )

        print(
            "results/stats.json"
        )


if __name__ == "__main__":
    asyncio.run(
        main()
    )