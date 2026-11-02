import httpx
import pytest
from conftest import fixture

from hamrah_mechanic_mcp import http

pytestmark = pytest.mark.anyio

BUILD = "BUILD123"
ND = f"/_next/data/{BUILD}"
API = "/api/v1"
TOOLS = {
    "hm_brands",
    "hm_models",
    "hm_prices",
    "hm_price_estimate",
    "hm_search_cars",
    "hm_car",
    "hm_inspection_prices",
    "hm_branches",
    "hm_price_history",
    "hm_price_list",
    "hm_reviews",
    "hm_articles",
}


@pytest.fixture
def site(api):
    """Fake site: home page with a buildId, plus the page data and API answers saved from the real site."""
    api["/"] = lambda r: httpx.Response(200, text=f'<script id="__NEXT_DATA__">{{"buildId":"{BUILD}"}}</script>')
    api[f"{ND}/cars-for-sale.json"] = {"pageProps": fixture("cfs.json")}
    api[f"{ND}/carprice/kia.json"] = {"pageProps": fixture("brand_prices.json")}
    api[f"{ND}/carprice/saipa/kiacerato.json"] = {"pageProps": fixture("model_prices.json")}
    api[f"{ND}/carprice/saipa/kiacerato/1397.json"] = {"pageProps": fixture("year_prices.json")}
    api[f"{API}/common/newexhibition"] = fixture("newexhibition.json")
    api[f"{API}/common/carbrandsnew/getcarmodelnew/exhibitionfeature"] = fixture("models.json")
    api[f"{API}/order/details"] = fixture("order_details.json")
    api[f"{API}/order/exhibitiongallery"] = fixture("gallery.json")
    api[f"{API}/price/newpricecalculation/raw-price"] = fixture("raw_price.json")
    api[f"{API}/price/pricechart"] = fixture("pricechart.json")
    api[f"{API}/car/inspection-cost"] = lambda r: httpx.Response(
        200, text={"1": "7180000", "2": "13820000", "3": "5540000"}[r.url.params["serviceTypeId"]]
    )
    api[f"{API}/location/province"] = fixture("provinces.json")
    api[f"{API}/location/autocenters"] = fixture("autocenters.json")
    api[f"{ND}/carprice/kia/sportage/2017/1276.json"] = {"pageProps": fixture("trim_prices.json")}
    api[f"{ND}/carprice/dakheli.json"] = {"pageProps": {"pricesList": fixture("domestic_prices.json")}}
    api[f"{ND}/carreview/saipa/kiacerato.json"] = {"pageProps": fixture("review_model.json")}
    api[f"{ND}/carreview/kia.json"] = {"pageProps": fixture("review_brand.json")}
    api["/mag/wp-json/wp/v2/posts"] = lambda r: httpx.Response(
        200, json=fixture("wp_posts.json"), headers={"x-wp-total": "78"}
    )
    api["/mag/wp-json/wp/v2/posts/69296"] = fixture("wp_post.json")
    return api


async def test_all_tools_are_read_only_and_described(client):
    tools = (await client.list_tools()).tools
    assert {t.name for t in tools} == TOOLS
    for t in tools:
        assert t.annotations.read_only_hint is True, t.name
        assert t.title and t.description.splitlines()[0].endswith("."), t.name
        assert "title" not in str(t.input_schema.get("properties", {}).values()), t.name


async def test_brands_filter_by_persian_or_english(client, site):
    r = (await client.call_tool("hm_brands", {"query": "کیا"})).structured_content
    assert r["brands"] == [{"slug": "kia", "name": "کیا", "id": 47}]
    assert (await client.call_tool("hm_brands", {"query": "TOYO"})).structured_content["count"] == 1
    assert "BUILD123" in str(site.calls[1].url)  # build id read from the home page


async def test_models_use_brand_id(client, site):
    r = (await client.call_tool("hm_models", {"brand": "kia"})).structured_content
    assert r["count"] > 3 and {"slug": "optima", "name": "اپتیما", "id": 46} in r["models"]
    assert site.calls[-1].url.params["brandId"] == "[47]"
    bad = await client.call_tool("hm_models", {"brand": "nope"})
    assert bad.is_error


async def test_prices_brand_model_and_year(client, site):
    r = (await client.call_tool("hm_prices", {"brand": "kia"})).structured_content
    assert r["models"][0]["price_brand"] == "saipa" and r["models"][0]["min_price"] == 3200000000
    r = (await client.call_tool("hm_prices", {"brand": "saipa", "model": "kiacerato"})).structured_content
    assert r["prices"][0]["year"] == 1398 and r["prices"][0]["type_id"] == 1206
    r = (await client.call_tool("hm_prices", {"brand": "saipa", "model": "kiacerato", "year": 1397})).structured_content
    assert [t["market_price"] for t in r["trims"]] == [4500000000, 4800000000, 4900000000]
    assert r["min_price"] == 4500000000
    assert (await client.call_tool("hm_prices", {"brand": "kia", "year": 1397})).is_error


async def test_price_estimate_merges_range_and_trend(client, site):
    r = (await client.call_tool("hm_price_estimate", {"type_id": 1075, "year": 2017})).structured_content
    assert (r["price_low"], r["price_high"], r["car_id"]) == (9888000000, 10712000000, 2401)
    assert r["monthly_change_percent"] == 9.6 and r["rising"] is True


def test_trend_is_null_without_direction():
    from hamrah_mechanic_mcp.cars import _trend

    assert _trend({"monthlyChange": 0.0, "isIncreased": None}) == {"monthly_change_percent": None, "rising": None}
    assert _trend({"monthlyChange": 2.5, "isIncreased": False}) == {"monthly_change_percent": 2.5, "rising": False}


async def test_search_builds_site_query(client, site):
    r = (
        await client.call_tool(
            "hm_search_cars",
            {
                "brand": "Kia",
                "model": "optima",
                "price_min": 1000,
                "year_max": 2018,
                "fuel": "hybrid",
                "sort": "price_desc",
            },
        )
    ).structured_content
    q = site.calls[-1].url.params
    assert q["brand"] == "kia" and q["price"] == "1000,50000" and q["year"] == "1380,2018"
    assert q["fuel"] == "hybrid " and q["sort"] == "1" and q["size"] == "24"
    assert r["total"] == 6 and r["cars"][0]["id"] == 3560384
    assert r["cars"][0]["url"].endswith("/cars-for-sale/kia/optima/3560384/")
    assert (await client.call_tool("hm_search_cars", {"model": "optima"})).is_error


async def test_car_has_no_seller_phone(client, site):
    r = (await client.call_tool("hm_car", {"id": 3560384, "photos": 2})).structured_content
    assert r["car_id"] == 2401 and r["type_id"] == 1075 and r["specs"]["fuelType"] == "بنزینی"
    assert len(r["photos"]) == 2 and "09000000000" not in str(r)


async def test_inspection_prices_by_car_or_type(client, site):
    r = (await client.call_tool("hm_inspection_prices", {"car_id": 2401})).structured_content
    assert [p["price"] for p in r["packages"]] == [7180000, 13820000, 5540000]
    r = (await client.call_tool("hm_inspection_prices", {"type_id": 1075, "year": 2017})).structured_content
    assert r["car_id"] == 2401
    assert (await client.call_tool("hm_inspection_prices", {})).is_error


async def test_branches_by_province_name(client, site):
    r = (await client.call_tool("hm_branches", {"province": "تهران"})).structured_content
    assert r["count"] == 2 and r["branches"][0]["hours"] == "9-20" and r["branches"][0]["open"] is True
    assert site.calls[-1].url.params["provinceId"] == "8"
    assert (await client.call_tool("hm_branches", {"province": "x"})).is_error


async def test_price_history_has_monthly_points(client, site):
    args = {"brand": "kia", "model": "sportage", "year": 2017, "type_id": 1276, "ads": 1}
    r = (await client.call_tool("hm_price_history", args)).structured_content
    assert r["price"] == 8000000000 and (r["price_low"], r["price_high"]) == (7680000000, 8320000000)
    assert len(r["history"]) == 6 and r["history"][-1] == {"month": "1405/7/15", "price": 7750000000}
    assert r["other_years_and_trims"][0] == {"year": 2025, "type_id": 2797, "trim": "1500 توربو", "price": 11100000000}
    assert len(r["for_sale"]) == 1
    assert (await client.call_tool("hm_price_history", {**args, "year": 2018})).is_error


async def test_price_list_filters_budget_and_brand(client, site):
    r = (await client.call_tool("hm_price_list", {"price_max": 3000, "sort": "price_asc"})).structured_content
    prices = [c["price"] for c in r["cars"]]
    assert prices == sorted(prices) and max(prices) <= 3_000_000_000 and r["total"] == len(prices) > 0
    r = (await client.call_tool("hm_price_list", {"brand": "irankhodro", "limit": 2})).structured_content
    assert r["count"] == 2 and {c["brand"] for c in r["cars"]} == {"irankhodro"}


async def test_reviews_model_and_brand(client, site):
    r = (
        await client.call_tool("hm_reviews", {"brand": "saipa", "model": "kiacerato", "text_chars": 100})
    ).structured_content
    assert r["owner_rating"] == 4 and r["pros"] and r["cons"] and r["rating_by_aspect"]["ایمنی"] == 4
    assert len(r["review"]) == 2 and len(r["review"][0]["text"]) <= 104
    assert len(r["owner_comments"]) == 3
    r = (await client.call_tool("hm_reviews", {"brand": "kia", "comments": 1})).structured_content
    assert {"name": "سراتو سایپا", "brand": "saipa", "model": "kiacerato"} in r["models"]
    assert len(r["owner_comments"]) == 1
    assert (await client.call_tool("hm_reviews", {"brand": "kia", "model": "nope"})).is_error


async def test_articles_list_search_and_read(client, site):
    r = (await client.call_tool("hm_articles", {"query": "تارا", "category": "reviews"})).structured_content
    q = [c for c in site.calls if c.url.path.endswith("/posts")][-1].url.params
    assert q["search"] == "تارا" and q["categories"] == "18"
    assert r["total"] == 78 and r["articles"][0]["id"] and r["articles"][0]["url"].startswith("https://")
    r = (await client.call_tool("hm_articles", {"id": 69296, "text_chars": 400})).structured_content
    assert "color:red" not in r["text"] and "var a" not in r["text"] and len(r["text"]) <= 403


async def test_search_installments_showroom_and_slot(client, site):
    await client.call_tool("hm_search_cars", {"installments": True, "showroom_only": True, "max_km": 0})
    q = site.calls[-1].url.params
    assert q["credit"] == "true" and q["autocenter"] == "true" and q["km"] == "0"
    r = (await client.call_tool("hm_inspection_prices", {"car_id": 2401, "time_slot": "premium"})).structured_content
    assert r["time_slot"] == "premium" and site.calls[-1].url.params["hourMode"] == "3"


async def test_stale_build_id_is_refreshed_once(client, api):
    hits = {"n": 0}

    def home(r):
        hits["n"] += 1
        build = "OLD" if hits["n"] == 1 else BUILD
        return httpx.Response(200, text=f'<x>"buildId":"{build}"</x>')

    api["/"] = home
    api[f"{ND}/cars-for-sale.json"] = {"pageProps": fixture("cfs.json")}
    r = (await client.call_tool("hm_brands", {})).structured_content
    assert r["count"] == 3 and hits["n"] == 2


async def test_http_errors_are_readable(client, api):
    api["/"] = lambda r: httpx.Response(403)
    r = await client.call_tool("hm_brands", {})
    assert r.is_error and "403" in r.content[0].text
    assert http.HOSTS == {"www.hamrah-mechanic.com"}


async def test_request_headers_match_the_sites_frontend(api):
    api["/api/v1/x"] = {}
    api["/mag/wp-json/wp/v2/posts"] = []
    api["/"] = lambda r: httpx.Response(200, text='"buildId":"B1"')
    api["/_next/data/B1/carprice.json"] = {"pageProps": {}}
    await http.fetch("/x")
    h = api.calls[-1].headers
    assert h["accept"] == "application/json" and h["referer"] == "https://www.hamrah-mechanic.com/"
    assert (h["sec-fetch-site"], h["sec-fetch-mode"], h["sec-fetch-dest"]) == ("same-origin", "cors", "empty")
    assert h["priority"] == "u=1, i" and "origin" not in h and h["accept-language"].startswith("fa-IR")
    await http.wp("/posts")
    assert api.calls[-1].headers["accept"] == "*/*" and api.calls[-1].headers["referer"].endswith("/mag/")
    await http.next_data("carprice")
    page, data = api.calls[-2].headers, api.calls[-1].headers
    assert (page["sec-fetch-mode"], page["sec-fetch-dest"], page["sec-fetch-site"]) == ("navigate", "document", "none")
    assert page["accept"].startswith("text/html") and "referer" not in page
    assert data["accept"] == "*/*" and data["x-nextjs-data"] == "1" and data["sec-fetch-mode"] == "cors"
