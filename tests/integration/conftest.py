"""Real Home Assistant core, in-process (pytest-homeassistant-custom-component)."""
from pathlib import Path

import custom_components
import pytest

# The harness ships its own `custom_components` package (testing_config), which is
# imported first and shadows ours, so add this repo's folder to its search path.
_OURS = str(Path(__file__).resolve().parents[2] / "custom_components")
if _OURS not in custom_components.__path__:
    custom_components.__path__.append(_OURS)


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


@pytest.fixture(autouse=True)
def fresh_shopping_list(hass):
    """The built-in Shopping List saves to the harness's shared testing_config
    folder, so a previous run's items would leak into the next. Start empty."""
    path = Path(hass.config.path(".shopping_list.json"))
    path.unlink(missing_ok=True)
    yield
    path.unlink(missing_ok=True)
