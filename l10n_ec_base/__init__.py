from . import models
from . import wizard

# Corregir lo que el modulo l10n_ec esta mal
def corregir_invoice_label(env, l10n_ec_code_applied, es_label):
    sql = f"""
        UPDATE account_tax
        SET invoice_label = jsonb_set(invoice_label, '{{es_ES}}', '"{es_label}"')
        WHERE id=(SELECT id FROM account_tax WHERE l10n_ec_code_applied='{l10n_ec_code_applied}')"""
    env.cr.execute(sql)
    

def _l10n_ec_base_post_init(env):
    corregir_invoice_label(env, '721', 'RET IVA 10%')
    corregir_invoice_label(env, '723', 'RET IVA 20%')
    corregir_invoice_label(env, '725', 'RET IVA 30%')
    corregir_invoice_label(env, '727', 'RET IVA 50%')
            
    env["account.chart.template"]._10n_ec_post_init()    