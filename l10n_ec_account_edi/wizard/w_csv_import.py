# -*- encoding: utf-8 -*-
import codecs

import datetime

from odoo import models, fields, tools
from odoo.exceptions import ValidationError, UserError
from zeep import Client, Settings
import logging

_logger = logging.getLogger(__name__)

cte_meses = {
    1: 'Enero',
    2: 'Febrero',
    3: 'Marzo',
    4: 'Abril',
    5: 'Mayo',
    6: 'Junio',
    7: 'Julio',
    8: 'Agosto',
    9: 'Septiembre',
    10: 'Octubre',
    11: 'Noviembre',
    12: 'Diciembre',
}


class DetalleCSV(models.TransientModel):
    _name = 'l10n_ec_account_edi.wizard.impcsv'
    _description = 'l10n_ec_account_edi.wizard.impcsv'

    name = fields.Char(u"Nombre", default=u"Importar TXT")
    archivo = fields.Binary(string="Archivo TXT", required=False, store=True, attachment=False,
                            help=u"Archivo con extensión 'TXT' que contiene un resumen de los documentos electrónicos")
    
    
    def get_indice(self, txt, lista):
        ind = 0
        for l in lista:
            if txt.strip().lower() in l.strip().lower():
                return ind
            ind += 1        
        return -1
    
    def action_procesar_archivo(self):
        # Formato actual 
        # COMPROBANTE	SERIE_COMPROBANTE	RUC_EMISOR	RAZON_SOCIAL_EMISOR	FECHA_EMISION	FECHA_AUTORIZACION	TIPO_EMISION	NUMERO_DOCUMENTO_MODIFICADO	IDENTIFICACION_RECEPTOR	CLAVE_ACCESO	NUMERO_AUTORIZACION	IMPORTE_TOTAL
        txt_cabecera = self.sudo().env['ir.config_parameter'].get_param('header_csv_file_sri_edis')
        if '\t' in txt_cabecera:
            txt_cabecera = txt_cabecera.split('\t')
        elif ',' in txt_cabecera:
            txt_cabecera = txt_cabecera.split(',')
        elif ';' in txt_cabecera:
            txt_cabecera = txt_cabecera.split(';')

        o_clientes = self.env['res.partner']
        m_reumen = self.env['l10n_ec_account_edi.resumen.sri.mes']
        m_reumen_line = self.env['l10n_ec_account_edi.resumen.sri.line']

        for s in self:
            if s.archivo:
                buff = codecs.decode(s.archivo, 'base64')
                buff = str(buff, "latin-1") 
                lineas = buff.strip().split("\n")
                ls = []

                # indices 
                ind_comprobante = self.get_indice('comprobante', txt_cabecera)
                ind_serie = self.get_indice('serie', txt_cabecera)
                ind_ruc = self.get_indice('ruc', txt_cabecera)
                ind_fecha = self.get_indice('fecha_emi', txt_cabecera)
                ind_razon_social = self.get_indice('razon_social', txt_cabecera)
                ind_num_autorizacion = self.get_indice('numero_autorizacion', txt_cabecera)
                ind_fecha_aut = self.get_indice('fecha_aut', txt_cabecera)
                ind_num_doc = self.get_indice('numero_documento', txt_cabecera)
                ind_importe = self.get_indice('importe', txt_cabecera)
                ind_clave = self.get_indice('clave_acceso', txt_cabecera)

                for l in lineas:
                    campos = l.split("\t")
                    #print(l, campos)

                    if len(campos) >= len(txt_cabecera): 
                        if campos[0] == txt_cabecera[0]: #Cabecera
                            continue
                        
                        if ind_razon_social >= 0:
                            emisor = campos[ind_razon_social]
                        else:
                            emisor = o_clientes.search([('vat', '=', campos[ind_ruc])], limit=1)
                            if emisor:
                                emisor = emisor.name
                            else:
                                emisor = '--no registrado--'

                        if len(emisor) > 40:
                            emisor = emisor[:40] + "..."

                        tipo = campos[ind_comprobante]
                        if "retenci" in tipo.lower():
                            tipo = "Retención"
                        elif  "notas de cr" in tipo.lower():
                            tipo = "N.Crédito"
                            
                        valor = campos[ind_importe].strip()
                        if valor.startswith('.'):
                            valor = '0' + valor
                        elif not valor:
                            valor = '0'
                        
                        fecha = datetime.datetime.strptime(campos[ind_fecha], "%d/%m/%Y")
                                                
                        linea = {
                            'ruc': campos[ind_ruc],
                            'emisor':emisor,
                            'tipo': tipo,
                            'numero': campos[ind_serie],
                            'fecha': fecha,
                            'clave': campos[ind_clave].strip(),
                            'autorizacion': campos[ind_clave].strip(),
                            'total': float(valor),
                            'estado': '-',
                        }
                        resumen_mes = f"SRI Mes: {cte_meses[fecha.month]} {fecha.year}"
                        resumen = m_reumen.search([('name', '=', resumen_mes)], limit=1)
                        if not resumen:
                            resumen = m_reumen.create({'name': resumen_mes})
                        
                        o_l = m_reumen_line.search([('autorizacion', '=', linea['autorizacion'])], limit=1)
                        if not o_l:                            
                            resumen.write({'lineas': [(0, 0, linea)]})
                
                res = {
                    'name': 'Resumen del SRI',
                    'type': 'ir.actions.act_window',
                    'res_model': 'l10n_ec_account_edi.resumen.sri.mes',
                    'view_mode': 'form',
                    'target': 'current',
                    'res_id': resumen.id,                    
                }
                s.archivo = False  # No guardar el archivo en BDD

                #print "RESPUESTA: ", ctx
                return res
