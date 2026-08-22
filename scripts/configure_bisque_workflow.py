"""Configure the database-specific bisque stock boundary after addon upgrade.

Run with:

    docker compose exec -T odoo odoo shell -d mb_odoo --no-http \
        < scripts/configure_bisque_workflow.py

The validation phase completes before any write. Product names are never used
as identifiers; missing or duplicate internal references abort the script.
"""

STAGE_BY_DEFAULT_CODE = {
    "BLANK-BOX-S": "green",
    "BLANK-BOX-M": "green",
    "BISQUE-BOX-S": "bisque",
    "BISQUE-BOX-M": "bisque",
}

BISQUE_PAIRS = {
    "BISQUE-BOX-S": "BLANK-BOX-S",
    "BISQUE-BOX-M": "BLANK-BOX-M",
}

WAREHOUSE_CODE = "AT"


def one_product(default_code):
    products = (
        env["product.product"]
        .with_context(active_test=False)
        .search(
            [
                ("default_code", "=", default_code),
            ]
        )
    )
    if len(products) != 1:
        raise RuntimeError(
            "Expected exactly one product with internal reference %s; found %s."
            % (default_code, len(products))
        )
    return products


def validate_bisque_bom(bisque, green):
    boms = env["mrp.bom"].search(
        [
            "|",
            ("product_id", "=", bisque.id),
            "&",
            ("product_id", "=", False),
            ("product_tmpl_id", "=", bisque.product_tmpl_id.id),
        ]
    )
    compatible = boms.filtered(lambda bom: green in bom.bom_line_ids.product_id)
    if len(compatible) != 1:
        raise RuntimeError(
            "%s needs exactly one BoM consuming %s; found %s."
            % (bisque.default_code, green.default_code, len(compatible))
        )
    return compatible


products = {code: one_product(code) for code in STAGE_BY_DEFAULT_CODE}
invalid_products = [
    code
    for code, product in products.items()
    if (
        not product.is_storable
        or product.tracking == "none"
        or (product.company_id and product.company_id != env.company)
    )
]
if invalid_products:
    raise RuntimeError(
        "Workflow products must be storable, tracked and belong to the active "
        "company: %s" % ", ".join(invalid_products)
    )
validated_boms = {
    bisque_code: validate_bisque_bom(products[bisque_code], products[green_code])
    for bisque_code, green_code in BISQUE_PAIRS.items()
}

warehouse = env["stock.warehouse"].search(
    [
        ("company_id", "=", env.company.id),
        ("code", "=", WAREHOUSE_CODE),
    ],
    limit=2,
)
if len(warehouse) != 1:
    raise RuntimeError(
        "Expected exactly one %s warehouse for the active company; found %s."
        % (WAREHOUSE_CODE, len(warehouse))
    )

bisque_location = env["stock.location"].search(
    [
        ("location_id", "=", warehouse.lot_stock_id.id),
        ("name", "=", "Bisque"),
        ("company_id", "in", (False, env.company.id)),
    ],
    limit=2,
)
if len(bisque_location) > 1:
    raise RuntimeError("More than one direct Bisque stock location exists.")

# No writes occur above this line.
for code, stage in STAGE_BY_DEFAULT_CODE.items():
    products[code].product_tmpl_id.write({"mb_ceramics_stage": stage})

if not bisque_location:
    bisque_location = env["stock.location"].create(
        {
            "name": "Bisque",
            "location_id": warehouse.lot_stock_id.id,
            "usage": "internal",
            "company_id": env.company.id,
        }
    )

env.cr.commit()

print("BISQUE_LOCATION", bisque_location.complete_name)
print(
    "CLASSIFIED",
    {code: product.product_tmpl_id.mb_ceramics_stage for code, product in products.items()},
)
print("VALIDATED_BOMS", {code: bom.display_name for code, bom in validated_boms.items()})
