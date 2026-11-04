# Pantry Inventory

Keep track of what's in your pantry from inside Home Assistant, and have things added to your shopping list automatically when they run low.

You scan a product's barcode with your phone's camera as it goes into the cupboard, and scan it again when you use it up. Pantry Inventory keeps the count, learns how fast you get through each thing, and puts it on your shopping list before you run out.

> **Status:** early. It runs every day in one household, but it hasn't been tried widely yet. Back up before installing, and please report anything odd on the [issues page](https://github.com/hostedinthebarn/pantry-inventory/issues).

## What you need

- Home Assistant 2026.2 or newer.
- A to-do list for shopping. Home Assistant's built-in **Shopping List** works, and so do **Local To-do** and **Bring!**.
- A phone or tablet with a camera, using the Home Assistant app or a browser. Barcode reading happens on the device itself; nothing is sent to the internet.

## Install

### With HACS

1. In HACS, open the menu (⋮) and choose **Custom repositories**.
2. Paste `https://github.com/hostedinthebarn/pantry-inventory`, choose **Integration**, and click **Add**.
3. Search HACS for **Pantry Inventory** and download it.
4. Restart Home Assistant.

### By hand

1. Download this repository.
2. Copy the `custom_components/pantry_inventory` folder into your Home Assistant `config/custom_components/` folder.
3. Restart Home Assistant.

## Set up

1. Go to **Settings → Devices & services → Add integration** and pick **Pantry Inventory**.
2. Choose the shopping list that running-low products should go on.
3. Optionally, list the stores you shop at (for example *Costco*), so each product can remember where you usually buy it.

You can change both later from the integration's **Configure** button.

A **Pantry** entry appears in the sidebar.

## Using it

- **Putting shopping away:** open Pantry, tap scan, and point the camera at each barcode. Each scan adds one.
- **Using something up:** switch the scanner to *use up* and scan it. Each scan takes one away.
- **A barcode it hasn't seen before** is still counted. It shows up as a new product waiting for a name; give it one and it joins the list.
- **Counting the cupboard:** if the numbers drift, type in the real count. That count replaces the old one rather than adding to it.
- **Running low:** each product has a level at which it goes on the shopping list. Pantry Inventory checks after every change.

## The one rule: scan it out

Scan things **out** when you use them up, not just in when you buy them.

Pantry Inventory never sees your cupboard; it only knows what you scan. Scanning in tells it what you bought. Scanning out is the only way it learns how fast you actually use each thing, and that rate is what decides when a product goes on the shopping list. Skip the scan-outs and it believes you still have plenty, so the item never makes the list and you run out.

If you do forget for a while, type in the real count and carry on. A counted number always wins.

## For automations

Everything the panel does is also available as an action (service) under `pantry_inventory`, so a dedicated barcode scanner or an automation can drive it:

| Action | What it does |
|---|---|
| `pantry_inventory.scan` | Record a scanned barcode, as stock in or use up |
| `pantry_inventory.set_count` | Record a counted quantity |
| `pantry_inventory.save_product` | Create or update a product |
| `pantry_inventory.attach_barcode` | Add another barcode to an existing product |
| `pantry_inventory.list_products` | Return every product and its current state |
| `pantry_inventory.evaluate` | Re-check every product against its running-low level |
| `pantry_inventory.discard_provisional` | Throw away a scanned-but-unnamed product |
| `pantry_inventory.delete_product` | Permanently delete an archived product |

The fields for each one are listed in **Developer tools → Actions**.

## Your data

Everything is stored in Home Assistant's own storage on your machine and included in your normal backups. Pantry Inventory makes no internet connections.

## Development

See [tests/README.md](tests/README.md) for running the two test suites.

## Support

Pantry Inventory is provided as-is, with no warranty and no promise of support. Bug reports and suggestions are welcome on the [issues page](https://github.com/hostedinthebarn/pantry-inventory/issues), and they're read, but there's no guaranteed response time.

## Licence

MIT, see [LICENSE](LICENSE). The barcode reader and UI library bundled with the panel are third-party code under their own licences; see [THIRD_PARTY_NOTICES.md](custom_components/pantry_inventory/panel/dist/vendor/THIRD_PARTY_NOTICES.md).
