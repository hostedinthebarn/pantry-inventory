"""SW-82's done-when, against real HA: a clean instance can push to its built-in
Shopping List, and the config flow stores the choice."""
from homeassistant import config_entries
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

DOMAIN = "pantry_inventory"


async def _shopping_list(hass):
    sl = MockConfigEntry(domain="shopping_list")
    sl.add_to_hass(hass)
    assert await hass.config_entries.async_setup(sl.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get("todo.shopping_list") is not None


async def _items(hass):
    resp = await hass.services.async_call(
        "todo", "get_items", {"entity_id": "todo.shopping_list"},
        blocking=True, return_response=True)
    return resp["todo.shopping_list"]["items"]


async def test_push_reaches_the_builtin_shopping_list(hass):
    assert await async_setup_component(hass, "http", {})
    await _shopping_list(hass)
    entry = MockConfigEntry(domain=DOMAIN, unique_id=DOMAIN, options={
        "shopping_list": "todo.shopping_list", "stores": ["Aldi"]})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    await hass.services.async_call(DOMAIN, "save_product", {
        "product_id": "bran", "name": "Raisin Bran", "policy": "par",
        "threshold_units": 2, "purchase_quantity": 2, "default_store": "Aldi"},
        blocking=True)
    # Stocked first: a push only arms when stock rises (push_armed), which is
    # what stops a product nobody has bought from nagging.
    await hass.services.async_call(DOMAIN, "set_count", {"product_id": "bran", "units": 2},
                                   blocking=True)
    await hass.async_block_till_done()
    assert await _items(hass) == []
    await hass.services.async_call(DOMAIN, "set_count", {"product_id": "bran", "units": 1},
                                   blocking=True)
    await hass.async_block_till_done()
    items = await _items(hass)
    assert [(i["summary"], i["status"]) for i in items] == [("Raisin Bran ×2", "needs_action")]

    # a second drop doesn't add it twice
    await hass.services.async_call(DOMAIN, "set_count", {"product_id": "bran", "units": 0},
                                   blocking=True)
    await hass.async_block_till_done()
    assert len(await _items(hass)) == 1

    # renaming the product renames the item on the list
    await hass.services.async_call(DOMAIN, "save_product",
                                   {"product_id": "bran", "name": "Bran Flakes"}, blocking=True)
    await hass.async_block_till_done()
    assert [i["summary"] for i in await _items(hass)] == ["Bran Flakes ×2"]


async def test_config_flow_stores_the_list_and_stores(hass):
    assert await async_setup_component(hass, "http", {})
    await _shopping_list(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert result["type"] == "form"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"shopping_list": "todo.shopping_list", "stores": [" Costco", "Costco", ""]})
    assert result["type"] == "create_entry"
    assert result["options"] == {"shopping_list": "todo.shopping_list", "stores": ["Costco"]}


async def test_no_lists_aborts(hass):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert result["type"] == "abort" and result["reason"] == "no_lists"
