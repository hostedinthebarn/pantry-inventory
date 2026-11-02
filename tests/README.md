# Tests

- `test_pantry.py`: the fast suite, plain Python with minimal HA stubs, testing the pantry's own logic.
  `cd custom_components && python3 -I ../tests/test_pantry.py` (run from `custom_components` so the package imports).
  Set `QSL_CONST=/path/to/quick_shopping_list/const.py` to run the department-vocabulary guard against that list.
- `integration/`: real Home Assistant core in-process (`pytest-homeassistant-custom-component`), against HA's built-in Shopping List.
  `uv sync --python 3.13 && .venv/bin/python -m pytest`
