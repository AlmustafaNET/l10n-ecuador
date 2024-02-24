# -*- encoding: utf-8 -*-
import codecs
import xmltodict #sudo apt-get install python-xmltodict
import json

import datetime
from datetime import timedelta

from odoo import models, fields, api, _
from odoo.exceptions import ValidationError, UserError
from odoo.tools import DEFAULT_SERVER_DATETIME_FORMAT
from zeep import Client, Settings
import logging

_logger = logging.getLogger(__name__)

class ImportarXML(models.TransientModel):
    _inherit = 'l10n_ec_account_edi.wimpxml'    
   
    
    def procesar_retencion(self, numero_autorizacion, retencion):
        #print("RETENCION")
        self.ensure_one()
        
        
        self.revisar_llaves(retencion, ['infoTributaria', 'infoCompRetencion'])
        origen = self.info_tributaria(retencion['infoTributaria'])
        if not isinstance(origen, dict):
            origen = origen.pop()

        if not numero_autorizacion:
            if 'clave' in origen:
                numero_autorizacion = origen['clave']
            elif 'claveAcceso' in origen:
                numero_autorizacion = origen['claveAcceso']
            else:
                print("Clave de Acceso no encontrada: ", origen.keys())

        info_r = retencion['infoCompRetencion']
        self.revisar_llaves(info_r, ['fechaEmision', 'tipoIdentificacionSujetoRetenido', 'razonSocialSujetoRetenido',
                                'identificacionSujetoRetenido', 'periodoFiscal'])

        s_fecha = info_r['fechaEmision']
        tipo_id = info_r['tipoIdentificacionSujetoRetenido']
        #sujeto = info_r['razonSocialSujetoRetenido']
        mi_ruc = info_r['identificacionSujetoRetenido']
        #periodo = info_r['periodoFiscal']

        company = self.env.company
        ruc_comp = company.vat
        if tipo_id == '05':
            ruc_comp = ruc_comp[:10]

        if mi_ruc != ruc_comp:
            raise ValidationError(f"ERROR: Retención NO emitada a esta Empresa!.\nEmitida al RUC: {mi_ruc}")


        self.fecha = s_fecha
        self.numero = origen['numero']
        
        dt_fecha = datetime.datetime.strptime(s_fecha, "%d/%m/%Y")
        fecha = datetime.datetime.strftime(dt_fecha, DEFAULT_SERVER_DATETIME_FORMAT)    
        
        
        # Forma antigua
        if retencion.get('impuestos', False): 

            r_impuestos = retencion['impuestos']

            self.revisar_llaves(r_impuestos, ['impuesto'])
            r_impuestos = r_impuestos['impuesto']
            if isinstance(r_impuestos, dict):
                r_impuestos = [r_impuestos]
                
        # Forma nueva 2023
        elif retencion.get('docsSustento', False): 
            documentos = retencion.get('docsSustento', {}).get('docSustento', [])
            if isinstance(documentos, dict):
                documentos = [documentos]
                
            r_impuestos = []
            for doc in documentos:
                retenciones = doc.get('retenciones', {}).get('retencion', [])
                if isinstance(retenciones, dict):
                    retenciones = [retenciones]
                for imp in retenciones:
                    r_impuestos.append({
                        'codigo': imp.get('codigo'),
                        'codigoRetencion': imp.get('codigoRetencion'), 
                        'baseImponible': imp.get('baseImponible'),
                        'porcentajeRetener': imp.get('porcentajeRetener'),
                        'valorRetenido': imp.get('valorRetenido'),
                        'numDocSustento': doc.get('numDocSustento'),
                        'codDocSustento': doc.get('codDocSustento'),
                    })
            
        else:
            self.print_dict(retencion)
            raise ValidationError("No se encontro la entrada 'impuestos' ni 'docsSustento'")   
             
        withhold_lines = []               
        subtotal_renta = 0
        subtotal_iva = 0
        for imp in r_impuestos:
            self.revisar_llaves(imp, ['codigo', 'codigoRetencion', 'baseImponible', 'porcentajeRetener', 'valorRetenido'])

            amount = float(imp['valorRetenido'])   

            # Renta
            if imp['codigo'] == '1':
                subtotal_renta += amount
                porcentaje = float(imp['porcentajeRetener']) * -1
                tax_group_name = 'withhold_income_sale'
            # IVA
            elif imp['codigo'] == '2':
                subtotal_iva += amount
                porcentaje = float(imp['porcentajeRetener']) * -1
                tax_group_name = 'withhold_vat_sale'
            # elif imp['codigo'] == '6':
            #     ri_codigo = 'ISD'
            else:
                raise ValidationError(u"ERROR: Código de Impuesto NO Soportado. '%s'" % imp['codigo'])
            
            tax_group_id = self.env['account.tax.group'].search([('l10n_ec_type', '=', tax_group_name)]).id
            r_tax = self.env['account.tax'].search([('tax_group_id', '=', tax_group_id), ('amount', '=', porcentaje)], limit=1)            

            if not r_tax:
                raise UserError("No se pudo encontrar el impuesto (%s) al %s %%" % (tax_group_name, porcentaje))
                                
            if 'numDocSustento' in imp.keys():
                num_factura = imp['numDocSustento']
            else:
                num_factura = '000'

            codDocSustento = imp.get('codDocSustento', '01')
            if codDocSustento != '01':            
                _logger.warning("Documento de Sustento no es Factura: %s" % codDocSustento)
                return False
            
            # new line
            taxes_vals = {
                "tax_group_withhold_id": tax_group_id,
                "tax_withhold_id": r_tax.id,
                "base_amount": float(imp['baseImponible']),
                "withhold_amount": amount,
            }
            withhold_lines.append(taxes_vals)
            

        if num_factura.startswith('000') and num_factura.startswith('999'):
            raise UserError("Esta retención NO tiene Documento de sustento.\n" + num_factura)    
                
        
        #Revisar si la factura relacionada existe
        num_factura = "%s-%s-%s" % (num_factura[0:3], num_factura[3:6], num_factura[6:])

        fact = self.env['account.move'].search([('name', 'like', num_factura), ('move_type', '=', 'out_invoice'), ('state', '=', 'posted')], limit=1)
        if not fact:
            raise ValidationError(f"No se encontró el Documento de Sustento : {num_factura}")

        
        # Crear retencion
        journal = self.env["account.journal"].search(
            [
                ("type", "=", "general"),
                ("l10n_ec_withholding_type", "=", 'sale'),
            ],
            limit=1,
        )
        
        withhold_vals = {
            "tipo": 'sale',
            "journal_id": journal.id,
            "number": origen['numero'],
            "date": fecha,
            "invoice_id": fact.id,
            "authorization": numero_autorizacion,
            "invoice_number": num_factura,
            "total_withhold": subtotal_renta + subtotal_iva,
            "lines": withhold_lines,
        }

        new_retencion = self.env["account.move"].create_withhold(withhold_vals)
              
        form_id = self.env.ref(
            "l10n_ec_withhold.view_account_move_withhold_form"
        ).id
        res = {
            "name": _("Withhold"),
            "type": "ir.actions.act_window",
            "view_mode": "form",
            "views": [(form_id, "form")],
            "res_model": "account.move",
            "res_id": new_retencion.id,
            "target": "current",
        }
        return res     
    
        
    def procesar_segun_tipo(self, numero_autorizacion, comprobante):
        if 'comprobanteRetencion' in comprobante:
            return self.procesar_retencion(numero_autorizacion, comprobante['comprobanteRetencion'])
        else:
            return super().procesar_segun_tipo(numero_autorizacion, comprobante)
        
    

        