# -*- encoding: utf-8 -*-
import codecs
import xmltodict #sudo apt-get install python-xmltodict
import json

import datetime
from datetime import timedelta

from odoo import models, fields, api
from odoo.exceptions import ValidationError, UserError
from odoo.tools import DEFAULT_SERVER_DATETIME_FORMAT
from odoo.addons.l10n_ec_withhold.models.data import TAX_SUPPORT

from zeep import Client, Settings
import logging

_logger = logging.getLogger(__name__)


class ImportarXML(models.TransientModel):
    _name = 'l10n_ec_account_edi.wimpxml'
    _description = 'l10n_ec_account_edi.wimpxml'
    
    archivo = fields.Binary(string="Archivo XML", required=False, store=True, attachment=False,
                            help=u"Archivo con extensión 'XML' que contiene un documento electrónico.")
    
    proveedor = fields.Char(string=u"Proveedor")
    numero = fields.Char(string=u"Número de Documento")
    fecha = fields.Char(string=u"Fecha")
    tipo = fields.Selection([('consolidado', 'Consolidado'), ('x_producto', 'Por Producto')], string=u"Tipo", default='consolidado', required=True)
    lines_x_producto = fields.One2many('l10n_ec_account_edi.wimpxml.by_product', 'wizard_id', string=u"Lineas Por Producto")
    lines_x_consolidado = fields.One2many('l10n_ec_account_edi.wimpxml.by_consolidado', 'wizard_id', string=u"Destino")
    lines_info_adicional = fields.One2many('l10n_ec_account_edi.wimpxml.info_adicional', 'wizard_id', string=u"Información Adicional")
    impuestos = fields.One2many('l10n_ec_account_edi.wimpxml.impuestos', 'wizard_id', string=u"Impuestos")
    totalSinImpuestos = fields.Float(string=u"Sub Total")
    descuento = fields.Float(string=u"Descuento")
    propina = fields.Float(string=u"Propina")
    total = fields.Float(string=u"Total")    
    ret_asumida = fields.Boolean("Asumir Retención", default=False)    
    l10n_ec_tax_support = fields.Selection(
        TAX_SUPPORT,
        string="Tax Support",
        copy=False,
        default=lambda self: self._context.get("tax_support"),
    )


    @api.model
    def _get_default_publicar_auto(self):        
        return self.env['ir.config_parameter'].sudo().get_param('l10n_ec_account_edi.publicar_automatico')

    @api.model
    def _get_default_pagar_auto(self):
        return self.env['ir.config_parameter'].sudo().get_param('l10n_ec_account_edi.pagar_automatico')

    publicar = fields.Boolean("Publicar automáticamente", default=_get_default_publicar_auto)
    pagar = fields.Boolean("Pagar automáticamente", default=_get_default_pagar_auto)      
    fpago = fields.Many2one(comodel_name='account.journal', string=u'Forma de Pago')
       
    
    suma_sub = fields.Float(string=u"Suma SubTotal", compute='_sumar')
    suma_imp = fields.Float(string=u"Suma Impuestos", compute='_sumar')
    #


    @api.depends('lines_x_producto', 'lines_x_consolidado')
    def _sumar(self):
        for s in self:
            sub = 0
            imp = 0
            if s.tipo == 'consolidado':
                for l in s.lines_x_consolidado:
                    sub += l.subtotal
                    imp += l.valor
            elif s.tipo == 'x_producto':
                for l in s.lines_x_producto:
                    if l.seleccionado:
                        sub += l.precio_sin_impuesto
                        imp += l.v_imp 
            s.suma_sub = sub
            s.suma_imp = imp
            

    @staticmethod
    def print_dict(d):
        print(json.dumps(d, indent=4))
    #

    def revisar_llaves(self, data, llaves):
        for llave in llaves:
            if llave not in data:
                self.print_dict(data)
                raise ValidationError(u"ERROR: Formato de Archivo INCORRECTO, No encontrada la entrada '%s'" % llave)

    
    def info_tributaria(self, info):
        self.ensure_one()
        self.revisar_llaves(info, ['ambiente', 'ruc', 'razonSocial', 'estab', 'ptoEmi', 'secuencial', 'dirMatriz', 'codDoc', 'claveAcceso'])

        company = self.env.company
        comp_ambiente = company.l10n_ec_type_environment
        company_ambiente = '1' if comp_ambiente in ('none', 'test') else '2'

        ambientes = {
            '1': 'Pruebas',
            '2': 'Producción'
        }
        
        # comparo ambientes y me salto si estoy en localhost (pruebas)
        if 'localhost' not in company.get_base_url() and info['ambiente'] != company_ambiente:
            raise ValidationError(u"ERROR: Comprobante esta en ambiente de %s, mientras que la companía esta en ambiente de %s" % (ambientes[info['ambiente']], ambientes[company_ambiente]))

        ruc = info['ruc']
        cliente = info['razonSocial']
        estab = info['estab']
        pto = info['ptoEmi']
        clave = info['claveAcceso']
        numero = info['secuencial']
        direccion = info['dirMatriz']

        # codDoc
        # FACTURA 01
        # NOTA DE CRÉDITO 04
        # NOTA DE DÉBITO 05
        # GUÍA DE REMISIÓN 06
        # COMPROBANTE DE RETENCIÓN 07
        if info['codDoc'] not in ["01", "07"]:
            raise ValidationError(u"ERROR: Código del Documento debe ser '01: Factura' o '07:  Retención' y es '%s'" % info['codDoc'])

        #print "ORIGEN: ", ruc, cliente, estab, pto, numero, direccion
        self.proveedor = f"{ruc} {cliente}"
        
        o_cliente = self.env['res.partner']
        r_cliente = o_cliente.search([('vat', '=',ruc)])
        if not r_cliente:
            #Crear Proveedor
            _logger.info("CREAR PROVEEDOR: %s / %s" %(ruc, cliente))
            # Cuentas por defecto.
            # user = o_cliente.browse(1) # Partner de la empresa
            # cuenta_cxc = user.property_account_receivable_id
            # cuenta_cxp = user.property_account_payable_id
            if len(ruc) == 13:
                tipo = 'company'
            else:
                tipo = 'person'

            nuevo = {
                'name': cliente,
                'vat': ruc,
                'street': direccion,   
                'company_type': tipo,            
                # 'property_account_receivable_id': cuenta_cxc.id,
                # 'property_account_payable_id': cuenta_cxp.id,
            }
            r_cliente = o_cliente.create(nuevo)
        
        res = {
            'proveedor': r_cliente.id,
            'clave': clave,
            'numero': f"{estab.zfill(3)}-{pto.zfill(3)}-{numero.zfill(9)}"
        }        
        return res 

    def obtener_anteriores(self, proveedor_id):
        self.ensure_one()

        moves = self.env['account.move'].search([('partner_id', '=', proveedor_id), ('move_type','=', 'in_invoice'), ('state', '=', 'posted')], limit=10, order='invoice_date desc')
        formas_pagos = {}
        fp_id = 0
        max_uso_journal = 0
        impuestos = {}
        tax_suport = False

        # Maximo las ultimas 10 facturas
        for move in moves:
            tax_suport = move.l10n_ec_tax_support
            # Pagos
            reconciled_lines, _ = move._get_reconciled_invoices_partials()
            for _, _, counterpart_line in reconciled_lines:
                jounral_id = counterpart_line.journal_id.id
                if jounral_id not in formas_pagos:
                    formas_pagos[jounral_id] = 0
                
                formas_pagos[jounral_id] += 1

                if formas_pagos[jounral_id] > max_uso_journal:
                    max_uso_journal = formas_pagos[jounral_id]
                    fp_id = jounral_id
            

            # Productos
            for line in move.invoice_line_ids:
                for tax in line.tax_ids:
                    if tax not in impuestos:
                        impuestos[tax] = (line.product_id.id, line.tax_ids.filtered(lambda r: r.id != tax.id).mapped('id'))

        
        return fp_id, impuestos, tax_suport
    
    def procesar_factura(self, numero_autorizacion, factura):
        self.ensure_one()
        #print("FACTURA")

        self.revisar_llaves(factura, ['infoTributaria', 'infoFactura', 'detalles'])
        origen = self.info_tributaria(factura['infoTributaria'])
        if not isinstance(origen, dict):
            origen = origen.pop()

        if not numero_autorizacion:
            if 'clave' in origen:
                numero_autorizacion = origen['clave']
            elif 'claveAcceso' in origen:
                numero_autorizacion = origen['claveAcceso']
            else:
                print("Clave de Acceso no encontrada: ", origen.keys())

        destino = factura['infoFactura']
        self.revisar_llaves(destino, ['fechaEmision', 'tipoIdentificacionComprador', 'identificacionComprador',
                                 'totalSinImpuestos', 'totalDescuento', 'importeTotal', 'totalConImpuestos'])

        s_fecha = destino['fechaEmision']
        fecha = datetime.datetime.strptime(s_fecha, "%d/%m/%Y")

        self.fecha = fecha
        self.numero = origen['numero']

        # print(destino['fechaEmision'] ,fecha)
                
        # tipoIdentificacionComprador
        # RUC         04
        # CEDULA      05
        # PASAPORTE   06
        # VENTA A CONSUMIDOR FINAL 07  (9999999999999)
        # IDENTIFICACION DELEXTERIOR 08
        # PLACA       09    
        tipo_id = destino['tipoIdentificacionComprador']
        company = self.env.company
        
        mi_ruc = destino['identificacionComprador']
        ruc_comp = company.vat
        if tipo_id == '05':
            ruc_comp = ruc_comp[:10]
            
        if mi_ruc != ruc_comp:
            raise UserError(u"ERROR: No emitida a esta Empresa. \nRUC '%s'" % mi_ruc)

        
        self.totalSinImpuestos = float(destino['totalSinImpuestos'])
        self.descuento = float(destino['totalDescuento'])
        self.propina = float(destino['propina']) if 'propina' in destino.keys() else 0.0
        self.total = float(destino['importeTotal'])
        
        #print "DESTINO: ", self.fecha, mi_ruc

        taxes_previos = self.env['account.tax']
        m_taxes = self.env['account.tax']

        fp_id, impuestos_previos, tax_suport = self.obtener_anteriores(origen['proveedor'])
        
        self.l10n_ec_tax_support = tax_suport

        if fp_id > 0:
            self.fpago = fp_id # Por defecto la forma de pago antes usada con este proveedor

        for tax in impuestos_previos.keys():
            taxes_previos += tax

                  
        impuestos = destino['totalConImpuestos']
        lineas = []
        lines_x_consolidado = []
        for ki in impuestos.keys():
            imps = impuestos[ki]
            if isinstance(imps, dict):
                imps = [imps]
            
            for imp in imps:
                self.revisar_llaves(imp, ['codigo', 'codigoPorcentaje', 'baseImponible', 'valor'])
                # #Codigo de impuesto
                # IVA 2
                # ICE 3
                # IRBPNR 5            
                if imp['codigo'] == '2': 
                    cod = 'IVA'
                    if imp['codigoPorcentaje'] == '0':
                        p_imp = 'IVA 0%'
                    elif imp['codigoPorcentaje'] == '2':
                        p_imp = 'IVA 12%'
                    elif imp['codigoPorcentaje'] == '3':
                        p_imp = 'IVA 14%'
                    elif imp['codigoPorcentaje'] == '6':
                        p_imp = 'No Objeto de IVA'
                    elif imp['codigoPorcentaje'] == '7':
                        p_imp = 'Exento'
                    elif imp['codigoPorcentaje'] == '8':
                        p_imp = 'IVA diferenciado'
                    else:
                        raise ValidationError(
                            u"ERROR: Código de Porcentaje de Impuesto NO Soportado. '%s'" % imp['codigoPorcentaje'])

                elif imp['codigo'] == '3': 
                    cod = 'ICE'
                    p_imp = imp['codigoPorcentaje']
                    self.totalSinImpuestos += float(imp['valor'])

                elif imp['codigo'] == '5': 
                    cod = 'IRBPNR'
                    p_imp = imp['codigoPorcentaje']
                else: 
                    raise ValidationError(u"ERROR: Código de Impuesto NO Soportado. '%s'" % imp['codigo'])
                                
                lineas += [[0,0, {
                    'codigo' : cod,
                    'codigoPorcentaje' : p_imp,
                    'baseImponible' : float(imp['baseImponible']),
                    'valor': float(imp['valor']),
                }]]
                
                # Buscar Impuesto Local Afin
                # Usar impuestos y producto anteriormente usados
                t_previo = taxes_previos.filtered(lambda r: r.l10n_ec_xml_fe_code == imp['codigoPorcentaje'] and r.type_tax_use == 'purchase')
                if t_previo:
                    t_previo = t_previo[0]
                    taxs = [t_previo.id]
                    taxs += impuestos_previos[t_previo][1]
                    lines_x_consolidado += [[0,0, {
                        'producto_id' : impuestos_previos[t_previo][0],
                        'tax_ids' : taxs,                        
                        'subtotal': float(imp['baseImponible']),
                        'valor': float(imp['valor']),
                    }]]   
                else:
                    # Crear lineas sin producto
                    
                    taxs = m_taxes.search([('l10n_ec_xml_fe_code', '=', imp['codigoPorcentaje']), ('type_tax_use', '=', 'purchase')], limit=1).ids
                    lines_x_consolidado += [[0,0, {
                        'tax_ids' : taxs,
                        'subtotal': float(imp['baseImponible']),
                        'valor': float(imp['valor']),
                    }]]             
                 

        self.impuestos = lineas
        self.lines_x_consolidado = lines_x_consolidado        
        
        # DETALLE
        self.revisar_llaves(factura['detalles'], ['detalle'])
        detalles = factura['detalles']['detalle']
        lines_x_producto = []

        o_productos = self.env['product.product']
        
        if isinstance(detalles, dict):
            detalles = [detalles]
        
        for d in detalles:
            self.revisar_llaves(d, ['descripcion', 'descuento', 'cantidad', 'precioUnitario', 'precioTotalSinImpuesto',
                               'impuestos'])

            if 'codigoPrincipal' in d.keys():
                codigo = d['codigoPrincipal']
            else:
                codigo = u"N/A"
                
            descripcion = d['descripcion']
            cantidad = d['cantidad']
            descuento = d['descuento']
            precio_unitario = d['precioUnitario']
            precio_sin_impuesto = d['precioTotalSinImpuesto']

            p_descuento = None
            if 'detallesAdicionales' in d.keys():
                adicional = d['detallesAdicionales']
                for c in adicional.keys():
                    if not isinstance(adicional[c], list):
                        lista = [adicional[c]]
                    else:
                        lista = adicional[c]
                    for l in lista:
                        if l['@nombre'] == 'porc_descuento':
                            p_descuento = l['@valor']
                            #print "Desc Establecido: ", p_descuento

            if p_descuento is None:
                # Descuento en porcentaje
                #print p_descuento, descuento, precio_unitario, cantidad
                dividendo = float(precio_unitario) * float(cantidad)
                if dividendo > 0:
                    p_descuento = (float(descuento) / dividendo) * 100.0
                else:
                    p_descuento = 0


            d_impuestos = d['impuestos']
            v_imp = 0
            for ki in d_impuestos.keys():
                impuesto = d_impuestos[ki]
                if not isinstance(impuesto, list):
                    impuesto = [impuesto]

                for imp in impuesto:
                    if imp['codigo'] == '2':
                        v_imp += float(imp['valor'])
                    else:
                        # Aumentar el impuesto ICE al precio unitario
                        precio_sin_impuesto = float(precio_sin_impuesto) + float(imp['valor'])
                        precio_unitario = precio_sin_impuesto / float(cantidad)                    

            #print u"DETALLE: ", codigo, descripcion, cantidad, precio_unitario, precio_sin_impuesto, v_imp, origen['gasto']

            #Tratar de enlazar producto
            producto_id = False
            cod_a_buscar = codigo
            r_ps = o_productos.search([('default_code', '=', cod_a_buscar.strip())], limit=1)
            #print cod_a_buscar, r_ps
            if r_ps and len(r_ps) == 1:
                producto_id = r_ps.id


            lines_x_producto += [[0,0,{                
                'codigo': codigo,
                'descripcion': descripcion,
                'cantidad': cantidad,
                'descuento': str(p_descuento),
                'producto_id': producto_id,
                'precio_unitario': precio_unitario,
                'precio_sin_impuesto': precio_sin_impuesto,
                'v_imp': v_imp,
            }]]

        self.lines_x_producto = lines_x_producto

        #INFORMACION ADICIONAL
        lines_info_adicional = []
        if 'infoAdicional' in factura.keys():            
            adicional = factura['infoAdicional']
            
            if 'campoAdicional' in adicional.keys():
                adicional = adicional['campoAdicional']
                if isinstance(adicional, dict):
                    adicional = [adicional]
                    
                #self.print_dict(adicional)
                for c in adicional:
                    if '@nombre' in c and '#text' in c:
                        lines_info_adicional += [[0,0,{
                            'nombre': c['@nombre'],
                            'valor': c['#text'],
                        }]]
                        # print "InfoAdicional: ", c['@nombre'], c['#text']
                self.lines_info_adicional = lines_info_adicional
                        

        #Crear Factura

        comprobante_id = self.env.ref('l10n_ec.ec_dt_01')  # Factura de Compra
        
        nueva_factura = {
            'partner_id': origen['proveedor'],
            'l10n_latam_document_type_id': comprobante_id.id,
            'date': fecha.replace(hour=12),
            'invoice_date': fecha.date(),
            'move_type': 'in_invoice',
            'l10n_latam_document_number': origen['numero'],
            'l10n_ec_electronic_authorization': numero_autorizacion,            
        }
        
        ctx = {
            'factura': nueva_factura,
            'modo': 'f',
        }       
        
        return {
                    'type': 'ir.actions.act_window',
                    'res_model': 'l10n_ec_account_edi.wimpxml',
                    'view_mode': 'form',                    
                    'target': 'new',
                    'res_id': self.id,
                    'context': ctx,
                }
    
    def action_crear_factura(self):
        nueva_factura = self._context['factura']
       
        lineas = []
        m_account_tax = self.env['account.tax']
        
        impuestos = {}
        #Inventario
        if self.tipo == 'x_producto':
            for l in self.lines_x_producto:
                if not l.producto_id:
                    raise ValidationError(u"Todas las líneas deben tener asignado un producto!")
                        
            for l in self.lines_x_producto:    
                tax_ids = []
                for t in l.tax_ids:
                    tax_ids.append(t.id)         

                lineas.append((0,0,{
                    'name': l.producto_id.name,
                    'product_id': l.producto_id.id,   
                    'product_uom_id': l.producto_id.uom_id,                 
                    'tax_ids': [(6, 0, tax_ids)], 
                    'price_unit': l.precio_unitario,
                    'quantity': l.cantidad,
                    'display_type': 'product',
                    'discount': l.descuento,                        
                }))          
        #Factura Consolidado
        elif self.tipo == 'consolidado':   
              
            if any(not x.producto_id for x in self.lines_x_consolidado):
                raise ValidationError(u"Todas las líneas deben tener asignado un producto!")
                        
            for l in self.lines_x_consolidado:   
                taxs = m_account_tax.browse(l.tax_ids.ids) 
                                            
                impuestos[taxs.tax_group_id.id] = [l.subtotal, l.valor]

                lineas.append((0,0,{
                    'name': l.producto_id.name,
                    'product_id': l.producto_id.id,    
                    'product_uom_id': l.producto_id.uom_id.id,                 
                    'tax_ids': [(6, 0, taxs.ids)], 
                    'price_unit': l.subtotal,
                    'quantity': 1,
                    'display_type': 'product',   
                }))    
        else:
            raise ValidationError("Debe crear un registro en la pestaña 'Consolidado' o en la pestaña 'Producto Por Producto'.")   
        
        nueva_factura['invoice_line_ids'] = lineas
        nueva_factura['l10n_ec_tax_support'] = self.l10n_ec_tax_support

        m_account_move = self.env['account.move'].sudo().with_context(default_move_type='in_invoice').with_company(self.env.company.id)
        r_fact = m_account_move.create(nueva_factura)
        if not r_fact:
            raise UserError("Error al crear la factura")

        
        publicar = True
        if abs(r_fact.amount_total - self.total) > 0.01:                
            for _,grupos in r_fact.tax_totals['groups_by_subtotal'].items():
                for g in grupos:
                    g['tax_group_amount'] = impuestos[g['tax_group_id']][1]
                
            r_fact._inverse_tax_totals()
            if abs(r_fact.amount_total - self.total) > 0.01:
                publicar = False
        
        if self.publicar and publicar:
            r_fact.sudo().action_post()
            if self.pagar:
                self.pagar_automaticamente(r_fact)       

        vista = self.env.ref('l10n_ec_account_edi.account_edi_view_move_form')
        
        return {
            'type': 'ir.actions.act_window',
            'views': [[vista.id, 'form']],
            'res_model': 'account.move',
            'res_id': r_fact.id,
        }

    def pagar_automaticamente(self, fact):        
        ctx = dict(self._context)

        ctx['active_model'] = 'account.move'
        ctx['active_ids'] = [fact.id]

        if self.ret_asumida:
            ret_asumida_cc = self.env['ir.config_parameter'].sudo().get_param('l10n_ec_account_edi.account_ret_asumida')                                                                               
            if not ret_asumida_cc:
                raise ValidationError("No esta configurada una cuenta contable de retenciones asumidas")
        

        rec = self.env['account.payment.register'].with_context(ctx).create({
            'payment_type': 'outbound',
            'currency_id': fact.currency_id.id,
            'amount': abs(fact.amount_residual),
            'payment_date': fact.invoice_date,
            'journal_id': self.fpago.id,
            'partner_id': fact.commercial_partner_id.id,
            'partner_type': 'supplier',
            'communication': fact.name,            
        })  

        if self.ret_asumida:
            rec['payment_difference_handling'] =  'reconcile'
            rec['writeoff_account_id'] =  int(ret_asumida_cc)
            rec['writeoff_label'] =  'Retención Asumida'
            rec['amount'] = abs(fact.amount_total)

        rec.action_create_payments()

        return True    

    def procesar_automaticamente(self):
        self.ensure_one()
        res = self.procesar_archivo()   
        if isinstance(res, dict):            
            w_id =  res.get('res_id', False)
            if w_id:
                w = self.env['l10n_ec_account_edi.wimpxml'].browse(w_id)
                if len(w.lines_x_consolidado) > 0:
                    r_ctx = res.get('context', {})
                    res = self.with_context({'factura': r_ctx.get('factura', False)}).crear_factura()
                    return res.get('res_id', False) 
    
        return False
           
    @staticmethod
    def buscar(base, nombre):
        if isinstance(base, dict):
            for key in base.keys():
                if key == nombre:
                    return base[nombre]
                else:
                    res = ImportarXML.buscar(base[key], nombre)
                    if res: return res
        return None
    
    def procesar_xml(self, txt):
        self.ensure_one()
        #print("Procesar XML")
        #print(txt)
        try:
            base = xmltodict.parse(txt, encoding='utf-8')
            #print("pasa")
        except Exception as ex:  
            #print("try!!!!!")
            try:
                #To fix xml that no have the same structure 
                my_str = txt.decode("utf-8")
                my_str=my_str.replace('<comprobante>', '<comprobante>' + '<![CDATA[')
                my_str=my_str.replace('</comprobante>', ']]>' + '</comprobante>')
                my_str=my_str.replace('ns2:autorizacion', 'autorizacion')
                txt = str.encode(my_str)
                base = xmltodict.parse(txt, encoding='utf-8')
            except Exception as ex:                  
                raise UserError("No se puede interpretar el archivo!\n" + str(ex))
            
        #print(base)
                   

        autorizacion = ImportarXML.buscar(base, 'autorizacion')
        if autorizacion:
            self.revisar_llaves(autorizacion, ['estado', 'numeroAutorizacion', 'comprobante'])
            if autorizacion['estado'].upper() != "AUTORIZADO":
                raise ValidationError(u"ERROR: NO AUTORIZADO. '%s'" % autorizacion['estado'].upper())

            numero_autorizacion = autorizacion['numeroAutorizacion']
            #print "N° Autoriz: ", numero_autorizacion

            comprobante = autorizacion['comprobante']
            autorizacion['comprobante'] = False
            comprobante = xmltodict.parse(comprobante)
        else:
            # Formato OFF-LINE
            comprobante = base
            numero_autorizacion = False

        return self.procesar_segun_tipo(numero_autorizacion, comprobante)
        
    def procesar_segun_tipo(self, numero_autorizacion, comprobante):
        if 'factura' in comprobante:
            return self.procesar_factura(numero_autorizacion, comprobante['factura'])        
        else:
            raise ValidationError(u"ERROR: SOLO SE ACEPTAN FACTURAS O RETENCIONES.\nNO: '%s'" % comprobante.keys())
    
    def action_procesar_archivo(self):   
        for s in self:
            if s.archivo:
                buff = codecs.decode(s.archivo, 'base64')
                ctx = self.procesar_xml(buff)
                s.archivo = False #No guardar el archivo en BDD
                
                while isinstance(ctx, list):
                    ctx = ctx.pop()
                                
                #print("RESPUESTA: ", ctx)
                return ctx


class ImportarXMLLineXProducto(models.TransientModel):
    _name = 'l10n_ec_account_edi.wimpxml.by_product'
    _description = 'Detalle de origen'

    wizard_id = fields.Many2one(comodel_name='l10n_ec_account_edi.wimpxml', string=u'Principal', store=True)
    producto_id = fields.Many2one('product.product', string=u'Producto')
    codigo = fields.Char(string=u"Código")
    descripcion  = fields.Char(string=u"Descripción")
    cantidad =fields.Float(string=u"Cantidad")
    precio_unitario = fields.Float(string=u"Prec.Unit.")
    descuento = fields.Float(string=u"Descuento")
    precio_sin_impuesto = fields.Float(string=u"SubTotal Sin-IVA")
    v_imp = fields.Float(string=u"IVA")
    seleccionado = fields.Boolean(string=u"Sumar", default=True)
    tax_ids = fields.Many2many('account.tax', string='Impuestos')

    @api.onchange('producto_id')
    def _onchange_product(self):
        for s in self:
            if s.producto_id:
                tax_ids = s.producto_id.supplier_taxes_id
                tax_ids = s._taxes_retentions(tax_ids)
                s.tax_ids = tax_ids
            else:
                s.tax_ids = []

        # Traer impuestos de retenciones de las categorias
    def _taxes_retentions(self, taxes):
        ret_taxes = taxes.filtered(lambda x: x.tax_group_id.l10n_ec_type in ('ret_renta', 'ret_iva'))

        if not ret_taxes:
            categoria = self.producto_id.categ_id
            ret_taxes = categoria.taxes_purchase_rets_id if categoria else False
            while not ret_taxes and categoria:
                categoria = categoria.parent_id
                ret_taxes = categoria.taxes_purchase_rets_id if categoria else False    

            if ret_taxes:
                taxes += ret_taxes 

        return taxes
        
    
class ImportarXMLLineConsolidado(models.TransientModel):
    _name = 'l10n_ec_account_edi.wimpxml.by_consolidado'
    _description = 'Detalle local'

    wizard_id = fields.Many2one(comodel_name='l10n_ec_account_edi.wimpxml', string=u'Principal', store=True)
    producto_id = fields.Many2one('product.product', string=u'Servicio')
    tax_ids = fields.Many2many('account.tax', string='Impuestos')
    subtotal = fields.Float(string=u"Base Imponible")
    valor = fields.Float(string=u"Impuesto")
    
    
    
class ImportarXMLLineAdicional(models.TransientModel):
    _name = 'l10n_ec_account_edi.wimpxml.info_adicional'
    _description = 'Comentarios del Documento'

    wizard_id = fields.Many2one(comodel_name='l10n_ec_account_edi.wimpxml', string=u'Principal', store=True)
    nombre = fields.Char(string=u"Nombre")        
    valor = fields.Char(string=u"Valor")

class ImportarXMLImpuestos(models.TransientModel):
    _name = 'l10n_ec_account_edi.wimpxml.impuestos'
    _description= 'l10n_ec_account_edi.wimpxml.impuestos'

    wizard_id = fields.Many2one(comodel_name='l10n_ec_account_edi.wimpxml', string=u'Principal', store=True)
    codigo = fields.Char(string=u"Impuesto")
    codigoPorcentaje = fields.Char(string=u"Detalle")
    baseImponible = fields.Float(string=u"Base Imp.")
    valor = fields.Float(string=u"Valor")