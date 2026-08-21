# mb_catalogue_sync

Read-only import of master catalogue materials into a tenant's product list.

It installs on Odoo 19 Community and reads the configured catalogue service over
its bounded HTTP API.

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

The master catalogue's supplier listings and price history do not belong in an
artisan's database: they are cross-tenant reference data and volatile. What
crosses is the curated manufacturer identity and the current offers of suppliers
this workshop has explicitly mapped.

| Catalogue | Odoo |
| --- | --- |
| canonical product | `product.template`, on demand, one per import |
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

Configure the service URL and optional bearer API key under **Purchase →
Configuration → Master catalogue → Service**. Network placement and publication
are deployment concerns; the addon does not assume a hostname.

## Bulk seeding, for development

`scripts/seed_from_catalogue.py` fills a database without the
picker, for when you want a populated instance to look at rather than a
workshop's real material list.

```bash
python3 scripts/seed_from_catalogue.py --database mb_odoo --manufacturer mayco --limit 40
python3 scripts/seed_from_catalogue.py --database mb_odoo --sku SC74,PC-20
python3 scripts/seed_from_catalogue.py --database mb_odoo --purge
python3 scripts/seed_from_catalogue.py --list-sources
```

`--purge` removes previously imported products and their external ids, and keeps
any that stock moves, orders, invoices or a bill of materials refer to — those
are part of a history, not a stray import.

## Boundaries

- The addon maps catalogue families onto the material categories owned by
  `mb_ceramics_base`; it does not declare another material taxonomy.
- `_mb_apply_ceramics` is an extension hook and is a no-op in this addon.
- Search and import are available through the **Import materials** wizard.
- Import is on demand; the addon does not schedule refreshes.
- The optional API key is stored on the catalogue service record and visible
  only to system administrators.

## Tests

```sh
docker compose exec odoo odoo -d <db> -u mb_catalogue_sync \
  --test-enable --stop-after-init --http-port=8199 --no-http
```

The suite covers search-without-import, selection and held-product behavior,
external-id idempotency, category and manufacturer-code ownership, native vendor
quantity tiers, duplicate pack normalization, net-price conversion, refused
offers, source mapping, and pack conversions.
