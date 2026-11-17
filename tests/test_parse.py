import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from monitor import build_url, parse_availability  # noqa: E402

CFG = {
    "parts": {"AAAAALL/A": "Duo 256", "BBBBBLL/A": "Duo 512"},
    "max_distance_miles": 15,
    "store_allowlist": [],
}

PAYLOAD = {
    "body": {
        "stores": [
                    {
                        "storeName": "Fifth Avenue",
                        "state": "NY",
                        "storeNumber": "R095",
                        "storedistance": 0.9,
                        "storeDistanceWithUnit": "0.9 mi",
                        "partsAvailability": {
                            "AAAAALL/A": {
                                "pickupDisplay": "available",
                                "pickupSearchQuote": "Today",
                                "messageTypes": {"regular": {"storePickupProductTitle": "iPhone Duo 256GB"}},
                            },
                            "BBBBBLL/A": {"pickupDisplay": "unavailable"},
                        },
                    },
                    {
                        "storeName": "Short Hills",
                        "state": "NJ",
                        "storeNumber": "R999",
                        "storedistance": 22.0,
                        "storeDistanceWithUnit": "22.0 mi",
                        "partsAvailability": {"AAAAALL/A": {"pickupDisplay": "available"}},
                    },
        ]
    }
}


def test_filters_by_distance_and_availability():
    hits = parse_availability(PAYLOAD, CFG)
    assert len(hits) == 1
    h = hits[0]
    assert (h.store, h.part, h.product, h.quote) == ("Fifth Avenue", "AAAAALL/A", "iPhone Duo 256GB", "Today")


def test_allowlist_overrides_distance():
    cfg = {**CFG, "store_allowlist": ["short hills"], "states": []}
    hits = parse_availability(PAYLOAD, cfg)
    assert [h.store for h in hits] == ["Short Hills"]


def test_empty_payload():
    assert parse_availability({}, CFG) == []


def test_build_url():
    url = build_url(["AAAAALL/A", "BBBBBLL/A"], "10001")
    assert "parts.0=AAAAALL%2FA" in url and "parts.1=BBBBBLL%2FA" in url and "location=10001" in url


def test_title_filter_night_sky_256_512():
    from monitor import title_matches
    cfg = {"title_must_include": ["Night Sky"], "title_must_include_any": ["256GB", "512GB"]}
    assert title_matches("iPhone Duo 256GB Night Sky", cfg)
    assert title_matches("iPhone Duo 512GB Night Sky", cfg)
    assert not title_matches("iPhone Duo 1TB Night Sky", cfg)
    assert not title_matches("iPhone Duo 256GB Silver", cfg)


def test_parse_applies_title_filter():
    cfg = {**CFG, "title_must_include": ["Night Sky"]}
    assert parse_availability(PAYLOAD, cfg) == []  # titulo do fixture nao tem Night Sky


def test_state_filter_excludes_nj():
    cfg = {**CFG, "max_distance_miles": 50, "states": ["NY"]}
    assert [h.store for h in parse_availability(PAYLOAD, cfg)] == ["Fifth Avenue"]
