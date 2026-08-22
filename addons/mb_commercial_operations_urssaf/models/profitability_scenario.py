from odoo import api, fields, models


class MbCommercialProfitabilityScenarioLine(models.Model):
    _inherit = "mb.commercial.profitability.scenario.line"

    urssaf_rate_date = fields.Date(readonly=True)
    urssaf_cotisation_rate_id = fields.Many2one(
        "l10n.fr.micro.urssaf.rate",
        ondelete="restrict",
        readonly=True,
    )
    urssaf_cfp_rate_id = fields.Many2one(
        "l10n.fr.micro.urssaf.rate",
        ondelete="restrict",
        readonly=True,
    )
    urssaf_chamber_rate_id = fields.Many2one(
        "l10n.fr.micro.urssaf.rate",
        ondelete="restrict",
        readonly=True,
    )
    urssaf_liberatoire_rate_id = fields.Many2one(
        "l10n.fr.micro.urssaf.rate",
        ondelete="restrict",
        readonly=True,
    )
    urssaf_acre_coefficient = fields.Float(readonly=True, digits=(5, 4))

    @api.model
    def _urssaf_planning_values(self, company, date):
        rate_model = self.env["l10n.fr.micro.urssaf.rate"]
        cotisation = rate_model.rate_for("cotisation", "bic_goods", date, company)
        cfp = rate_model.rate_for("cfp", "bic_goods", date, company)
        chamber = (
            rate_model.rate_for("chamber", "bic_goods", date, company)
            if company.l10n_fr_micro_chamber_kind != "none"
            else rate_model
        )
        liberatoire = (
            rate_model.rate_for("liberatoire", "bic_goods", date, company)
            if company.l10n_fr_micro_versement_from
            and company.l10n_fr_micro_versement_from <= date
            and (
                not company.l10n_fr_micro_versement_to or date <= company.l10n_fr_micro_versement_to
            )
            else rate_model
        )
        acre = company._l10n_fr_micro_acre_coefficient_on(date)
        combined = (
            (cotisation.rate if cotisation else 0.0) * acre
            + (cfp.rate if cfp else 0.0)
            + (chamber.rate if chamber else 0.0)
            + (liberatoire.rate if liberatoire else 0.0)
        )
        return {
            "turnover_levy_rate": combined,
            "urssaf_rate_date": date,
            "urssaf_cotisation_rate_id": cotisation.id,
            "urssaf_cfp_rate_id": cfp.id,
            "urssaf_chamber_rate_id": chamber.id,
            "urssaf_liberatoire_rate_id": liberatoire.id,
            "urssaf_acre_coefficient": acre,
        }


class MbCommercialPlanningWizardLine(models.TransientModel):
    _inherit = "mb.commercial.operation.plan.wizard.line"

    apply_urssaf_goods_rates = fields.Boolean(default=True)

    def _scenario_values(self):
        values = super()._scenario_values()
        if self.apply_urssaf_goods_rates:
            date = fields.Date.to_date(self.wizard_id.operation_id.planned_start)
            values.update(
                self.env["mb.commercial.profitability.scenario.line"]._urssaf_planning_values(
                    self.wizard_id.company_id,
                    date,
                )
            )
        return values
