# -*- encoding: utf-8 -*-
import codecs
import xmltodict #sudo apt-get install python-xmltodict
import json

import datetime
from datetime import timedelta

from odoo import models, fields, api
from odoo.exceptions import ValidationError, UserError
from odoo.tools import DEFAULT_SERVER_DATETIME_FORMAT
from zeep import Client, Settings
import logging

_logger = logging.getLogger(__name__)

class DetalleCSV(models.TransientModel):
    _inherit = 'l10n_ec_account_edi.wizard.impcsv'

    def procesar_retenciones(self):
        self.ensure_one()
        _logger.info("Procesar todas las retenciones")
        
        retenciones = self.lineas.filtered(lambda x: x.tipo == 'Retención' and x.estado=='-')
        _logger.info(f"Retenciones encontradas {len(retenciones)}")
        ind = 1
        for r in retenciones:
            _logger.info(f"Retención: {ind}")
            # Descargar del SRI el documento
            res = r.action_autorizacion()
            if res:
                try:
                    r.estado = u"PROCESANDO"
                    o_xml = self.env['l10n_ec_account_edi.wimpxml']
                    o = o_xml.sudo().create({
                        'archivo': res
                    })

                    o.procesar_archivo()

                    # Hacer commit de los cambios actuales
                    self.env.cr.commit()
                except:
                    _logger.warning("Error al procesar la retención")
                    pass
                
            ind += 1
        
        return {}
