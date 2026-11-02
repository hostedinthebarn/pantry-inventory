"""Sensors: one per Product, plus three summaries."""

from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, POLICY_PAR
from .coordinator import PantryManager


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry,
                            async_add_entities: AddEntitiesCallback) -> None:
    manager: PantryManager = entry.runtime_data
    manager.add_sensor_entities = async_add_entities
    manager.sensor_factory = lambda pid: PantryProductSensor(manager, pid)

    entities: list[SensorEntity] = [
        PantrySummarySensor(manager, "products_below_threshold",
                            "Products Below Threshold", "mdi:alert-outline"),
        PantrySummarySensor(manager, "products_needing_naming",
                            "Products Needing Naming", "mdi:help-rhombus-outline"),
        PantrySummarySensor(manager, "overall_compliance",
                            "Scan Compliance", "mdi:barcode-scan"),
    ]
    manager.summary_entities = list(entities)

    for p in manager.get_products():
        ent = PantryProductSensor(manager, p.product_id)
        manager.product_entities[p.product_id] = ent
        entities.append(ent)

    async_add_entities(entities)


class PantrySummarySensor(SensorEntity):
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, manager: PantryManager, key: str, name: str, icon: str) -> None:
        self.manager = manager
        self.key = key
        self._attr_name = name
        self._attr_icon = icon

    @property
    def unique_id(self) -> str:
        return f"{DOMAIN}_{self.key}"

    @property
    def native_value(self):
        value = self.manager.summary().get(self.key)
        if self.key == "overall_compliance" and value is not None:
            return round(value * 100, 1)
        return value

    @property
    def native_unit_of_measurement(self):
        return "%" if self.key == "overall_compliance" else None


class PantryProductSensor(SensorEntity):
    """State is the number the product's own policy is thresholded on.

    Under the rate policy that is days_of_supply; under par it is on_hand. They
    are different quantities in different units, which is why the unit is a
    property rather than a class attribute - reporting a par product's stock as
    "2 d" would be a straightforward lie. Both figures are always in the
    attributes, so nothing is lost either way. There is no state_class on this
    sensor, so no long-term statistics break when a product changes policy.
    """

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, manager: PantryManager, product_id: str) -> None:
        self.manager = manager
        self.product_id = product_id

    @property
    def unique_id(self) -> str:
        return f"{DOMAIN}_{self.product_id}"

    @property
    def available(self) -> bool:
        return self.manager.get_product(self.product_id) is not None

    @property
    def name(self) -> str:
        p = self.manager.get_product(self.product_id)
        return p.name if p else self.product_id

    @property
    def native_unit_of_measurement(self):
        s = self.manager.state_for(self.product_id)
        return None if s.get("policy") == POLICY_PAR else "d"

    @property
    def native_value(self):
        """Under the rate policy: None when the rate is zero - NEVER a large
        number. `unknown` and `plenty in stock` want opposite responses (#0314).

        Under par: the count itself, which is always known once anything has
        been scanned, and negative when the log and the shelf have diverged.
        """
        s = self.manager.state_for(self.product_id)
        if s.get("policy") == POLICY_PAR:
            return s.get("on_hand") if s.get("event_count") else None
        dos = s.get("days_of_supply")
        return None if dos is None else round(dos, 1)

    @property
    def icon(self) -> str:
        s = self.manager.state_for(self.product_id)
        if s.get("on_hand", 0) < 0:
            return "mdi:alert-circle-outline"
        if s.get("policy") == POLICY_PAR:
            if not s.get("event_count"):
                return "mdi:help-circle-outline"
        elif s.get("days_of_supply") is None:
            return "mdi:help-circle-outline"
        if s.get("below_threshold"):
            return "mdi:package-variant"
        return "mdi:package-variant-closed"

    @property
    def extra_state_attributes(self) -> dict:
        """Both figures always ride here, including whichever one is the state -
        an automation should not have to know a product's policy to read its
        stock. Keeping days_of_supply out of the attributes for rate products is
        the existing behaviour and stays."""
        s = dict(self.manager.state_for(self.product_id))
        if s.get("policy") != POLICY_PAR:
            s.pop("days_of_supply", None)   # it is the state
        return s
