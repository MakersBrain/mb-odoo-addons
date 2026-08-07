# mb_catalogue_sync

Read-only import of master catalogue materials into a tenant's product list.

Status: working. It installs on Odoo 19 Community, its tests pass, and it runs
against the catalogue read API in `catalogue-ceramics/catalogue-service/`.

## Importing

**Purchase → Configuration → Master catalogue → Import materials.** Search a
manufacturer code or a product name, tick what the workshop uses, import those.

Punctuation in a code does not matter: AMACO stores `PC20` and prints `PC-20` on
the jar, so both find Blue Rutile. Results are ordered by how many suppliers
carry the product, because a code eleven shops sell is more likely the one
someone means than a code one shop sells. A product the workshop already holds is
shown as held rather than offered again.

Nothing is imported by searching. That is the point of the wizard existing: the
catalogue holds tens of thousands of listings and a workshop uses a few dozen
materials, so bulk import would put a manufacturer's entire range in front of
somebody who bought four glazes.

## What crosses the boundary, and what does not

The master catalogue holds ~47,000 supplier listings across 76 shops, with price
history. None of that belongs in an artisan's database: it is cross-tenant
reference data, it is volatile, and it is the most independent asset in the
product. What crosses is the curated manufacturer identity and the offers of the
suppliers this workshop actually buys from.

| Catalogue | Odoo |
| --- | --- |
| `canonical_products` (1,748 today) | `product.template`, on demand, one per import |
| pack size, from `parent_external_id` | `product.product`, via the `Pack size` attribute |
| latest offer, mapped sources only | `product.supplierinfo` |
| price history, unmapped sources, stock at the distributor | stays in the catalogue |

Distributor stock is deliberately absent. It is the most volatile field in the
catalogue and Odoo has nowhere honest to put it — stock in Odoo means stock this
company owns.

## The shape

```
product.template          one manufacturer product   Mayco SC74 Hot Tamale
  product.product         one pack size              473 ml, 236 ml
    product.supplierinfo  one vendor's price for it  Ceradel, 22.40 EUR net
```

Pack size is a variant and not a separate template because that is what the
catalogue already says: every record carries a `parent_external_id` grouping the
sizes of one product. Splitting them into templates makes "which pack is cheapest
per litre" unanswerable in Odoo, which is most of why an artisan looks at a
supplier price at all.

## Three things that are refused rather than guessed

**VAT basis.** `product.supplierinfo.price` is a net price; Odoo adds tax on top.
A VAT-inclusive figure stored there overstates purchase cost forever, silently.
44% of catalogue offers carry no `vat_status` and only 1,026 of 132,622 raw
records carry a `vat_rate` — so both fall back to the vendor mapping, where a
person sets them and owns them, and an offer with neither is refused. Refusals
are counted and reported, never dropped quietly.

**Currency.** Prices arrive in EUR, PLN, SEK, USD and GBP. The catalogue's EUR
conversions use ECB daily reference rates and are indicative, not the rate this
artisan is billed at, so the offer keeps its own currency and Odoo is told which
one the vendor bills in.

**Vendor identity.** Only catalogue sources mapped to a `res.partner` in
`mb.catalogue.supplier` produce a `product.supplierinfo`. A glaze sold by fifteen
shops would otherwise put fifteen vendors in front of an artisan who buys from
one.

## Packs

Shops publish one jar several ways: 8 US fl oz appears as 236 and 237 ml, 16 oz
as 472, 473 and one pint. Keyed on the raw number, one Mayco glaze acquires six
pack variants where it has four, and an artisan's stock of "473 ml Hot Tamale"
splits across two of them. `mb.catalogue.units._pack_key` groups them to two
significant figures, and the label is the most frequently published figure in the
group — see the tie-break comment in `_mb_sync_pack_variants`, which exists so
the label does not change when a supplier is added.

Imperial units are US measure, which is not an assumption: they occur only on
amaco, speedball and hiclay. A British source publishing pints (568 ml) needs its
own entry in `_TO_BASE`.

## Idempotency

Import is keyed on `ir.model.data` under the reserved module `__mb_catalogue__`,
not on a name match — two Mayco glazes can share a name, and a matcher that
merged them would be undiscoverable afterwards. Re-importing updates one
template and creates no second one. `name` is written on creation only: the
artisan renames a glaze to what they call it on the shelf, and a refresh that
renamed it back would be a bug they cannot fix.

## The read contract

`mb.catalogue.client` issues GET and nothing else, against:

- `GET /v1/canonical-products?q=<query>&limit=<n>` — search
- `GET /v1/canonical-products?ids=<uuid,uuid>` — fetch for import

Each product carries `canonical_product_id`, `brand`, `manufacturer_sku`,
`canonical_name`, `family`, `firing_range` and an `offers` list of
`source_id`, `supplier_name`, `supplier_reference`, `price`, `currency`,
`vat_status`, `vat_rate`, `package_quantity`, `package_unit`,
`min_order_quantity`.

That is exactly the `catalogue.canonical_catalogue` view in
`catalogue-ceramics/catalogue-dump/catalogue-canonical-promotion.sql`, and
`catalogue-ceramics/catalogue-service/app.py` serves it from there.

Odoo reaches it at `http://catalogue-service:8686` by joining the
catalogue-ceramics compose network — see the `catalogue` network in
`odoo-poc/docker-compose.yml`. The service is not published on the host: the only
thing that needs it is that container.

## Bulk seeding, for development

`makersbrain-odoo/scripts/seed_from_catalogue.py` fills a database without the
picker, for when you want a populated instance to look at rather than a
workshop's real material list.

```bash
python3 scripts/seed_from_catalogue.py --database odoo --manufacturer mayco --limit 40
python3 scripts/seed_from_catalogue.py --database odoo --sku SC74,PC-20
python3 scripts/seed_from_catalogue.py --database odoo --purge
python3 scripts/seed_from_catalogue.py --list-sources
```

`--purge` removes previously imported products and their external ids, and keeps
any that stock moves, orders, invoices or a bill of materials refer to — those
are part of a history, not a stray import.

## Not done here

- Ceramics fields — firing range, cone, atmosphere, shrinkage, food-safe — belong
  to `mb_ceramics_material` per POC-PLAN section 4. This addon calls
  `_mb_apply_ceramics`, a no-op hook, rather than declaring a competing set.
- The artisan-facing picker. `action_search` is the backend for it.
- Refresh scheduling. Import is on demand; nothing runs on a cron yet.
- `api_key` is a stand-in until `mb_connected_account` exists (POC-PLAN 5.1).

## Tests

```sh
docker compose exec odoo odoo -d <db> -u mb_catalogue_sync \
  --test-enable --stop-after-init --http-port=8199 --no-http
```

Seven tests, from a trimmed real payload: external-id idempotency, the same jar
published twice landing on one variant, VAT-inclusive prices stored net, an
offer without a VAT basis refused, an unmapped source producing no vendor, and
the pack conversions.
