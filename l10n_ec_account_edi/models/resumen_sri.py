# -*- encoding: utf-8 -*-
import codecs

import datetime

from odoo import models, fields, tools
from odoo.exceptions import ValidationError, UserError
from zeep import Client, Settings
import logging

_logger = logging.getLogger(__name__)


class ResumenSRIMes(models.Model):
    _name = 'l10n_ec_account_edi.resumen.sri.mes'
    _description = 'l10n_ec_account_edi.resumen.sri.mes'

    name = fields.Char(u"Nombre")
    lineas = fields.One2many('l10n_ec_account_edi.resumen.sri.line', 'resumen_id', string=u"Detalle")
    

    def action_revisar_f_previas(self):
        self.ensure_one()

        _logger.info("Revisar facturas previas")
        facturas = self.lineas.filtered(lambda x: x.estado=='-' and x.tipo == 'Factura') 
        _logger.info(f"Facturas encontradas {len(facturas)}")
        facturas.check_f_previa()        
        return {}
    
    def action_procesar_seleccionados(self):
        self.ensure_one()

        _logger.info("Procesar_seleccionados")
        facturas = self.lineas.filtered(lambda x: x.sel and x.tipo == 'Factura' and x.estado!='YA EXISTE') 
        _logger.info(f"Facturas encontradas {len(facturas)}")
        
        return facturas.action_procesar(True)          
    
            
    def action_comprobar_existencia(self):
        m_move = self.env['account.move']

        for s in self:  
            for l in s.lineas:
                o = m_move.search([
                    ('state', '=', 'posted'), 
                    '|',
                    ('l10n_ec_xml_access_key', '=', l.autorizacion),
                    ('l10n_ec_electronic_authorization', '=', l.autorizacion)
                ], limit=1) 

                if o:
                    l.estado = u"YA EXISTE"
                else:
                    l.estado = u"-"
    
    def action_traer_xmls(self):
        _logger.info("Traer XMLs")
        for l in self.lineas.filtered(lambda x: not x.xml and x.estado == '-'):
            l.get_xml_sri()


class ResumenSRILine(models.Model):
    _name = 'l10n_ec_account_edi.resumen.sri.line'
    _description = 'l10n_ec_account_edi.resumen.sri.line'
    _order = 'estado, fecha, tipo, emisor'

    resumen_id = fields.Many2one('l10n_ec_account_edi.resumen.sri.mes', string=u"Resumen")
    fecha = fields.Date(string=u"F.Emisión")
    ruc = fields.Char(string=u"RUC")
    emisor = fields.Char(string=u"Emisor")
    tipo = fields.Char(string=u"Tipo")
    numero = fields.Char(string=u"Número")    
    total = fields.Float(string=u"TOTAL", digits=(4, 2))
    estado = fields.Char(string=u"Estado")
    clave = fields.Char(string=u"Clave")
    autorizacion = fields.Char(string=u"Autorizacion")
    xml = fields.Binary(string=u"XML")
    sel = fields.Boolean(string=u"Sel", default=False, readonly=False)

    
    def get_xml_sri(self):
        self.ensure_one()
        if self.xml:
            return self.xml

        company = self.env.company
        auth_client = self.env['account.edi.format']._l10n_ec_get_edi_ws_client(
            company.l10n_ec_type_environment, "authorization"
        )
        
        claveacceso = self.clave
        
        try:
            response = auth_client.service.autorizacionComprobante(
                claveAccesoComprobante=claveacceso
            )
        except Exception as e:
            msg = "Error al obtener el XML del SRI: %s" % tools.ustr(e)
            _logger.warning(msg)
            raise ValidationError(msg)
        
        autorizacion = response.autorizaciones.autorizacion[0]            
           
        if autorizacion.estado.upper() != 'AUTORIZADO':   
            msg = f"El documento no se encuentra AUTORIZADO.\nEstado actual: {autorizacion.estado}"        
            if autorizacion.mensajes and autorizacion.mensajes.mensaje:
                msg += f"\n\n{autorizacion.mensajes.mensaje[0].mensaje}:"
                msg += f"\n{autorizacion.mensajes.mensaje[0].informacionAdicional}"
            raise ValidationError(msg)

        comprobante = autorizacion.comprobante
        comprobante = comprobante.encode()
        
        self.xml = codecs.encode(comprobante, 'base64')
        return self.xml
    
    def check_f_previa(self):
        for s in self:
            res = s.get_xml_sri()
            if res:                
                res = codecs.decode(res, 'base64')
                o_xml = self.env['l10n_ec_account_edi.wimpxml']
                o = o_xml.sudo().create({})

                res = o.action_procesar_archivo(res)      
                if isinstance(res, dict):          
                    w_id = res.get('res_id', False)
                    if w_id:
                        w = self.env['l10n_ec_account_edi.wimpxml'].browse(w_id)
                        if len(w.lines_x_consolidado.filtered(lambda x: x.producto_id)) > 0:
                            s.estado = 'F.PREVIA'

    
    def action_procesar(self, automaticamente=False):
        f_ids = []

        for s in self:
            if s.estado == 'YA EXISTE':
                raise ValidationError(u"El Documento no puede procesarse porque ya existe!")

            res = s.get_xml_sri()
            if res:
                res = codecs.decode(res, 'base64')
                s.estado = u"PROCESANDO"
                o_xml = self.env['l10n_ec_account_edi.wimpxml']
                o = o_xml.sudo().create({})

                if automaticamente:
                    f_id = o.procesar_automaticamente(res)
                    if f_id:
                        f_ids.append(f_id)
                else:
                    return o.action_procesar_archivo(res)
        
        #vista = self.env.ref('account.view_in_invoice_tree')

        domain = [('id', 'in', f_ids)]
        action = self.env["ir.actions.actions"]._for_xml_id("account.action_move_in_invoice_type")
        return dict(action, domain=domain)
        
        # return {
        #     'type': 'ir.actions.act_window',
        #     'views': [[vista.id, 'tree']],
        #     'res_model': 'account.move',
        #     'res_ids': f_ids,
        # }

    