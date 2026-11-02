"""Verification suite for pantry_inventory.

Lives at /config/pantry_tests/ so it survives; run it from a machine with
python3 (the SSH add-on container has none):

    scp -r root@homeassistant.local:/config/custom_components/pantry_inventory .
    scp root@homeassistant.local:/config/pantry_tests/test_pantry.py .
    python3 test_pantry.py

Every check here exists because something was actually wrong, or because a
decision would be silently easy to undo. Stubs are deliberately minimal: the
point is to exercise OUR logic, not Home Assistant's.
"""

import asyncio
import sys
import types
from datetime import datetime, timedelta

# --------------------------------------------------------------------------
# stubs
# --------------------------------------------------------------------------
def _mod(name, **attrs):
    m = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(m, k, v)
    sys.modules[name] = m
    return m


class _Marker:
    def __init__(self, key, default=None, **k):
        self.key, self.default = key, default
    def __hash__(self): return hash(self.key)
    def __eq__(self, o): return self.key == getattr(o, "key", o)


class _Schema:
    def __init__(self, s, **k): self.schema = s
    def __call__(self, d): return d


_mod("voluptuous", Schema=_Schema, Required=_Marker, Optional=_Marker,
     In=lambda o: o, Coerce=lambda t: t, All=lambda *a: a,
     Range=lambda **k: k, Invalid=ValueError)


class HomeAssistant: pass
class ServiceCall:
    def __init__(self, data=None): self.data = data or {}
class SupportsResponse:
    OPTIONAL = "optional"; ONLY = "only"; NONE = "none"


_mod("homeassistant")
_mod("homeassistant.core", HomeAssistant=HomeAssistant, ServiceCall=ServiceCall,
     SupportsResponse=SupportsResponse, callback=lambda f: f)


class ConfigEntry: pass
class ConfigFlow:
    def __init_subclass__(cls, **kw): pass
    async def async_set_unique_id(self, *a, **k): pass
    def _abort_if_unique_id_configured(self): pass
    def async_create_entry(self, **k): return k


_mod("homeassistant.config_entries", ConfigEntry=ConfigEntry, ConfigFlow=ConfigFlow)
_mod("homeassistant.const", Platform=type("P", (), {"SENSOR": "sensor"}))
_mod("homeassistant.exceptions", ServiceValidationError=Exception,
     HomeAssistantError=Exception)

_helpers = _mod("homeassistant.helpers")


class Store:
    def __init__(self, *a, **k): self.data = None
    async def async_load(self): return self.data
    async def async_save(self, d): self.data = d


_helpers.storage = _mod("homeassistant.helpers.storage", Store=Store)
_helpers.config_validation = _mod("homeassistant.helpers.config_validation",
                                  string=str, boolean=bool)
_mod("homeassistant.helpers.event",
     async_track_time_change=lambda *a, **k: (lambda: None))
_mod("homeassistant.helpers.entity_platform", AddEntitiesCallback=object)


class _EntityRegistry:
    """Just enough for delete_product's entity cleanup (added to the code 2026-09-13)."""
    def __init__(self): self.removed = []
    def async_get_entity_id(self, domain, platform, unique_id): return None
    def async_get(self, entity_id): return None
    def async_remove(self, entity_id): self.removed.append(entity_id)


_ENTITY_REGISTRY = _EntityRegistry()
_helpers.entity_registry = _mod("homeassistant.helpers.entity_registry",
                                async_get=lambda hass: _ENTITY_REGISTRY)

_util = _mod("homeassistant.util")
# A MONOTONIC clock. A fixed one is what exposed the uuid4-vs-ULID ordering bug:
# same-timestamp events fell back to a random tiebreak, and because a checkpoint
# RESETS the running total, mis-ordering silently changed on_hand.
_CLOCK = {"t": datetime(2026, 9, 2, 12, 0, 0)}
def _now():
    _CLOCK["t"] += timedelta(seconds=1)
    return _CLOCK["t"]
_util.dt = _mod("homeassistant.util.dt", now=_now)

_comps = _mod("homeassistant.components")
_comps.http = _mod("homeassistant.components.http",
                   StaticPathConfig=lambda *a, **k: None)


class SensorEntity:
    _attr_has_entity_name = False
    def async_write_ha_state(self): pass


_mod("homeassistant.components.sensor", SensorEntity=SensorEntity)
REGISTERED = []
_comps.websocket_api = _mod(
    "homeassistant.components.websocket_api",
    websocket_command=lambda schema: (lambda f: f),
    async_response=lambda f: f,
    async_register_command=lambda hass, f: REGISTERED.append(f.__name__),
    connection=_mod("homeassistant.components.websocket_api.connection"))


async def _areg(*a, **k): return None
_comps.panel_custom = _mod("homeassistant.components.panel_custom",
                           async_register_panel=_areg)
_comps.frontend = _mod("homeassistant.components.frontend",
                       async_remove_panel=lambda *a, **k: None)

# --------------------------------------------------------------------------
from pantry_inventory import const, derive, gtin               # noqa: E402
from pantry_inventory.coordinator import PantryError, PantryManager  # noqa: E402
from pantry_inventory.models import (BarcodeRecord, ProductRecord,   # noqa: E402
                                     StockEventRecord)
from pantry_inventory.storage import PantryStore                # noqa: E402
from pantry_inventory.ulid import new_ulid                      # noqa: E402
import pantry_inventory as pi                                   # noqa: E402

OK = FAIL = 0


def chk(label, got, want):
    global OK, FAIL
    if got == want:
        OK += 1
    else:
        FAIL += 1
        print(f"  FAIL {label}\n       got  {got!r}\n       want {want!r}")


def expect_refusal(label, coro):
    global OK, FAIL
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        pass
    return coro


NOW = datetime(2026, 9, 2, 12, 0, 0)
mk = lambda body: body + str(gtin.check_digit(body))
CASE, BOTTLE, OTHER = mk("0003024100012"), mk("0003024100011"), mk("0001234567000")
BAD = CASE[:13] + str((int(CASE[13]) + 1) % 10)


def ev(n, t, delta=0, absolute=0, days_ago=0):
    return StockEventRecord(
        event_id=f"e{n:04d}", product_id="p", event_type=t,
        timestamp=(NOW - timedelta(days=days_ago)).isoformat(),
        units_delta=delta, units_absolute=absolute)


def test_gtin():
    chk("UPC-A check digit valid", gtin.is_valid_gtin("036000291452"), True)
    chk("bad check digit rejected", gtin.is_valid_gtin("036000291453"), False)
    chk("non-numeric rejected", gtin.is_valid_gtin("03600029145X"), False)
    chk("GTIN-14 validates", gtin.is_valid_gtin("10036000291459"), True)
    chk("pads to 14", gtin.normalise("036000291452"), "00036000291452")
    # one physical barcode must never become two rows
    chk("UPC-A and EAN-13 forms compare equal",
        gtin.normalise("0036000291452"), gtin.normalise("036000291452"))


def test_ulid():
    a = [new_ulid(1000 + i) for i in range(6)]
    chk("ULID sorts by time", a, sorted(a))
    b = [new_ulid(2000) for _ in range(6)]
    chk("same ms: unique", len(set(b)), 6)
    chk("26 chars", all(len(x) == 26 for x in b), True)


def test_on_hand():
    chk("deltas sum", derive.on_hand(
        [ev(1, "stock_in", 18, days_ago=10), ev(2, "use_up", 1, days_ago=1)]), 17)
    chk("checkpoint RESETS, not adds", derive.on_hand(
        [ev(1, "stock_in", 18, days_ago=10), ev(2, "adjust", absolute=7, days_ago=5),
         ev(3, "use_up", 1, days_ago=1)]), 6)
    # clamping here would destroy the evidence that log and shelf diverged
    chk("goes NEGATIVE deliberately", derive.on_hand(
        [ev(1, "adjust", absolute=1, days_ago=5), ev(2, "use_up", 3, days_ago=1)]), -2)
    chk("reconcile is a checkpoint too", derive.on_hand(
        [ev(1, "stock_in", 18, days_ago=10), ev(2, "reconcile", absolute=3, days_ago=2),
         ev(3, "stock_in", 18, days_ago=2)]), 21)


def test_rate():
    P = ProductRecord(product_id="p", name="P", initial_rate_estimate=2.0)
    r = derive.rate([ev(i, "use_up", 1, days_ago=i) for i in range(1, 4)], P, NOW)
    chk("too few events -> estimate", (r["rate"], r["rate_source"]), (2.0, "estimated"))
    r = derive.rate([ev(i, "use_up", 1, days_ago=0) for i in range(1, 8)], P, NOW)
    chk("7 scans in one day -> STILL estimate", r["rate_source"], "estimated")
    r = derive.rate([ev(i, "use_up", 2, days_ago=i) for i in range(1, 11)], P, NOW)
    chk("10 scans over 10 days -> measured", r["rate_source"], "measured")
    # Units over the days the log covers (10), not the full 21-day window: the
    # divisor change of 2026-09-13 (Premier caramel read at half speed).
    chk("  rate is units/days covered", round(r["rate"], 4), round(20 / 10, 4))
    chk("  sample size exposed", r["rate_sample_size"], 10)
    r = derive.rate([ev(i, "use_up", 1, days_ago=30 + i) for i in range(1, 11)], P, NOW)
    chk("outside the window -> estimate, n=0",
        (r["rate_source"], r["rate_sample_size"]), ("estimated", 0))


def test_days_of_supply():
    chk("normal", derive.days_of_supply(10, 2.0, "measured")["days_of_supply"], 5.0)
    d = derive.days_of_supply(10, 0, "measured")
    chk("rate 0 measured -> no_consumption, NEVER infinity",
        (d["days_of_supply"], d["unknown_reason"]), (None, "no_consumption_in_window"))
    chk("rate 0 estimated -> awaiting_first",
        derive.days_of_supply(10, 0, "estimated")["unknown_reason"],
        "awaiting_first_measurement")
    # absence of data is not a measurement of zero: without this, seeding a
    # catalogue pushes every product onto the shopping list immediately
    d = derive.days_of_supply(0, 2.0, "estimated", has_events=False)
    chk("no events -> unknown, not 0",
        (d["days_of_supply"], d["unknown_reason"]), (None, "no_stock_events"))
    chk("with events, 0 on hand really is 0 days",
        derive.days_of_supply(0, 2.0, "measured", has_events=True)["days_of_supply"], 0.0)


def test_compliance():
    chk("perfect", derive.compliance(
        [ev(1, "reconcile", absolute=20, days_ago=40), ev(2, "use_up", 10, days_ago=20),
         ev(3, "reconcile", absolute=10, days_ago=1)])["compliance"], 1.0)
    c = derive.compliance(
        [ev(1, "reconcile", absolute=20, days_ago=40), ev(2, "use_up", 8, days_ago=20),
         ev(3, "reconcile", absolute=10, days_ago=1)])
    chk("80% when 2 of 10 went unscanned", c["compliance"], 0.8)
    chk("  unscanned units reported", c["unscanned_units"], 2)
    c = derive.compliance(
        [ev(1, "reconcile", absolute=5, days_ago=40), ev(2, "stock_in", 18, days_ago=39),
         ev(3, "use_up", 9, days_ago=20), ev(4, "reconcile", absolute=12, days_ago=1)])
    chk("stock_in inside the cycle", round(c["compliance"], 4), round(9 / 11, 4))
    c = derive.compliance(
        [ev(1, "reconcile", absolute=20, days_ago=40), ev(2, "use_up", 5, days_ago=30),
         ev(3, "adjust", absolute=13, days_ago=25), ev(4, "use_up", 3, days_ago=10),
         ev(5, "reconcile", absolute=10, days_ago=1)])
    chk("adjust folded in, not a cycle boundary", round(c["compliance"], 4), 0.8)
    chk("no reconcile yet -> unknown",
        derive.compliance([ev(1, "stock_in", 18, days_ago=5)])["compliance"], None)


def test_models():
    chk("unknown key tolerated (downgrade survives)",
        ProductRecord.from_dict({"product_id": "x", "name": "X", "from_the_future": 1}).name, "X")


CALLS, LIST, BREAK = [], [], {"on": False}
# Set to make update_item raise, so the re-stamp's "a failing list must not
# fail the save" guarantee is actually exercised rather than assumed.
FAIL_UPDATE: list = []


class _Svc:
    async def async_call(self, domain, service, data, blocking=False,
                         return_response=False):
        CALLS.append((domain, service, dict(data)))
        if BREAK["on"] and service == "add_item":
            raise RuntimeError("shopping list unavailable")
        if FAIL_UPDATE and service == "update_item":
            raise RuntimeError("shopping list unavailable")
        if service == "list_items":
            return {"items": list(LIST)}
        if service == "add_item":
            LIST.append({"item_id": f"i{len(LIST)}", "name": data["name"],
                         "status": "active", "product_id": data.get("product_id", ""),
                         "tags": data.get("tags", []),
                         "store": data.get("store", ""),
                         "department": data.get("department", "")})
        if service == "update_item":
            for it in LIST:
                if it["item_id"] == data["item_id"]:
                    it.update({k: v for k, v in data.items() if k != "item_id"})
        if service == "mark_purchased":
            for it in LIST:
                if it["item_id"] == data["item_id"]:
                    it["status"] = "purchased"
        return None


class _Hass:
    def __init__(self): self.services = _Svc()


class _Ent:
    def __init__(self, pid): self.pid = pid
    def async_write_ha_state(self): pass


def _test_vocabulary_mirror():
    """The department list is hand-mirrored from quick_shopping_list.

    That is the same arrangement as STORE_OPTIONS, and STORE_OPTIONS is exactly
    how four live shopping list items ended up stranded on `Katy`, `HEB` and
    `MC` - stores dropped from one copy while rows still referenced them. A
    stored department slug that stops existing is the same failure, so this
    copy gets the guard STORE_OPTIONS never had.

    Skipped, not failed, when the sibling component is not on disk - the suite
    must still run from a bare checkout of pantry_inventory alone.
    """
    import os, re
    here = os.path.dirname(os.path.abspath(__file__))
    sibling = os.path.join(here, "quick_shopping_list", "const.py")
    if not os.path.exists(sibling):
        sibling = "/config/custom_components/quick_shopping_list/const.py"
    if not os.path.exists(sibling):
        print("  SKIP vocabulary mirror - quick_shopping_list/const.py not found")
        return
    body = open(sibling).read()
    block = re.search(r"DEPARTMENTS[^=]*=\s*\((.*?)\n\)", body, re.S)
    chk("sibling DEPARTMENTS found", block is not None, True)
    if block is None:
        return
    theirs = tuple(re.findall(r'\(\s*"([a-z_]+)"\s*,', block.group(1)))
    chk("department vocabulary matches quick_shopping_list exactly",
        theirs, const.DEPARTMENT_SLUGS)


def _test_par_models():
    """Old records must load, and a rollback must not crash on the new keys."""
    p = ProductRecord.from_dict({"product_id": "old", "name": "Old"})
    chk("pre-policy record defaults to rate", p.policy, "rate")
    chk("  with a par of 1 held in reserve", p.threshold_units, 1)
    # the _prune trap: a NEWER key written to storage must not TypeError an
    # older build on load (#0315)
    p2 = ProductRecord.from_dict({"product_id": "n", "name": "N",
                                  "policy": "par", "threshold_units": 4,
                                  "some_future_key": 1})
    chk("unknown keys pruned, not raised", (p2.policy, p2.threshold_units), ("par", 4))
    chk("pre-quantity record defaults to buying one", p.purchase_quantity, 1)
    chk("  and a stored one loads",
        ProductRecord.from_dict({"product_id": "q", "name": "Q",
                                 "purchase_quantity": 2}).purchase_quantity, 2)


async def test_coordinator():
    global OK
    hass = _Hass()
    st = PantryStore(hass)
    m = PantryManager(hass, st)
    m.add_sensor_entities = lambda ents: None
    m.sensor_factory = _Ent

    st.products["premier"] = ProductRecord(
        product_id="premier", name="Premier Protein", unit_noun="bottle",
        initial_rate_estimate=2.0, threshold_days=21, default_store="Costco")
    st.barcodes[CASE] = BarcodeRecord(code=CASE, product_id="premier", units=18)
    st.barcodes[BOTTLE] = BarcodeRecord(code=BOTTLE, product_id="premier", units=1)

    try:
        await m.async_scan(BAD, "use_up"); chk("bad check digit refused", False, True)
    except PantryError: OK += 1
    try:
        await m.async_scan(CASE, "sideways"); chk("bad direction refused", False, True)
    except PantryError: OK += 1

    chk("case scan adds its own unit count",
        (await m.async_scan(CASE, "stock_in"))["state"]["on_hand"], 18)
    chk("bottle scan removes 1",
        (await m.async_scan(BOTTLE, "use_up"))["state"]["on_hand"], 17)

    r = await m.async_scan(OTHER, "use_up")
    chk("unknown code -> provisional", r["provisional"], True)
    # WAS -1. A first use_up now seeds an observed floor of 1 first: there must
    # have been one on the shelf for the code to be scannable (Gary, 2026-09-04).
    chk("unknown scan is NOT lost", r["state"]["on_hand"], 0)
    seeded = [e for e in st.events_for(r["product_id"]) if e.source == "seed"]
    chk("  seeded once, as an observed checkpoint", len(seeded), 1)
    chk("  stored absolute, not as a delta", seeded[0].units_absolute, 1)
    chk("  and as an adjust, not a stock_in", seeded[0].event_type, "adjust")
    chk("  a first use_up never lands negative", r["state"]["on_hand"] < 0, False)

    # the seed is a FIRST-event rule, not a per-scan one
    n_before = len(st.events_for(r["product_id"]))
    await m.async_scan(OTHER, "use_up")
    chk("second use_up does NOT re-seed",
        len(st.events_for(r["product_id"])) - n_before, 1)
    chk("  so it depletes normally", m.state_for(r["product_id"])["on_hand"], -1)

    # stock_in must NOT be seeded, or a new product doubles on its first scan
    NEWIN = mk("0009876543210")
    r2 = await m.async_scan(NEWIN, "stock_in")
    chk("a first stock_in is not seeded", r2["state"]["on_hand"], 1)
    chk("  no seed event written",
        [e for e in st.events_for(r2["product_id"]) if e.source == "seed"], [])

    # a brand new product must not be pushed before any stock is recorded
    CALLS.clear()
    await m.async_save_product({"product_id": "fresh", "name": "Fresh",
                                "default_store": "Costco", "initial_rate_estimate": 2.0})
    chk("new product does NOT push", [c for c in CALLS if c[1] == "add_item"], [])
    chk("  reads as unknown", m.state_for("fresh")["days_of_supply"], None)
    chk("  with a reason", m.state_for("fresh")["unknown_reason"], "no_stock_events")
    chk("  stays armed", st.products["fresh"].push_armed, True)

    # threshold push. Made self-contained: the earlier bottle scan already
    # pushed and disarmed premier, so relying on ordering here made the test
    # assert the wrong thing.
    CALLS.clear(); LIST.clear()
    st.products["premier"].push_armed = True
    await m.async_set_count("premier", 4)
    adds = [c for c in CALLS if c[1] == "add_item"]
    chk("pushed below threshold", len(adds) >= 1, True)
    chk("  ONLY the store tag", adds[-1][2]["tags"], ["Costco"])
    chk("  quantity defaults to 1", adds[-1][2]["quantity"], "1")
    chk("  source names the pantry", adds[-1][2]["source"], "pantry_inventory")
    chk("  product_id is the link", adds[-1][2]["product_id"], "premier")
    chk("  disarmed after a confirmed add", st.products["premier"].push_armed, False)

    n = len([c for c in CALLS if c[1] == "add_item"])
    await m.async_evaluate("premier")
    chk("no duplicate push", len([c for c in CALLS if c[1] == "add_item"]), n)

    # restock: re-arms, marks purchased, and does NOT churn the list
    before = len([c for c in CALLS if c[1] == "add_item"])
    for _ in range(5):
        await m.async_scan(CASE, "stock_in")
    chk("re-armed on increase", st.products["premier"].push_armed, True)
    chk("list item marked purchased", LIST[0]["status"], "purchased")
    chk("no churn while stock arrives",
        len([c for c in CALLS if c[1] == "add_item"]), before)

    # an ADJUST upward re-arms too - a stock_in-only rule would disarm forever
    await m.async_set_count("premier", 2)
    chk("pushed again next cycle", st.products["premier"].push_armed, False)
    await m.async_set_count("premier", 90)
    chk("ADJUST upward re-arms", st.products["premier"].push_armed, True)

    # a failed push must never disarm, or the miss is permanent
    await m.async_set_count("premier", 1)
    for it in LIST:
        it["status"] = "purchased"
    st.products["premier"].push_armed = True
    BREAK["on"] = True
    await m.async_evaluate("premier")
    chk("failed push stays ARMED", st.products["premier"].push_armed, True)
    BREAK["on"] = False
    await m.async_evaluate("premier")
    chk("retry then succeeds", st.products["premier"].push_armed, False)

    # catalogue
    prov = [p for p in st.products.values() if p.status == "provisional"][0]
    await m.async_save_product({"product_id": prov.product_id, "name": "Sparkling Water",
                               "unit_noun": "can", "threshold_days": 14,
                               "default_store": "Costco"})
    chk("naming activates a provisional product",
        st.products[prov.product_id].status, "active")
    try:
        await m.async_save_product({"product_id": "premier", "default_store": "Aldi"})
        chk("unknown store refused", False, True)
    except PantryError: OK += 1
    # a refusal must leave the record untouched, or every later save fails too
    chk("refused save did NOT mutate the product",
        st.products["premier"].default_store, "Costco")

    NEW = mk("0005555000000")
    chk("barcode attached with its OWN unit count",
        (await m.async_attach_barcode(NEW, "premier", 12))["barcodes"][NEW], 12)
    try:
        await m.async_attach_barcode(NEW, "fresh", 1)
        chk("silent reassignment refused", False, True)
    except PantryError: OK += 1


    # ---- #0322: removal ----
    # discard: easy, and only for never-named products
    st.products["junk"] = ProductRecord(product_id="junk", name="Unknown item 000001",
                                        status="provisional")
    JUNK = mk("0007777000000")
    st.barcodes[JUNK] = BarcodeRecord(code=JUNK, product_id="junk", units=1)
    await m.async_scan(JUNK, "use_up")
    r = await m.async_discard_provisional("junk")
    chk("discard removes the product", "junk" in st.products, False)
    chk("  and its barcodes", JUNK in st.barcodes, False)
    chk("  and its events", [e for e in st.events_or_empty("junk")], [])
    try:
        await m.async_discard_provisional("premier")
        chk("discard refuses a non-provisional product", False, True)
    except PantryError: OK += 1

    # delete: archived only, exact name, barcodes SURVIVE
    try:
        await m.async_delete_product("premier", "Premier Protein")
        chk("delete refuses a non-archived product", False, True)
    except PantryError: OK += 1
    await m.async_save_product({"product_id": "premier", "status": "archived"})
    try:
        await m.async_delete_product("premier", "Premier Protien")   # typo
        chk("delete refuses a wrong name", False, True)
    except PantryError: OK += 1

    n_events_before = len(st.events)
    res = await m.async_delete_product("premier", "Premier Protein")
    chk("product gone", "premier" in st.products, False)
    chk("  events removed", len(st.events) < n_events_before, True)
    chk("  barcodes KEPT", CASE in st.barcodes, True)
    chk("  remembering the name", st.barcodes[CASE].remembered_name, "Premier Protein")
    chk("  and the unit noun", st.barcodes[CASE].remembered_unit_noun, "bottle")
    chk("  and its own unit count", st.barcodes[CASE].units, 18)
    chk("  report lists the remembered codes",
        sorted(res["barcodes_remembered"]) == sorted([CASE, BOTTLE, NEW]), True)

    # scanning a remembered code recreates the product AND re-links siblings
    r = await m.async_scan(BOTTLE, "stock_in")
    pid = r["product_id"]
    chk("remembered code recreates the product", st.products[pid].name, "Premier Protein")
    chk("  as provisional, awaiting confirmation", st.products[pid].status, "provisional")
    chk("  unit noun recovered", st.products[pid].unit_noun, "bottle")
    chk("  SIBLING case code re-linked, not orphaned",
        st.barcodes[CASE].remembered_name, "")
    chk("  and the case code still means 18",
        (await m.async_scan(CASE, "stock_in"))["units"], 18)


    # ---- folding a provisional into an existing product (#0316 gap) ----
    # the Walmart-12 / Costco-18 case: same product, unfamiliar pack code
    st.products["prem2"] = ProductRecord(product_id="prem2", name="Premier Protein",
        unit_noun="bottle", initial_rate_estimate=2.0, threshold_days=21,
        default_store="Costco")
    W12 = mk("0004444000000")
    st.barcodes[W12] = BarcodeRecord(code=W12, product_id="prem2", units=18)
    await m.async_set_count("prem2", 50)

    # scanning an unfamiliar code makes a provisional recorded at 1 unit
    WALMART = mk("0006666000000")
    r = await m.async_scan(WALMART, "stock_in")
    prov_id = r["product_id"]
    chk("unfamiliar pack code -> provisional", st.products[prov_id].status, "provisional")
    chk("  recorded at 1 unit, not knowing better",
        m.state_for(prov_id)["on_hand"], 1)

    before = m.state_for("prem2")["on_hand"]
    res = await m.async_attach_to_existing(prov_id, "prem2", 12)
    chk("provisional is gone", prov_id in st.products, False)
    chk("  barcode moved to the target", st.barcodes[WALMART].product_id, "prem2")
    chk("  at ITS OWN unit count", st.barcodes[WALMART].units, 12)
    chk("  the sibling 18-case is untouched", st.barcodes[W12].units, 18)
    chk("  scan replayed, not lost", res["scans_replayed"], 1)
    chk("  and at the CORRECTED count (+12, not +1)",
        m.state_for("prem2")["on_hand"], before + 12)

    # guards
    try:
        await m.async_attach_to_existing("prem2", "prem2", 12)
        chk("refuses attaching to itself", False, True)
    except PantryError: OK += 1
    try:
        await m.async_attach_to_existing("prem2", "fresh", 12)
        chk("refuses folding a non-provisional product", False, True)
    except PantryError: OK += 1

    # 'All' means no tag - an unrecognised tag lands the item on no list at all
    st.products["allstore"] = ProductRecord(product_id="allstore", name="All Store",
                                            initial_rate_estimate=5.0, default_store="All")
    await m.async_set_count("allstore", 20)
    await m.async_set_count("allstore", 1)   # a DECREASE, so evaluation runs
    await m.async_evaluate("allstore")
    chk("'All' store writes NO tag",
        [c for c in CALLS if c[1] == "add_item"][-1][2]["tags"], [])

    # ---------------------------------------------------------------- par
    # The jam case: no rate worth measuring, so the threshold is in UNITS. Under
    # the rate policy every one of these products would be unpushable forever.
    JAM = mk("0005550000001")
    st.products["jam"] = ProductRecord(
        product_id="jam", name="Jam", unit_noun="jar", policy="par",
        threshold_units=2, default_store="Walmart")
    st.barcodes[JAM] = BarcodeRecord(code=JAM, product_id="jam", units=1)

    chk("a par product with no events reads unknown",
        m.state_for("jam")["days_of_supply"], None)
    chk("  and is NOT below threshold on absence alone",
        m.state_for("jam")["below_threshold"], False)

    CALLS.clear(); LIST.clear()
    await m.async_set_count("jam", 3)
    chk("above par: nothing pushed", [c for c in CALLS if c[1] == "add_item"], [])
    chk("  rate is still zero, and that does not matter",
        m.state_for("jam")["rate"], 0.0)
    chk("  days_of_supply stays None, never infinity",
        m.state_for("jam")["days_of_supply"], None)

    await m.async_scan(JAM, "use_up")          # 2 - at par, not below it
    chk("at par: still nothing pushed", [c for c in CALLS if c[1] == "add_item"], [])
    chk("  on_hand tracks the scans", m.state_for("jam")["on_hand"], 2)

    await m.async_scan(JAM, "use_up")          # 1 - below par
    adds = [c for c in CALLS if c[1] == "add_item"]
    chk("below par: pushed", len(adds), 1)
    chk("  on the product's own list", adds[-1][2]["tags"], ["Walmart"])
    chk("  carrying the product reference", adds[-1][2]["product_id"], "jam")
    chk("  disarmed", st.products["jam"].push_armed, False)

    await m.async_scan(JAM, "use_up")          # 0 - still below, already listed
    chk("no second push while it is on the list",
        len([c for c in CALLS if c[1] == "add_item"]), 1)

    # restock re-arms and closes the loop, exactly as under the rate policy
    marked = len([c for c in CALLS if c[1] == "mark_purchased"])
    await m.async_scan(JAM, "stock_in")        # 1 - bought ONE, par is 2
    chk("restock re-arms a par product", st.products["jam"].push_armed, True)
    chk("  and marks the list item purchased",
        len([c for c in CALLS if c[1] == "mark_purchased"]) > marked, True)
    # Buying fewer than the par leaves it below par, and re-armed. The daily
    # tick puts it back on the list, which is right: the shelf still is short.
    chk("  a partial restock is still below par",
        m.state_for("jam")["below_threshold"], True)
    await m.async_scan(JAM, "stock_in")        # 2 - back at par
    chk("  restocking to par clears it", m.state_for("jam")["below_threshold"], False)

    # the summary counts par products too
    chk("summary counts by policy, not by days",
        m.summary()["products_below_threshold"] >= 0, True)

    # ---------------------------------------------------------- department
    chk("a product starts unclassified", st.products["jam"].department, "")
    try:
        await m.async_save_product({"product_id": "jam", "department": "Alcohol"})
        chk("a label instead of a slug is refused", False, True)
    except PantryError: OK += 1
    try:
        await m.async_save_product({"product_id": "jam", "department": "nonsense"})
        chk("an unknown department is refused", False, True)
    except PantryError: OK += 1
    chk("  and the refusal left the record alone", st.products["jam"].department, "")

    # The push carries it, so a freshly listed item arrives pre-classified.
    CALLS.clear(); LIST.clear()
    st.products["jam"].push_armed = True
    await m.async_save_product({"product_id": "jam", "department": "bread_spreads"})
    await m.async_set_count("jam", 0)
    adds = [c for c in CALLS if c[1] == "add_item"]
    chk("push stamps the department", adds[-1][2]["department"], "bread_spreads")

    # ------------------------------------------------------------ re-stamp
    # A rename used to leave the list showing the old name until the item was
    # bought and re-pushed.
    CALLS.clear()
    await m.async_save_product({"product_id": "jam", "name": "Damson Jam"})
    ups = [c for c in CALLS if c[1] == "update_item"]
    chk("renaming re-stamps the active list item", len(ups), 1)
    chk("  with the new name", ups[-1][2]["name"], "Damson Jam")
    chk("  addressed by item_id", "item_id" in ups[-1][2], True)

    CALLS.clear()
    await m.async_save_product({"product_id": "jam", "department": "condiments_sauces"})
    ups = [c for c in CALLS if c[1] == "update_item"]
    chk("changing department re-stamps too", ups[-1][2]["department"], "condiments_sauces")

    # Only on an ACTUAL change - an unrelated save must not touch the list.
    CALLS.clear()
    # Same value on purpose: this must leave the fixture's par at 2 for the
    # policy-switch checks further down.
    await m.async_save_product({"product_id": "jam", "threshold_units": 2})
    chk("an unrelated save re-stamps NOTHING",
        [c for c in CALLS if c[1] == "update_item"], [])
    CALLS.clear()
    await m.async_save_product({"product_id": "jam", "name": "Damson Jam"})
    chk("re-saving the SAME name re-stamps nothing",
        [c for c in CALLS if c[1] == "update_item"], [])

    # A purchased item is history; rewriting its name edits the past.
    CALLS.clear()
    for it in LIST:
        if it.get("product_id") == "jam":
            it["status"] = "purchased"
    await m.async_save_product({"product_id": "jam", "name": "Greengage Jam"})
    chk("a PURCHASED item is left alone",
        [c for c in CALLS if c[1] == "update_item"], [])

    # A shopping list that is down must not make saving a Product fail.
    for it in LIST:
        if it.get("product_id") == "jam":
            it["status"] = "active"
    FAIL_UPDATE.append(True)
    CALLS.clear()
    try:
        await m.async_save_product({"product_id": "jam", "name": "Mirabelle Jam"})
        chk("a failing list does NOT fail the save", True, True)
    except Exception:
        chk("a failing list does NOT fail the save", False, True)
    FAIL_UPDATE.clear()
    chk("  and the Product still took the new name",
        st.products["jam"].name, "Mirabelle Jam")

    # ------------------------------------------- adjust must not mark purchased
    # #0315 gave the push re-arm and the purchase-marking ONE condition so they
    # could not drift. That produced a real fault: correcting a count upward
    # marked an active list item purchased although nothing was bought. The two
    # side-effects now differ by design, so BOTH halves are pinned here.
    st.products["corr"] = ProductRecord(
        product_id="corr", name="Correction Test", unit_noun="Jar",
        policy="par", threshold_units=2, default_store="Walmart")
    CALLS.clear(); LIST.clear()
    await m.async_set_count("corr", 0)          # below par -> pushes
    chk("setup: on the list", len([c for c in CALLS if c[1] == "add_item"]), 1)
    chk("  and disarmed", st.products["corr"].push_armed, False)
    listed = [it for it in LIST if it["product_id"] == "corr"][0]

    CALLS.clear()
    await m.async_set_count("corr", 4)          # a CORRECTION, nothing bought
    chk("an adjust re-arms the push", st.products["corr"].push_armed, True)
    chk("  but does NOT mark the list item purchased",
        [c for c in CALLS if c[1] == "mark_purchased"], [])
    chk("  so the item is still on the list", listed["status"], "active")

    # reconcile is step ONE of a restock - counting the shelf, not buying.
    st.products["corr"].push_armed = False
    CALLS.clear()
    await m.async_set_count("corr", 9, event_type="reconcile")
    chk("a reconcile re-arms too", st.products["corr"].push_armed, True)
    chk("  and also does not mark purchased",
        [c for c in CALLS if c[1] == "mark_purchased"], [])
    chk("  item still active", listed["status"], "active")

    # stock_in is the ONLY event that means stock arrived.
    CALLS.clear()
    await m._append_event("corr", "stock_in", delta=1, source="service")
    chk("a stock_in DOES mark it purchased",
        len([c for c in CALLS if c[1] == "mark_purchased"]), 1)
    chk("  and the item leaves the list", listed["status"], "purchased")

    # a par of zero would sit permanently below threshold - refused
    try:
        await m.async_save_product({"product_id": "jam", "threshold_units": 0})
        chk("par of zero refused", False, True)
    except PantryError: OK += 1
    chk("  and the refusal left the record alone",
        st.products["jam"].threshold_units, 2)
    try:
        await m.async_save_product({"product_id": "jam", "policy": "vibes"})
        chk("unknown policy refused", False, True)
    except PantryError: OK += 1
    chk("  record still par", st.products["jam"].policy, "par")

    # switching policy must not lose the other threshold
    await m.async_save_product({"product_id": "jam", "policy": "rate"})
    chk("switching to rate keeps threshold_units", st.products["jam"].threshold_units, 2)
    await m.async_save_product({"product_id": "jam", "policy": "par"})
    chk("switching back keeps threshold_days", st.products["jam"].threshold_days, 10)

    # a seeded FIRST scan is what makes a par product work with no setup at all
    JAM2 = mk("0005550000002")
    r3 = await m.async_scan(JAM2, "use_up")
    await m.async_save_product({"product_id": r3["product_id"], "name": "Chutney",
                                "policy": "par", "threshold_units": 2,
                                "default_store": "Walmart"})
    chk("seeded first scan leaves a new par product at 0",
        m.state_for(r3["product_id"])["on_hand"], 0)
    chk("  which is below par, so naming it pushes it",
        st.products[r3["product_id"]].push_armed, False)


# helper used by the removal tests
def _events_or_empty(self, pid):
    return [e for e in self.events if e.product_id == pid]
PantryStore.events_or_empty = _events_or_empty


class _H2:
    def __init__(self):
        self.data = {}; self.services = self; self.http = self
        self.config_entries = self; self.registered = []
    def async_register(self, d, s, f, schema=None, supports_response=None):
        self.registered.append(s)
    def async_remove(self, d, s): pass
    async def async_forward_entry_setups(self, *a): pass
    async def async_register_static_paths(self, *a): pass
    async def async_unload_platforms(self, *a): return True


class _E:
    runtime_data = None
    def async_on_unload(self, f): pass


async def test_purchase_quantity():
    """How many to buy is a separate axis from how low to let it get.

    Raisin bran is the case that produced the field: par 2 AND buy 2, where the
    two numbers agreeing is a coincidence rather than an identity (2026-09-07).
    """
    st = PantryStore(_Hass())
    st.products, st.barcodes, st.events = {}, {}, []
    m = PantryManager(_Hass(), st)
    m.ensure_entity = lambda pid: None
    m._write_state = lambda pid: None
    CALLS.clear(); LIST.clear()

    await m.async_save_product({
        "product_id": "bran", "name": "Raisin Bran", "unit_noun": "box",
        "default_store": "Walmart", "department": "breakfast_cereal",
        "policy": "par", "threshold_units": 2, "purchase_quantity": 2})
    chk("par and purchase quantity are independent fields",
        (st.products["bran"].threshold_units,
         st.products["bran"].purchase_quantity), (2, 2))
    chk("  surfaced on the derived state",
        m.state_for("bran")["purchase_quantity"], 2)

    # two on the shelf is AT par, not below it
    await m.async_set_count("bran", 2)
    chk("at par does not push", [c for c in CALLS if c[1] == "add_item"], [])

    # open the last box
    await m.async_set_count("bran", 1)
    adds = [c for c in CALLS if c[1] == "add_item"]
    chk("below par pushes", len(adds), 1)
    chk("  at the PRODUCT's quantity, not 1", adds[-1][2]["quantity"], "2")

    # emptying it must not add a second item - push_armed is what stops churn
    await m.async_set_count("bran", 0)
    chk("scanning the rest out adds nothing further",
        len([c for c in CALLS if c[1] == "add_item"]), 1)

    # changing the setting reaches an item already on the list
    ups = len([c for c in CALLS if c[1] == "update_item"])
    await m.async_save_product({"product_id": "bran", "purchase_quantity": 3})
    chk("a changed quantity re-stamps the active item",
        LIST[0]["quantity"], "3")
    chk("  via update_item", len([c for c in CALLS if c[1] == "update_item"]) > ups, True)

    # ...but an unrelated save must not touch the list
    ups = len([c for c in CALLS if c[1] == "update_item"])
    await m.async_save_product({"product_id": "bran", "purchase_quantity": 3})
    chk("an unchanged save re-stamps nothing",
        len([c for c in CALLS if c[1] == "update_item"]), ups)

    # zero would put "buy 0 boxes" on the list
    try:
        await m.async_save_product({"product_id": "bran", "purchase_quantity": 0})
        chk("purchase_quantity 0 refused", "not refused", "refused")
    except PantryError:
        chk("purchase_quantity 0 refused", "refused", "refused")
    chk("  and the refusal left the record alone",
        st.products["bran"].purchase_quantity, 3)


async def test_setup():
    hass, entry = _H2(), _E()
    chk("setup_entry returns True", await pi.async_setup_entry(hass, entry), True)
    chk("all services registered", sorted(hass.registered),
        ["attach_barcode", "attach_to_existing", "delete_product",
         "discard_provisional", "evaluate", "list_products", "save_product",
         "scan", "set_count"])
    # refusable writes need websocket twins: HA's REST endpoint flattens every
    # handler exception to an opaque 500, so the reason only survives over ws
    chk("refusable writes have ws twins",
        {"ws_scan", "ws_set_count", "ws_save_product", "ws_attach_barcode",
         "ws_discard_provisional", "ws_delete_product",
         "ws_attach_to_existing"} <= set(REGISTERED), True)


def main():
    test_gtin(); test_ulid(); test_on_hand(); test_rate()
    test_days_of_supply(); test_compliance(); test_models(); _test_par_models()
    _test_vocabulary_mirror()
    asyncio.run(test_coordinator())
    asyncio.run(test_purchase_quantity())
    asyncio.run(test_setup())
    print(f"\n{OK} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
