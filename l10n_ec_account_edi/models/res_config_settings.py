from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    l10n_ec_type_environment = fields.Selection(
        related="company_id.l10n_ec_type_environment", readonly=False
    )
    l10n_ec_key_type_id = fields.Many2one(
        comodel_name="sri.key.type",
        related="company_id.l10n_ec_key_type_id",
        readonly=False,
    )
    l10n_ec_invoice_version = fields.Selection(
        related="company_id.l10n_ec_invoice_version", readonly=False
    )
    l10n_ec_liquidation_version = fields.Selection(
        related="company_id.l10n_ec_liquidation_version", readonly=False
    )
    l10n_ec_credit_note_version = fields.Selection(
        related="company_id.l10n_ec_credit_note_version", readonly=False
    )
    l10n_ec_debit_note_version = fields.Selection(
        related="company_id.l10n_ec_debit_note_version", readonly=False
    )
    l10n_ec_final_consumer_limit = fields.Float(
        string="Invoice Sales Limit Final Consumer",
        config_parameter="l10n_ec_final_consumer_limit",
        default=50.0,
        readonly=False,
    )    
    l10n_ec_sri_auto_post = fields.Boolean(
        string="Publicar Automáticamente Facturas SRI",
        help="Si está marcado, las facturas se publicarán automáticamente al usar la opción 'Porcesar Seleccionados' en el Resumen del SRI.",
        config_parameter="l10n_ec_sri_auto_post",
        default=True,
        readonly=False,
    )
    l10n_ec_sri_auto_payment = fields.Boolean(
        string="Pagar Automáticamente Facturas SRI",
        help="Si está marcado, las facturas se pagaran automáticamente al usar la opción 'Porcesar Seleccionados' en el Resumen del SRI.",
        config_parameter="l10n_ec_sri_auto_payment",
        default=True,
        readonly=False,
    )
