"""Hamrah Mechanic tools: car price lists, used cars for sale, one listing, inspection prices, branches."""

from __future__ import annotations

import asyncio
from typing import Annotated, Any, Literal

from pydantic import Field

from .http import SITE, ApiError, fetch, next_data
from .registry import tool

Slug = Annotated[
    str, Field(description="Brand slug from hm_brands, e.g. kia, saipa, irankhodro.", min_length=1, max_length=40)
]
Model = Annotated[
    str,
    Field(description="Model slug from hm_models, e.g. optima, kiacerato, peugeot207.", min_length=1, max_length=60),
]
TypeId = Annotated[int, Field(description="Trim id (carTypeId) from hm_prices rows or hm_models.", ge=1)]
Year = Annotated[
    int,
    Field(
        description="Model year as the site shows it: Solar Hijri (1397) for Iranian cars, Gregorian (2017) for imports.",
        ge=1380,
        le=2030,
    ),
]

# Values the site's filter menu uses (read from the filtersList of /cars-for-sale, 2026-10-31).
GEARBOX = Literal["manual", "automate"]
FUEL = Literal["gas", "cng", "hybrid", "Electric"]
BODY = Literal["sedan", "hatchback", "suv", "pickup", "coupe", "convertible", "van"]
COUNTRY = Literal["Imported", "ChineseAssembly", "Iranian"]
COLOR = Literal["White", "Black", "Silver", "Red", "Blue", "Yellow", "Brown", "Green"]
CITY = Literal[
    "tehran",
    "karaj",
    "isfahan",
    "shahriar",
    "ray",
    "fardis",
    "andisheh",
    "shahin shahr",
    "mohammadshahr",
    "garmdareh",
    "meshkindasht",
]
SORT = {"default": None, "price_asc": "0", "price_desc": "1", "newest_year": "4", "lowest_km": "5"}
INSPECTION = {1: "full inspection", 2: "VIP inspection", 3: "economy inspection"}
SLOTS = {"standard": 1, "discounted": 2, "premium": 3}  # hourMode
TOMAN_NOTE = "prices in Toman"


def _data(body: dict[str, Any]) -> Any:
    """Unwrap the API's {data: {result}, isSuccess} envelope."""
    if body.get("isSuccess") is False:
        raise ApiError(body.get("message") or "hamrah-mechanic.com rejected the request.")
    d = body["data"]
    return d.get("result", d)


def _row(r: dict[str, Any]) -> dict[str, Any]:
    return {
        "model": r.get("modelEnglishName"),
        "name": r.get("modelName"),
        "type": r.get("carTypeName"),
        "type_id": r.get("carTypeId"),
        "year": r.get("carYear"),
        "market_price": r.get("marketPrice"),
        "zero_km_listed": r.get("hasCarPriceZero") if r.get("hasCarPriceZero") is not None else r.get("existPriceZero"),
    }


def _trend(chart: dict[str, Any]) -> dict[str, Any]:
    """Monthly change and direction; both null when the site has no trend (it sends 0.0 and no direction)."""
    up = chart.get("isIncreased")
    return {"monthly_change_percent": None if up is None else chart.get("monthlyChange"), "rising": up}


def _card(c: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": c.get("orderId"),
        "name": c.get("carNamePersian", "").strip(),
        "brand": (c.get("brandEnglishName") or "").strip(),
        "model": (c.get("modelEnglishName") or "").strip(),
        "type": (c.get("carTypeName") or "").strip(),
        "year": c.get("carYear"),
        "price": c.get("price"),
        "km": c.get("km"),
        "gearbox": c.get("gearBoxPersian"),
        "color": c.get("carColorName"),
        "location": c.get("carLocation"),
        "inspected": any(f.get("title") == "کارشناسی شده" for f in c.get("footerFeatures") or []),
        "in_showroom": c.get("inAutoCenter") or None,
        "sold": c.get("isSold") or None,
        "coming_soon": c.get("comingSoon") or None,
        "url": SITE + c["exhibitionDetailUrl"] if c.get("exhibitionDetailUrl") else None,
    }


@tool("Car brands")
async def hm_brands(
    query: Annotated[
        str | None, Field(description="Part of a brand name, Persian or English (e.g. کیا, toyota). Omit for all.")
    ] = None,
) -> dict:
    """List the car brands Hamrah Mechanic knows, with the slug the other tools take.

    Use first when you need a brand slug. Then call hm_models for its models, or hm_prices for its price list.
    """
    pp = await next_data("cars-for-sale")
    q = (query or "").strip().lower()
    rows = [
        {"slug": b["brandEnglishName"], "name": b["brandName"].strip(), "id": b["brandId"]}
        for b in pp["brands"]
        if not q or q in b["brandName"].lower() or q in b["brandEnglishName"].lower()
    ]
    return {"count": len(rows), "brands": rows}


@tool("Car models of a brand")
async def hm_models(brand: Slug) -> dict:
    """List the models of one brand with their slugs and trims (types).

    Use after hm_brands. Model slugs go to hm_prices (market prices, which also lists the trims) and hm_search_cars
    (cars for sale).
    """
    brands = (await next_data("cars-for-sale"))["brands"]
    b = next((x for x in brands if x["brandEnglishName"].lower() == brand.lower()), None)
    if not b:
        raise ApiError(f"Unknown brand '{brand}'. Call hm_brands to see the slugs.")
    body = await fetch("/common/carbrandsnew/getcarmodelnew/exhibitionfeature", {"brandId": f"[{b['brandId']}]"})
    models = [
        {"slug": m["modelEnglishName"], "name": m["modelName"].strip(), "id": m["carModelId"]} for m in _data(body)
    ]
    return {"brand": b["brandName"].strip(), "count": len(models), "models": models}


@tool("Car market prices")
async def hm_prices(
    brand: Slug,
    model: Annotated[
        str | None,
        Field(description="Model slug (from hm_models, or `model` in a brand listing). Omit for the whole brand."),
    ] = None,
    year: Annotated[
        int | None,
        Field(description="Model year; needs `model`. Gives the price of every trim of that year.", ge=1380, le=2030),
    ] = None,
    limit: Annotated[int, Field(description="Most rows returned for a brand or model.", ge=1, le=200)] = 60,
) -> dict:
    """Get today's market (used and zero-km) prices of cars from Hamrah Mechanic's daily price list.

    Brand only: one summary line per model (price range, years, trims). With a model: the price of each trim and year.
    With model and year: that year's trims. Prices in Toman. Use brand slugs from hm_brands; take a type_id from the
    rows to call hm_price_estimate, or the model slug to call hm_search_cars for real ads.
    """
    brand = brand.lower()
    if year is not None and not model:
        raise ApiError("`year` needs `model`.")
    if model and year:
        pp = await next_data(f"carprice/{brand}/{model}/{year}")
        rows = pp["carsPriceList"]["carPriceOtherYearsDetails"]
        return {
            "updated": pp["carsPriceList"].get("lastUpdateTime"),
            "name": pp["yearDetail"].get("nickName"),
            "year": year,
            "min_price": pp["yearDetail"].get("minPrice"),
            "max_price": pp["yearDetail"].get("maxPrice"),
            "trims": [_row(r) for r in rows],
            "ads_url": SITE + pp["yearDetail"]["exhibitionLink"] if pp["yearDetail"].get("exhibitionLink") else None,
        }
    if model:
        pp = await next_data(f"carprice/{brand}/{model}")
        pl = pp["yearsPriceList"]
        rows = [_row(r) for r in pl["carPriceOtherYearsDetails"]]
        return {
            "updated": pl.get("lastUpdateTime"),
            "name": pp["modelDetail"].get("nickName"),
            "years": [pp["modelDetail"].get("minYear"), pp["modelDetail"].get("maxYear")],
            "count": len(rows),
            "prices": rows[:limit],
        }
    pp = await next_data(f"carprice/{brand}")
    cards = pp["modelsCardList"]
    return {
        "brand": pp["brandHeader"].get("brandName"),
        "updated": pp["modelPriceList"].get("lastUpdateTime"),
        "count": len(cards),
        "models": [
            {
                "name": c.get("carName"),
                "model": c.get("modelEnglishName"),
                "price_brand": c.get("mainBrandEnglishName"),
                "min_price": c.get("minPrice"),
                "max_price": c.get("maxPrice"),
                "years": [c.get("minYear"), c.get("maxYear")],
                "trims": [{"type_id": t["typeId"], "name": t["typeName"]} for t in c.get("modelTypesList", [])],
            }
            for c in cards[:limit]
        ],
        "note": "Pass `price_brand` as brand and `model` to hm_prices for per-trim, per-year prices. " + TOMAN_NOTE,
    }


@tool("Price estimate for one trim and year")
async def hm_price_estimate(type_id: TypeId, year: Year) -> dict:
    """Get the market price range and recent monthly change for one trim in one model year.

    Use with a type_id and year from hm_prices rows. The range is what Hamrah Mechanic pays or advises (priceDown to
    priceUp) in Toman; monthly_change_percent is the latest monthly change, only given for some trims. For the monthly
    price history use hm_price_history.
    """
    est, chart = await asyncio.gather(
        fetch("/price/newpricecalculation/raw-price", {"carTypeId": type_id, "year": year}),
        fetch("/price/pricechart", {"typeId": type_id, "year": year}),
        return_exceptions=True,
    )
    if isinstance(est, BaseException):
        raise est
    e = _data(est)
    c = {} if isinstance(chart, BaseException) else _data(chart)
    return {
        "name": e.get("carName"),
        "type": e.get("carTypeName"),
        "gearbox": e.get("gearBox"),
        "car_id": e.get("carId"),
        "price_low": e.get("priceDown"),
        "price_high": e.get("priceUp"),
        **_trend(c),
    }


@tool("Search used cars for sale")
async def hm_search_cars(
    brand: Annotated[str | None, Field(description="Brand slug from hm_brands (one only), e.g. toyota.")] = None,
    model: Annotated[str | None, Field(description="Model slug from hm_models; needs `brand`.")] = None,
    price_min: Annotated[
        int | None, Field(description="Lowest price in million Toman, e.g. 1000 for 1 billion.", ge=0)
    ] = None,
    price_max: Annotated[int | None, Field(description="Highest price in million Toman.", ge=0)] = None,
    year_min: Annotated[
        int | None,
        Field(description="Oldest model year (Solar 1395 or Gregorian 2016, as the ad shows).", ge=1380, le=2030),
    ] = None,
    year_max: Annotated[int | None, Field(description="Newest model year.", ge=1380, le=2030)] = None,
    max_km: Annotated[int | None, Field(description="Most kilometres driven; 0 gives zero-km cars only.", ge=0)] = None,
    gearbox: GEARBOX | None = None,
    fuel: FUEL | None = None,
    body: BODY | None = None,
    origin: Annotated[COUNTRY | None, Field(description="Imported, ChineseAssembly or Iranian.")] = None,
    color: COLOR | None = None,
    city: CITY | None = None,
    installments: Annotated[bool, Field(description="Only cars that can be bought in installments.")] = False,
    showroom_only: Annotated[
        bool, Field(description="Only the showrooms' own stock (delivered at any branch).")
    ] = False,
    sort: Annotated[
        Literal["default", "price_asc", "price_desc", "newest_year", "lowest_km"],
        Field(description="Order of results."),
    ] = "default",
    page: Annotated[int, Field(description="Page number, 24 ads each.", ge=1, le=100)] = 1,
) -> dict:
    """Search the used and zero-km cars Hamrah Mechanic's showrooms sell, with filters.

    Returns ad cards (price in Toman, km, year, city). Use hm_car with an ad id for the full details and photos, and
    hm_prices to compare with the market. Price, year and km filters are inclusive. `total` is the number of matches.
    A brand also matches its Iranian-assembled models; those cards add `maker` (e.g. Kia Cerato, maker saipa).
    """
    if model and not brand:
        raise ApiError("`model` needs `brand`.")
    q: dict[str, Any] = {"page": page, "size": 24}
    for k, v in {
        "brand": brand and brand.lower(),
        "model": model,
        "gearbox": gearbox,
        "fuel": "hybrid " if fuel == "hybrid" else fuel,  # the site's own value has a trailing space
        "bodytype": body,
        "country": origin,
        "colors": color,
        "city": city,
        "km": max_km,
        "credit": "true" if installments else None,
        "autocenter": "true" if showroom_only else None,
        "sort": SORT[sort],
    }.items():
        if v is not None:
            q[k] = v
    if price_min is not None or price_max is not None:
        q["price"] = f"{price_min or 0},{price_max if price_max is not None else 50000}"
    if year_min is not None or year_max is not None:
        q["year"] = f"{year_min or 1380},{year_max or 2030}"
    res = _data(await fetch("/common/newexhibition", q))
    cards = [_card(c) for c in res["list"]]
    if brand:  # Iranian-assembled cars carry the maker (saipa) as brandEnglishName; report the brand asked for
        for c in cards:
            if c["brand"] != brand.lower():
                c["maker"], c["brand"] = c["brand"], brand.lower()
    if sort == "price_asc":
        cards = [c for c in cards if (c["price"] or 0) > 1000]  # placeholder prices of 1 Toman sort first
    return {"total": res["totalCount"], "page": page, "count": len(cards), "cars": cards, "note": TOMAN_NOTE}


@tool("One car for sale")
async def hm_car(
    id: Annotated[int, Field(description="Ad id (orderId) from hm_search_cars, e.g. 3560384.", ge=1)],
    photos: Annotated[int, Field(description="How many photo links to return.", ge=0, le=20)] = 4,
) -> dict:
    """Get the full details of one car for sale: price, specs, condition, inspection notes, photos and showroom.

    Use after hm_search_cars. No phone numbers or seller data are returned. For the inspection fee of this model use
    hm_inspection_prices with its car_id.
    """
    d, gallery = await asyncio.gather(
        fetch("/order/details", {"orderId": id}),
        fetch("/order/exhibitiongallery", {"orderId": id}),
        return_exceptions=True,
    )
    if isinstance(d, BaseException):
        raise d
    ci = d["carInformation"]
    specs = {s["key"]: s["value"].strip() for s in d.get("carSpecifications", {}).get("specs", [])}
    pics = [] if isinstance(gallery, BaseException) or not isinstance(gallery, list) else gallery
    return {
        "id": id,
        "name": ci.get("nickName"),
        "brand": ci.get("carBrandName"),
        "model": ci.get("carModelName"),
        "type": ci.get("carTypeName"),
        "type_id": ci.get("carTypeId"),
        "car_id": ci.get("carId"),
        "year": ci.get("carYear"),
        "price": ci.get("price"),
        "offer_price": ci.get("offerPrice") if ci.get("isSpecialOffer") else None,
        "km": ci.get("km"),
        "gearbox": ci.get("gearBox"),
        "location": ci.get("visitingPlace"),
        "service_fee": ci.get("serviceFee"),
        "coming_soon": ci.get("comingSoon") or None,
        "specs": specs,
        "highlights": [f.strip() for f in d.get("carFeature", {}).get("features") or []],
        "perks": [f["title"] for f in ci.get("footerFeatures") or []],
        "about": d.get("descriptionPart", {}).get("description"),
        "photos": [p["largeImage"] for p in pics[:photos] if p.get("largeImage")],
        "note": TOMAN_NOTE,
    }


@tool("Car inspection prices")
async def hm_inspection_prices(
    car_id: Annotated[int | None, Field(description="car_id from hm_car or hm_price_estimate.", ge=1)] = None,
    type_id: Annotated[int | None, Field(description="Trim id, with `year`, instead of car_id.", ge=1)] = None,
    year: Annotated[int | None, Field(description="Model year, with `type_id`.", ge=1380, le=2030)] = None,
    time_slot: Annotated[
        Literal["standard", "discounted", "premium"],
        Field(description="Visit time slot: discounted is about 15% cheaper, premium adds 500,000 (VIP unchanged)."),
    ] = "standard",
) -> dict:
    """Get what Hamrah Mechanic charges to inspect a given car at its location, for each inspection package.

    Give car_id, or type_id with year. Three packages: full, VIP (adds contract drafting) and economy; prices are in
    Toman. The fee depends on the car's value and the time slot (discounted and premium slots were read from the price
    pattern of the site's hourMode 2 and 3, not from a label).
    """
    if car_id is None:
        if not (type_id and year):
            raise ApiError("Give car_id, or type_id and year.")
        car_id = _data(await fetch("/price/newpricecalculation/raw-price", {"carTypeId": type_id, "year": year}))[
            "carId"
        ]
    hour = SLOTS[time_slot]
    prices = await asyncio.gather(
        *(fetch("/car/inspection-cost", {"carId": car_id, "serviceTypeId": s, "hourMode": hour}) for s in INSPECTION)
    )
    return {
        "car_id": car_id,
        "time_slot": time_slot,
        "packages": [{"service": n, "price": p} for n, p in zip(INSPECTION.values(), prices, strict=True)],
        "note": TOMAN_NOTE,
    }


@tool("Hamrah Mechanic showrooms and inspection centers")
async def hm_branches(
    province: Annotated[
        str, Field(description="Province name in Persian (تهران, البرز, اصفهان...) or id (8 = Tehran).")
    ] = "تهران",
    inspection_only: Annotated[bool, Field(description="Only centers that do car inspection.")] = False,
) -> dict:
    """List Hamrah Mechanic's car showrooms and inspection centers in a province with address, hours and cars in stock.

    Use to say where a used car can be seen or inspected. The `location` of an ad from hm_search_cars names its branch.
    """
    provinces = await fetch("/location/province")
    pid = next(
        (p["id"] for p in provinces if str(p["id"]) == province.strip() or p["name"].strip() == province.strip()), None
    )
    if pid is None:
        raise ApiError(
            "Unknown province. Use a Persian name such as تهران, or an id from: "
            + ", ".join(p["name"] for p in provinces[:12])
        )
    centers = await fetch(
        "/location/autocenters", {"provinceId": pid, "onlyInspectionCenters": str(inspection_only).lower()}
    )
    return {
        "count": len(centers),
        "note": None
        if centers
        else "No showroom or inspection center listed in this province (Tehran and Alborz have them).",
        "branches": [
            {
                "name": c.get("title"),
                "slug": c.get("englishTitle"),
                "city": c.get("cityName"),
                "address": c.get("address"),
                "hours": f"{c['startHour']}-{c['endHour']}" if c.get("startHour") else None,
                "cars_in_stock": c.get("carCount"),
                "open": c.get("isActive") and not c.get("isComingSoon"),
            }
            for c in centers
        ],
    }
