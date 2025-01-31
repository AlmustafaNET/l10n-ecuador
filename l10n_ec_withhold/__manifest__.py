{
    "name": "Electronic Withholding Ecuadorian Localization",
    "summary": "Electronic Withholding adapted Ecuadorian localization",
    "category": "Account",
    "countries": ["ec"],
    "author": "Odoo Community Association (OCA), Odoo-EC",
    "website": "https://github.com/OCA/l10n-ecuador",
    "license": "AGPL-3",
    "version": "17.0.1.0.0",
    "depends": ["l10n_ec_base", "l10n_ec_account_edi"],
    "data": [
        "security/ir.model.access.csv",
        "data/edi_withhold.xml",
        "wizard/wizard_create_withhold_view.xml",
        "views/resumen_sri.xml",
        "views/res_partner_view.xml",
        "views/account_journal_view.xml",
        "views/account_move_view.xml",
        "views/account_fiscal_position_view.xml",
        "views/menu_root.xml",
        "report/report_edi_withhold.xml",
        "report/report_invoice.xml",
    ],
    "installable": True,
    "auto_install": False,
    "post_init_hook": "_10n_ec_withhold_post_init",
    "assets": {
        "web.assets_backend": [
            "l10n_ec_withhold/static/src/components/**/*",
        ],
    },
}
