"""Constants for Pantry Inventory."""

DOMAIN = "pantry_inventory"
VERSION = "0.2.0"   # purchase_quantity: buy in fixed multiples

STORAGE_KEY = f"{DOMAIN}.storage"
STORAGE_VERSION_MAJOR = 1
STORAGE_VERSION_MINOR = 1

PANEL_URL = "pantry"
PANEL_NAME = "pantry-inventory-panel"
PANEL_TITLE = "Pantry"
PANEL_ICON = "mdi:cupboard-outline"   # a pantry, and distinct from the shopping list cart
PANEL_API_PATH = f"/{DOMAIN}_static"
# VERSION doubles as the cache-buster: HA serves panel assets with a long cache
# header, so an unbumped version means the tablet keeps stale JS (#0312).
PANEL_API_URL = f"{PANEL_API_PATH}/main.js?v={VERSION}"

# A restock is TWO events: `reconcile` (count what is left) then `stock_in`
# (scan the new packs). See ADR 0017.
EVENT_STOCK_IN = "stock_in"      # delta, +N
EVENT_USE_UP = "use_up"          # delta, -N
EVENT_ADJUST = "adjust"          # absolute, mid-cycle correction
EVENT_RECONCILE = "reconcile"    # absolute, closes a compliance period
EVENT_TYPES = [EVENT_STOCK_IN, EVENT_USE_UP, EVENT_ADJUST, EVENT_RECONCILE]
# Set-absolute events are checkpoints: on_hand derives forward from the most
# recent one. They store the OBSERVED count, never a computed delta.
CHECKPOINT_EVENTS = {EVENT_ADJUST, EVENT_RECONCILE}

PRODUCT_ACTIVE = "active"
PRODUCT_PROVISIONAL = "provisional"
PRODUCT_ARCHIVED = "archived"
PRODUCT_STATUSES = [PRODUCT_ACTIVE, PRODUCT_PROVISIONAL, PRODUCT_ARCHIVED]

RATE_WINDOW_DAYS = 21
# Both must hold - five scans in one afternoon is not a rate (#0314).
RATE_MIN_EVENTS = 5
RATE_MIN_DAYS = 7

RATE_SOURCE_ESTIMATED = "estimated"
RATE_SOURCE_MEASURED = "measured"

# "No consumption" must be distinguishable from "never calibrated": they mean
# opposite things (#0314).
REASON_NO_CONSUMPTION = "no_consumption_in_window"
REASON_AWAITING_FIRST = "awaiting_first_measurement"
# A product with no stock events has no RECORD, which is not the same as having
# none in the cupboard. Without this, seeding a catalogue pushes every product
# onto the shopping list before a single count has been entered.
REASON_NO_EVENTS = "no_stock_events"

# 10 days (Gary, 2026-09-02), measured in SHOPPING OPPORTUNITIES rather than
# consumption: 10 days means that if something runs out mid-week there are still
# two weekends available to replace it, and worst case one. That is the real
# constraint - not the Costco cycle length.
#
# The charting grill defaulted this to 21-28 to match
# the 4-8 week Costco cycle, but a threshold must sit comfortably BELOW the days
# a normal restock provides or the product is permanently flagged and the alert
# stops meaning anything - at 2 bottles/day, 21 days needs 42 on the shelf to
# clear. Per-product values still override this.
DEFAULT_THRESHOLD_DAYS = 10

# ---------------------------------------------------------------------------
# Reorder policy
# ---------------------------------------------------------------------------
# Some products have no consumption rate worth measuring - a jar of jam is used
# up over months, and fewer than RATE_MIN_EVENTS scans ever land inside the
# window, so days-of-supply is either unknown or a projection off a guessed
# estimate. A threshold expressed in DAYS cannot describe them.
#
# POLICY_PAR expresses the threshold in UNITS instead: push when fewer than
# `threshold_units` are on hand. No rate, no days-of-supply, no arithmetic.
#
# The alternative - setting initial_rate_estimate to 1.0 so days-of-supply
# equals on-hand - was rejected. It holds only until RATE_MIN_EVENTS scans land
# inside the window, at which point the measured rate takes over and the alert
# goes SILENT exactly when consumption is highest. It also makes the card read
# "2 days of supply" for something that lasts eight months, so the one screen
# you would check to sanity-check the system is lying.
POLICY_RATE = "rate"   # days_of_supply < threshold_days
POLICY_PAR = "par"     # on_hand < threshold_units
POLICIES = [POLICY_RATE, POLICY_PAR]
DEFAULT_POLICY = POLICY_RATE
# One. "Keep at least one on the shelf" is the whole point of a par product;
# anything higher is a deliberate choice, not a default.
DEFAULT_THRESHOLD_UNITS = 1

# ---------------------------------------------------------------------------
# Purchase quantity
# ---------------------------------------------------------------------------
# HOW MANY TO BUY, which is a different question from how low to let it get.
# The push used to hardcode "1", so a product bought in a fixed multiple was
# always understated on the list and corrected by hand every cycle.
#
# Deliberately NOT folded into threshold_units. Par asks "how low before I
# reorder", this asks "how many do I buy when I do", and raisin bran wants
# 2 for both by coincidence rather than by identity: par 2 flags the moment the
# last box is opened, and 2 is a pair because that is what fills the cereal
# container. Conflating them breaks in both directions - a par of 4 would flag
# with three boxes still on the shelf, and a purchase quantity of 1 would keep
# sending Gary back for the second box.
#
# It is a hint stamped on the shopping list item and NOTHING else: stock is
# scanned in per unit regardless, so inventory arithmetic never reads it. That
# is what keeps it from being a second, quieter source of truth about counts.
DEFAULT_PURCHASE_QUANTITY = 1

# A use_up scan against a product with NO stock events writes this as an
# `adjust` checkpoint first (Gary, 2026-09-04): there must have been at least
# one on the shelf for the barcode to be scannable, so the floor is 1 and
# anything above it is a manual count. Without it the first scan of a new
# product lands on-hand at -1 and the card reads "needs a count" on day one.
#
# It does NOT apply to stock_in - the scan itself establishes the stock there,
# and seeding would double it.
# A floor. The seed actually written is max(SEED_UNITS, the scanned code's unit
# count), so a first use_up lands on-hand at exactly 0 whether the code is a
# single bottle or an 18-case - never at a negative number that reads as drift.
SEED_UNITS = 1
# Written as the event `source` so a seeded checkpoint stays distinguishable
# from a counted one forever. Nothing in derive.py reads `source`, so this
# changes no arithmetic - it is forensics.
SOURCE_SEED = "seed"

# MIRRORS quick_shopping_list/const.py:33 - keep in sync by hand. A cross-component
# import would couple two custom components at load time, which HA handles badly;
# free text would let an item land on no list at all and be invisible while
# appearing to have worked (ADR 0018).
STORE_OPTIONS = ("All", "DIY", "Lowes", "Costco", "Walmart", "HEB")

SHOPPING_LIST_DOMAIN = "quick_shopping_list"

# MIRRORS quick_shopping_list/const.py DEPARTMENTS - keep in sync by hand, for
# the same reason as STORE_OPTIONS above: a cross-component import couples two
# custom components at load time, which HA handles badly.
#
# Hand-mirroring is how STORE_OPTIONS drifted - four live list items still carry
# `Katy`, `HEB` and `MC`, stores dropped from the vocabulary and orphaned. So
# unlike STORE_OPTIONS this copy has a GUARD: the verification suite reads the
# sibling component's const.py and fails if the two lists disagree.
#
# The pantry validates against its own copy rather than letting the list refuse
# on push, because a push that raises returns False and leaves push_armed set -
# which would retry a doomed push forever instead of surfacing the problem.
DEPARTMENT_SLUGS = (
    "produce", "bakery", "bread_spreads", "deli", "meat_seafood", "dairy_eggs",
    "breakfast_cereal", "coffee_tea", "canned_dry", "condiments_sauces",
    "baking_spices", "snacks", "beverages", "alcohol", "frozen",
    "household_paper", "health_beauty", "pet",
    "tools_hardware", "lumber_building", "paint_sundries", "electrical",
    "plumbing", "garden_outdoor", "automotive", "office_stationery",
    "clothing",
    "other",
)
SOURCE_TAG = "pantry_inventory"

RECOMPUTE_HOUR = 3
RECOMPUTE_MINUTE = 0
