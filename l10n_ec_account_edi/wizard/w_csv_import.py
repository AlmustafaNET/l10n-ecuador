# -*- encoding: utf-8 -*-
import codecs

import datetime

from odoo import models, fields, tools
from odoo.exceptions import ValidationError, UserError
from zeep import Client, Settings
import logging

_logger = logging.getLogger(__name__)


class DetalleCSV(models.TransientModel):
    _name = 'l10n_ec_account_edi.wizard.impcsv'
    _description = 'l10n_ec_account_edi.wizard.impcsv'

    name = fields.Char(u"Nombre", default=u"Importar TXT")
    archivo = fields.Binary(string="Archivo TXT", required=False, store=True, attachment=False,
                            help=u"Archivo con extensión 'TXT' que contiene un resumen de los documentos electrónicos")
    lineas = fields.One2many('l10n_ec_account_edi.wizard.impcsv.line', 'wizard_id', string=u"Detalle")


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
        
        return facturas.procesar(True)      
    
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
                                                
                        linea = {
                            'wizard_id' : s.id,
                            'ruc': campos[ind_ruc],
                            'emisor':emisor,
                            'tipo': tipo,
                            'numero': campos[ind_serie],
                            'fecha': datetime.datetime.strptime(campos[ind_fecha], "%d/%m/%Y"),
                            'clave': campos[ind_clave].strip(),
                            'autorizacion': campos[ind_clave].strip(),
                            'total': float(valor),
                            'estado': '-',
                        }                        

                        ls += [[0, False, linea]]

                s.lineas = ls

                ctx = {
                    'modo': 'f',
                }
                res = {
                    'type': 'ir.actions.act_window',
                    'res_model': 'l10n_ec_account_edi.wizard.impcsv',                    
                    'view_mode': 'form',
                    'target': 'current',
                    'res_id': s.id,
                    'context': ctx,
                }
                s.archivo = False  # No guardar el archivo en BDD

                #print "RESPUESTA: ", ctx
                return res
            
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


class DetalleCSVLine(models.TransientModel):
    _name = 'l10n_ec_account_edi.wizard.impcsv.line'
    _description = 'l10n_ec_account_edi.wizard.impcsv.line'
    _order = 'estado'

    wizard_id = fields.Many2one(comodel_name='l10n_ec_account_edi.wizard.impcsv', string=u'Principal', store=True)
    ruc = fields.Char(string=u"RUC")
    emisor = fields.Char(string=u"Emisor")
    tipo = fields.Char(string=u"Tipo")
    numero = fields.Char(string=u"Número")
    fecha = fields.Date(string=u"F.Emisión")
    total = fields.Float(string=u"TOTAL", digits=(4, 2))
    estado = fields.Char(string=u"Estado")
    clave = fields.Char(string=u"Clave")
    autorizacion = fields.Char(string=u"Autorizacion")
    sel = fields.Boolean(string=u"Sel", default=False, readonly=False)

    @staticmethod
    def buscar_nodo(nodo, nombre, con_text=False):
        if nodo.tag == nombre:
            if con_text:
                if nodo.text and len(nodo.text) > 0: return nodo
            else:
                return nodo

        for n in nodo:
            r = DetalleCSVLine.buscar_nodo(n, nombre, con_text)
            # BUG, NO usar simplemente 'if r:'
            if str(type(r)) == "<type 'Element'>": return r
        return False

    
    def get_xml_sri(self):
        self.ensure_one()

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
        
        return codecs.encode(comprobante, 'base64')
    
    def check_f_previa(self):
        for s in self:
            res = s.get_xml_sri()
            if res:                
                o_xml = self.env['l10n_ec_account_edi.wimpxml']
                o = o_xml.sudo().create({
                    'archivo': res
                })

                res = o.action_procesar_archivo()      
                if isinstance(res, dict):          
                    w_id = res.get('res_id', False)
                    if w_id:
                        w = self.env['l10n_ec_account_edi.wimpxml'].browse(w_id)
                        if len(w.lines_x_consolidado) > 0:
                            s.estado = 'F.PREVIA'

    
    def action_procesar(self, automaticamente=False):
        f_ids = []

        for s in self:
            if s.estado == 'YA EXISTE':
                raise ValidationError(u"El Documento no puede procesarse porque ya existe!")

            res = s.get_xml_sri()
            if res:
                s.estado = u"PROCESANDO"
                o_xml = self.env['l10n_ec_account_edi.wimpxml']
                o = o_xml.sudo().create({
                    'archivo': res
                })

                if automaticamente:
                    f_id = o.procesar_automaticamente()
                    if f_id:
                        f_ids.append(f_id)
                else:
                    return o.action_procesar_archivo()
        
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

