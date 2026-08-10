from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    """Select an existing approved scenario and migrate only unambiguous costs."""
    cr.execute("""
        UPDATE mb_commercial_operation operation
           SET primary_scenario_id = (
              SELECT scenario.id
                FROM mb_commercial_profitability_scenario scenario
               WHERE scenario.operation_id = operation.id
                 AND scenario.state = 'approved'
               ORDER BY scenario.sequence, scenario.id DESC
               LIMIT 1
          )
         WHERE operation.primary_scenario_id IS NULL
           AND 1 = (
              SELECT COUNT(*) FROM mb_commercial_profitability_scenario scenario
               WHERE scenario.operation_id = operation.id
                 AND scenario.state = 'approved'
           )
    """)
    env = api.Environment(cr, SUPERUSER_ID, {})
    for operation in env["mb.commercial.operation"].search([
        ("primary_scenario_id", "!=", False),
    ]):
        scenario = operation.primary_scenario_id
        legacy_lines = operation.cost_line_ids.filtered(lambda line: not line.scenario_id)
        if scenario.cost_line_ids or not legacy_lines:
            continue
        operation_total = sum(legacy_lines.mapped("planned_amount"))
        scenario_total = (
            scenario.accepted_travel_cost
            + scenario.planned_work_hours * scenario.work_hourly_cost
            + scenario.stall_rent + scenario.parking_cost
            + scenario.accommodation_cost + scenario.other_fixed_cost
        )
        if scenario_total and not operation.currency_id.is_zero(operation_total - scenario_total):
            continue
        values_list = [{
            "operation_id": operation.id, "scenario_id": scenario.id,
            "sequence": line.sequence, "name": line.name,
            "category": line.category, "calculation": line.calculation,
            "quantity": line.quantity, "rate": line.rate,
            "percentage": line.percentage, "source_kind": "migration",
            "assumption_date": line.create_date.date(),
        } for line in legacy_lines]
        env["mb.commercial.cost.line"].with_context(
            mb_planning_migration=True,
        ).create(values_list)
