import pytest

pytestmark = [pytest.mark.live, pytest.mark.anyio]


async def test_live_brands_and_models(client):
    r = (await client.call_tool("hm_brands", {"query": "kia"})).structured_content
    assert r["brands"][0]["slug"] == "kia"
    m = (await client.call_tool("hm_models", {"brand": "kia"})).structured_content
    assert any(x["slug"] == "optima" for x in m["models"])


async def test_live_prices(client):
    r = (await client.call_tool("hm_prices", {"brand": "saipa", "model": "kiacerato"})).structured_content
    assert r["count"] > 0 and all(p["market_price"] > 1e8 for p in r["prices"])
    y = (await client.call_tool("hm_prices", {"brand": "saipa", "model": "kiacerato", "year": 1397})).structured_content
    assert y["trims"] and y["min_price"] <= y["max_price"]


async def test_live_search_detail_estimate_inspection(client):
    s = (await client.call_tool("hm_search_cars", {"brand": "kia", "sort": "price_desc"})).structured_content
    assert s["total"] > 0 and s["cars"]
    car = (await client.call_tool("hm_car", {"id": s["cars"][0]["id"]})).structured_content
    assert car["price"] == s["cars"][0]["price"]
    e = (
        await client.call_tool("hm_price_estimate", {"type_id": car["type_id"], "year": car["year"]})
    ).structured_content
    assert e["price_low"] <= e["price_high"]
    i = (await client.call_tool("hm_inspection_prices", {"car_id": car["car_id"]})).structured_content
    assert len(i["packages"]) == 3


async def test_live_branches(client):
    r = (await client.call_tool("hm_branches", {"province": "تهران"})).structured_content
    assert r["count"] > 0


async def test_live_price_list_history_reviews(client):
    pl = (
        await client.call_tool("hm_price_list", {"origin": "domestic", "price_max": 3000, "limit": 3})
    ).structured_content
    assert pl["total"] > 0 and all(c["price"] <= 3_000_000_000 for c in pl["cars"])
    c = pl["cars"][0]
    h = (
        await client.call_tool(
            "hm_price_history", {"brand": c["brand"], "model": c["model"], "year": c["year"], "type_id": c["type_id"]}
        )
    ).structured_content
    assert h["price"] > 0 and h["price_low"] <= h["price_high"] and len(h["history"]) >= 2
    r = (await client.call_tool("hm_reviews", {"brand": "saipa", "model": "kiacerato"})).structured_content
    assert r["pros"] and r["review"]


async def test_live_articles(client):
    a = (await client.call_tool("hm_articles", {"query": "تارا", "per_page": 2})).structured_content
    assert a["total"] > 0 and a["articles"]
    t = (await client.call_tool("hm_articles", {"id": a["articles"][0]["id"], "text_chars": 300})).structured_content
    assert t["title"] and t["text"]


async def test_live_new_search_filters(client):
    s = (await client.call_tool("hm_search_cars", {"brand": "toyota", "installments": True})).structured_content
    all_ = (await client.call_tool("hm_search_cars", {"brand": "toyota"})).structured_content
    assert 0 < s["total"] < all_["total"]
    i = (await client.call_tool("hm_inspection_prices", {"car_id": 2401, "time_slot": "discounted"})).structured_content
    std = (await client.call_tool("hm_inspection_prices", {"car_id": 2401})).structured_content
    assert i["packages"][0]["price"] < std["packages"][0]["price"]
