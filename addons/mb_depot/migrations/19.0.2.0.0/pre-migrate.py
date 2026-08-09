"""Drop leftover statement rows before `depot_id` changes what it points at.

`mb.depot.statement` is a TransientModel, so its rows are cache: a statement is
recomputed from the move lines every time it is opened, and vacuum deletes them
on its own schedule. But rows outliving the last vacuum still hold a `depot_id`
that referenced a stock.location, and the field now references a stock.warehouse.
Odoo repoints the foreign key on upgrade and Postgres rejects it against those
ids, which fails the whole registry load rather than the module.

Emptying them loses nothing that was not about to be regenerated anyway.
"""


def migrate(cr, version):
    cr.execute("DELETE FROM mb_depot_statement_line")
    cr.execute("DELETE FROM mb_depot_statement")
