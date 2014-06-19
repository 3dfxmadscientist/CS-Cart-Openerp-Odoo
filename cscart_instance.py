#-*- coding:utf-8 -*-
##############################################################################
#
#    SnippetBucket, MidSized Business Application Solution
#    Copyright (C) 2013-2014 http://snippetbucket.com/. All Rights Reserved.
#    Email: snippetbucket@gmail.com, Skype: live.snippetbucket
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU Affero General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU Affero General Public License for more details.
#
#    You should have received a copy of the GNU Affero General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
##############################################################################

from osv import osv, fields
import threading
import pooler
import urllib
import time
import datetime
import xmlrpclib
import netsvc
logger = netsvc.Logger()
import urllib2
import base64
from tools.translate import _
import cscartapi as api
import httplib, ConfigParser, urlparse
from xml.dom.minidom import parse, parseString
from lxml import etree
from xml.etree.ElementTree import ElementTree

class res_company_inherit(osv.osv):
    _inherit = 'res.company'
    _columns = {
       'cscart_supplier':fields.boolean('Allow Suppliers',)
    }

class res_users_inherit(osv.osv):
    _inherit = 'res.users'
    _columns = {
       'cscart_id' : fields.char('CsCart Id',size=6,readonly=True),
       'cscart':fields.boolean('CsCart',readonly=True)
    }
class sale_order_inherit(osv.osv):
    _inherit = 'sale.order'
    _columns = {
        'cscart_order_id' : fields.char('Cscart Order ID', size=256),
        'purchase_order_id': fields.many2one('purchase.order', 'Purchase Order'),
        'cscart_instance_id': fields.many2one('cscart.instance', 'Web Shop'),
        'payment_method_id': fields.many2one('cscart.payment.method','Payment Method'),
    }
    _order = "date_order desc,id desc"

    def create(self, cr, uid, vals, context={}):
        if not context:
            context = {}
        res = super(sale_order_inherit, self).create(cr, uid, vals, context=context)
        return res

    def _prepare_order_line_move(self, cr, uid, order, line, picking_id, date_planned, context=None):
        location_id = order.shop_id.warehouse_id.lot_stock_id.id
        output_id = order.shop_id.warehouse_id.lot_output_id.id
        return {
            'name': line.name,
            'picking_id': picking_id,
            'product_id': line.product_id.id,
            'date': date_planned,
            'date_expected': date_planned,
            'product_qty': line.product_uom_qty,
            'product_uom': line.product_uom.id,
            'product_uos_qty': (line.product_uos and line.product_uos_qty) or line.product_uom_qty,
            'product_uos': (line.product_uos and line.product_uos.id)\
                    or line.product_uom.id,
            'product_packaging': line.product_packaging.id,
            'partner_id': line.address_allotment_id.id or order.partner_shipping_id.id,
            'location_id': location_id,
            'location_dest_id': output_id,
            'sale_line_id': line.id,
            'tracking_id': False,
            'state': 'draft',
            #'state': 'waiting',
            'company_id': order.company_id.id,
            'price_unit': line.product_id.standard_price or 0.0,
            'cscart_item_code': line.cscart_item_code,
        }

    def create_purchase_quotation(self, cr, uid, ids, context):
        res = {}
        if context is None:
            context = {}
        company       = self.pool.get('res.users').browse(cr, uid, uid, context=context).company_id
        partner_obj   = self.pool.get('res.partner')
        uom_obj       = self.pool.get('product.uom')
        pricelist_obj = self.pool.get('product.pricelist')
        prod_obj      = self.pool.get('product.product')
        acc_pos_obj   = self.pool.get('account.fiscal.position')
        seq_obj       = self.pool.get('ir.sequence')
        warehouse_obj = self.pool.get('stock.warehouse')
        po_line_obj   = self.pool.get('purchase.order.line')
        po_obj        = self.pool.get('purchase.order')
        po_list       = {}
        sobj = self.browse(cr, uid, ids[0], context=context)
        for line in sobj.order_line:
            for seller in line.seller_ids:
                partner = seller.name
                partner_id = partner.id
                address_id = partner_obj.address_get(cr, uid, [partner_id], ['delivery'])['delivery']
                qty = line.product_uom_qty
                company_id = line.order_id.company_id.id
                pricelist_id = partner.property_product_pricelist_purchase.id
                warehouse_id = warehouse_obj.search(cr, uid, [('company_id', '=', line.order_id.company_id.id or company.id)], context=context)
                uom_id = line.product_id.uom_po_id.id
                price = seller.sup_price
                context.update({'lang': partner.lang, 'partner_id': partner_id})
                product = prod_obj.browse(cr, uid, line.product_id.id, context=context)
                taxes_ids = line.product_id.product_tmpl_id.supplier_taxes_id
                taxes = acc_pos_obj.map_tax(cr, uid, partner.property_account_position, taxes_ids)
                line_vals = {
                                'name': line.name or product.partner_ref,
                                'product_qty': qty,
                                'product_id': line.product_id.id,
                                'product_uom': uom_id,
                                'date_planned': line.order_id.date_order,
                                'price_unit': price or 0.0, 
                                'notes': product.description_purchase,
                                'taxes_id': [(6,0,taxes)],
                                'cscart_item_code':line.cscart_item_code,
                            }
                po_exists = po_obj.search(cr, uid, [('company_id','=', company_id),
                                                    ('partner_id', '=', partner_id),
                                                    ('state', '=', 'draft'),
                                                    ('sale_order_id','=',line.order_id.id)])
                if po_exists:
                    purchase_id = po_exists[0] 
                else:
                    name = seq_obj.get(cr, uid, 'purchase.order') or _('PO: %s') % line.order_id.name
                    po_vals = {
                                    'name': name,
                                    'origin': line.order_id.name,
                                    'partner_id': partner_id,
                                    'partner_address_id' : address_id,
                                    'location_id': line.order_id.shop_id.warehouse_id.lot_stock_id.id,
                                    'warehouse_id': warehouse_id and warehouse_id[0] or False,
                                    'pricelist_id': pricelist_id,
                                    #'date_order': purchase_date.strftime(DEFAULT_SERVER_DATETIME_FORMAT),
                                    'company_id': company_id,
                                    'fiscal_position': partner.property_account_position and partner.property_account_position.id or False,
                                    'order_line': [],
                                    'sale_order_id': sobj.id,
                                }
                    if line.drop_ship:
                        po_vals.update({'dest_address_id': sobj.partner_id.id, 'location_id': sobj.partner_id.property_stock_customer.id, 'drop_ship': True})
                    purchase_id = po_obj.create(cr, uid, po_vals)
                line_vals.update({'order_id': purchase_id})
                purchase_line_id = po_line_obj.create(cr, uid, line_vals) 

class sale_order_line_inherit(osv.osv):
    _inherit = 'sale.order.line'
    _columns = {
        'cscart_item_code' : fields.char('CsCart Item Code'),
    }

class purchase_order_line_inherit(osv.osv):
    _inherit = 'purchase.order.line'
    _columns = {
        'cscart_item_code' : fields.char('CsCart Item Code'),
    }

class Stock_move_inherit(osv.osv):
    _inherit = 'stock.move'
    _columns = {
        'cscart_item_code' : fields.char('CsCart Item Code'),
    }

class purchase_order(osv.osv):
    _inherit = 'purchase.order'

    _columns = {
        'cscart_item_code' : fields.char('cscart_item_code'),
        'direct_address_note': fields.text('Direct Address Note.'),
    }

    def _prepare_order_line_move(self, cr, uid, order, order_line, picking_id, context={}):
        return {
            'name': order_line.name or '',
            'product_id': order_line.product_id.id,
            'product_qty': order_line.product_qty,
            'product_uos_qty': order_line.product_qty,
            'product_uom': order_line.product_uom.id,
            'product_uos': order_line.product_uom.id,
            'date': self.date_to_datetime(cr, uid, order.date_order, context),
            'date_expected': self.date_to_datetime(cr, uid, order_line.date_planned, context),
            'location_id': order.partner_id.property_stock_supplier.id,
            'location_dest_id': order.location_id.id,
            'picking_id': picking_id,
            'partner_id': order.dest_address_id.id or order.partner_id.id,
            'move_dest_id': order_line.move_dest_id.id,
            'state': 'draft',
            'type':'in',
            'purchase_line_id': order_line.id,
            'company_id': order.company_id.id,
            'price_unit': order_line.price_unit,
            'cscart_item_code': order_line.cscart_item_code,
        }

class cscart_instance(osv.osv):
    _name = 'cscart.instance'
    _columns = {
        'name' : fields.char('Name',size=64, required=True),
        'auth_email' : fields.char('Auth Email ',size=64,required=True),
        'auth_password' : fields.char('Auth Password',size=64,required=True),
        'url' : fields.char('URL ',size=64,required=True),
        'last_cscart_order_import_date' : fields.datetime('Last Order Import Time'),
        'rewrite': fields.boolean('Rewrite'),
        'journal_id': fields.many2one('account.journal', 'Payment Type', domain=[('type','in',['bank', 'cash'])],required=True),
        'ssl' : fields.boolean('SSL Enabled'),
        'progress_status':fields.char('Progress Status'),
        'since_date':fields.date('Since Date'),
#        'period': :fields.selection((('D','Current Day'),
#                                    ('W','Current Week'),
#                                    ('M','Current Month'),
#                                    ('Y','Current year'),
#                                    ('LD','Last Day'),
#                                    ('LW','Last Week'),
#                                    ('LM','Last Month'),
#                                    ('LY','Last Year')),'Time Period'),
    }




    def import_payment_method(self, cr, uid, ids, context={}):
        cscart = self.read(cr, uid, ids, [], context=context)
        if cscart:
            cscart = cscart[0]
            context.update({'instance_id':cscart['id']})
            context.update({'journal_id':cscart['journal_id']})
            o = api.CsCart(cscart['url'], (cscart['auth_email'],cscart['auth_password']), cscart['rewrite'],cscart['ssl'])
            params = {'items_per_page':20}
            page = 1
            params = {'page':page}
            rs_payments = o.getpayments(params)
            page = page + 1
#            print "page :->>>>",page
            for payment in rs_payments:
               payment_method = o.getpayment(payment['payment_id'])
               self.create_payment(cr, uid, ids, payment_method, context=context)
        return True

    def create_payment(self, cr, uid, ids, rs_payments, context):
        payment_obj = self.pool.get('cscart.payment.method')

        paymentvals = {
        'name': rs_payments['payment'],
        'processor': rs_payments['processor'],
        'payment_category': rs_payments['payment_category'],
#        'user_groups_all': rs_payments['usergroup_ids'],
#        'user_groups_guest': rs_payments['usergroup_ids'],
#        'user_groups_registered': rs_payments['usergroup_ids'],
        'description': rs_payments['description'],
        'a_surcharge': rs_payments['a_surcharge'],
        'p_surcharge': rs_payments['p_surcharge'],
        'payment_id': rs_payments['payment_id'],
        }
        payment_ids = payment_obj.search(cr,uid,[('payment_id','=',rs_payments['payment_id'])])
        if payment_ids == []:
            payment_id = payment_obj.create(cr,uid, paymentvals)
        else:
            payment_id = payment_ids[0]
            return payment_id



    def import_customer(self, cr, uid, ids, context):
        context = context or {}
        cscart = self.read(cr, uid, ids, [], context=context)
        if cscart:
            cscart = cscart[0]
            o = api.CsCart(cscart['url'], (cscart['auth_email'],cscart['auth_password']), cscart['rewrite'],cscart['ssl'])
            customers = o.getUsers()
            self.check_connnection(customers)
            for customer in customers:
                custo = customer
                customer_id = self.createCustomers(cr,uid,ids,custo,context=context)
        return True

    def export_product(self, cr, uid, ids, context={}):
        cscart = self.read(cr, uid, ids, [], context=context)
        if cscart:
            cscart = cscart[0]
            o = api.CsCart(cscart['url'], (cscart['auth_email'],cscart['auth_password']), cscart['rewrite'],cscart['ssl'])
        product_obj = self.pool.get('product.product')
        product_ids = product_obj.search(cr, uid, [('cscart_id', '!=', False)], context=context)
        for product_id in product_ids :
            product = product_obj.read(cr, uid, product_id, context=context)
            product_cscart_id = product.get('cscart_id',False)
            product_vals = {
                 'product': product.get('name'),
                 'price':product.get('list_price'),
                 'amount':product.get('qty_available'),
                 'list_price':product.get('standard_price'),
                 'full_description':product.get('description'),
            }
            prod = o.write('products',product_cscart_id,product_vals)
            self.check_export_connnection(prod)
            return prod

    def create_product(self, cr, uid, ids, rs_product, context, o=False):
        prod_obj = self.pool.get('product.product')
        category_obj = self.pool.get('product.category')
        categ_ids = category_obj.search(cr,uid,[('category_id','=',rs_product['main_category'])]) 
        product_ids = prod_obj.search(cr, uid, [('product_code','=', rs_product['product_code'])], context=context)
        image_64 = False
        rs_product = o.getProduct(int(rs_product['product_id']))
        if rs_product.get('main_pair',False) and rs_product['main_pair'].get('detailed',False) and rs_product['main_pair']['detailed'].get('image_path',False):
            path = rs_product['main_pair']['detailed']['image_path']
            image = urllib.urlopen(path)
            image_64 = False
            if image.code == 200:
                image_64 = base64.encodestring(image.read())
        product_vals = {
            'name' : rs_product['product'],
            'is_drop_ship': True,
            'procure_method' :'make_to_order',
            'list_price' : rs_product['base_price'],
            'categ_id': categ_ids[0] if categ_ids else False,
            'product_code':rs_product['product_code'],
            'cs_cart':True,
            'weight':rs_product['weight'],
            'description' :rs_product['full_description'],
            'image_medium':image_64,
            'cscart_id':rs_product['product_id'],
        }
        if not product_ids:
            prod_id = prod_obj.create(cr, uid, product_vals)
            sup = False
            supplier_id = int(rs_product.get('supplier_id',False)) if rs_product.get('supplier_id',False) else False
            if supplier_id : 
                 sup = self.pool.get('res.partner').search(cr,uid,[('cscart_id','=',supplier_id)])
                 if not sup and o:
                    suppl = o.getSupplier(supplier_id)
                    supplier_id = self.createSuppliers(cr,uid,ids,suppl,context=context)
                    sup = [supplier_id]
                 if sup :
                    sup = sup[0]
                    vals = {
                        'seller_ids':[(0,0,{'name':sup,
                                        'sup_price':float(rs_product.get('price')),
                                        'min_qty':float(0.0),
                                        'delay': int(1),
                                        })],
                       }
                 prod_obj.write(cr, uid, [prod_id], vals, context=context)
        else:
            prod_id = prod_obj.write(cr, uid, product_ids, product_vals,context=context)
        cr.commit()
        return prod_id

    def import_product(self,  cr, uid, ids ,context):
        ncr = pooler.get_db(cr.dbname).cursor()
        cscart = self.read(ncr, uid, ids, [], context=context)
        if cscart:
            cscart = cscart[0]
            o = api.CsCart(cscart['url'], (cscart['auth_email'],cscart['auth_password']), cscart['rewrite'],cscart['ssl'])
            page = 1
            while 1:
                params = {'page':page}
                products = o.getProducts(params)
                self.check_connnection(products)
                products = products['products']
                if products == []:
                    self.write(ncr, uid,ids,{'progress_status':'completed'},context=context)
                    break
                page = page + 1
                product_obj = self.pool.get('product.product')
                for product in products:
                  product_id = self.create_product(ncr,uid,ids,product,context,o)
                ncr.commit()
                time.sleep(10)
        ncr.commit()
        ncr.close()
        
        return True

    def import_category(self, cr, uid, ids, context={}):
        cscart = self.read(cr, uid, ids, [], context=context)
        if cscart:
            cscart = cscart[0]
            o = api.CsCart(cscart['url'], (cscart['auth_email'],cscart['auth_password']), cscart['rewrite'],cscart['ssl'])
            cat_id = []
            page = 1
            #while 1:
            params = {'page':page}
            rs_categories = o.getCategories(params)
            self.check_connnection(rs_categories)
            category_obj = self.pool.get('product.category')
            for category in rs_categories:
               vals = { 'name':category['category'],'category_id':category['category_id'],'cscart_parent_id':category['parent_id']}
               cat= category_obj.create(cr,uid,vals)
               cat_id.append(cat)
            for record in category_obj.browse(cr,uid,cat_id):
                self.create_product_categories(cr,uid,ids,record,context)
        return True

    def create_product_categories(self, cr, uid, ids,record,context):
        category_obj = self.pool.get('product.category')
        par_id = category_obj.search(cr,uid,[('category_id','=',record.cscart_parent_id)])
        vals = {}
        if len(par_id) > 0 :
            vals ={'parent_id':par_id[0]}
        category_obj.write(cr,uid, record.id,vals)
        return True

    def import_orders_cscart(self, cr, uid, ids, context={}):
        cscart = self.read(cr, uid, ids, [], context=context)
        if cscart:
            cscart = cscart[0]
            context.update({'instance_id':cscart['id']})
            context.update({'journal_id':cscart['journal_id']})
            o = api.CsCart(cscart['url'], (cscart['auth_email'],cscart['auth_password']), cscart['rewrite'],cscart['ssl'])
            time_from = cscart['since_date']
            params = {'items_per_page':20}
            if time_from :
                timestamp = time.mktime(datetime.datetime.strptime(time_from, "%Y-%m-%d").timetuple())
                params = {'period': 'HD','time_from': timestamp,'items_per_page':20}
            page = 1
            while 1:
                params['page'] = page
                rs_orders = o.getOrders(params)
                self.check_connnection(rs_orders)
                if not rs_orders or rs_orders == []:
                    print "not stopped"
                    break
                page = page + 1
                for order in rs_orders:
                   sale_order = o.getOrder(order['order_id'])
                   self.create_order(cr, uid, ids, sale_order, context=context)
                cr.commit()
                time.sleep(10)
        return True

    def createCustomerAddress(self, cr, uid, id, resultvals, part_id, context={}):
        country_obj = self.pool.get('res.country')
        state_obj = self.pool.get('res.country.state')
        if not part_id:
            return False
        city = resultvals['city']
        postalcode = resultvals['zip']
        addressvals = {
                'name' : resultvals['name'],
                'street' : resultvals['address'],
                'street2': resultvals['address2'],
                'city' : city,
                'phone' : resultvals['phone'] or False,
                'zip' : postalcode,
                'partner_id' : part_id,
                'type' : 'default',
            }
        address_id = self.pool.get('res.partner').create(cr,uid,addressvals)
        return address_id

    def createCustomers(self, cr, uid, ids, rs_customer,part_id=0, context={}):
        partner_id = False
        partner_obj = self.pool.get('res.users')
        partnervals = {
#            'supplier' : True,
#            'customer' : True,
#            'cscart':True,
            'name' : "%s %s" %(rs_customer['firstname'],rs_customer['lastname']),
            'login' : rs_customer['email'],
            'cscart_id' : rs_customer['user_id'],
            'email':rs_customer['email'],
        }
        user_ids = partner_obj.search(cr,uid,[('cscart_id','=',rs_customer['user_id'])])
        
        if user_ids == [] and rs_customer['email'] != '':
            user_id = partner_obj.create(cr,uid, partnervals)
            cr.commit()
        elif user_ids != []:
            user_id = user_ids[0]
            return user_id
	else:
	    return True

        # code for Payment an order...... 
    def _get_journal_id(self, cr, uid, context={}):
        if context is None: context = {}
        if context.get('invoice_id', False):
            currency_id = self.pool.get('account.invoice').browse(cr, uid, context['invoice_id'], context=context).currency_id.id
            journal_id = self.pool.get('account.journal').search(cr, uid, [('currency', '=', currency_id)], limit=1)
            return journal_id and journal_id[0] or False
        res = self.pool.get('account.journal').search(cr, uid, [('type', '=','bank')], limit=1)
        return res and res[0] or False

    def _get_currency_id(self, cr, uid,journal_id,context={}):
        if context is None: context = {}
        journal = self.pool.get('account.journal').browse(cr, uid, journal_id, context=context)
        if journal.currency:
            return journal.currency.id
        return self.pool.get('res.users').browse(cr, uid, uid, context=context).company_id.currency_id.id

    def sales_order_payment(self,cr,uid,payment,context={}):
        """
        @param payment: List of invoice_id, reference, partner_id ,journal_id and amount
        @param context: A standard dictionary
        @return: True
        """
        if context is None:
            context = {}
        voucher_obj = self.pool.get('account.voucher')
        voucher_line_obj = self.pool.get('account.voucher.line')
        partner_id = payment.get('partner_id')
        journal_id = payment.get('journal_id',False)
        if not journal_id:
            journal_id = self._get_journal_id(cr,uid,context)
        amount = payment.get('amount',0.0)
        date = payment.get('date',time.strftime('%Y-%m-%d'))
        entry_name = payment.get('reference')
        currency_id1 = self._get_currency_id(cr,uid,journal_id)
        invoice_obj = self.pool.get('account.invoice').browse(cr,uid,payment.get('invoice_id'))
        invoice_name = invoice_obj.number

        data = voucher_obj.onchange_partner_id(cr, uid, [invoice_obj.id], partner_id, journal_id,int(amount), currency_id1, 'receipt', date, context)['value']
        
        for line_cr in data.get('line_cr_ids'):
            if line_cr['name'] == invoice_name:
                amount = line_cr['amount_original']
        account_id = data['account_id']
        statement_vals = {
                            'reference': entry_name,
                            'journal_id': journal_id,
                            'amount': amount,
                            'date' : date,
                            'partner_id': partner_id,
                            'account_id': account_id,
                            'type': 'receipt',
                         }
        if data.get('payment_rate_currency_id'):
            statement_vals['payment_rate_currency_id'] = data['payment_rate_currency_id']
            company_currency_id=self.pool.get('res.users').browse(cr, uid, uid, context=context).company_id.currency_id.id
            if company_currency_id<>data['payment_rate_currency_id']:
                statement_vals['is_multi_currency']=True
    
        if data.get('paid_amount_in_company_currency'):
            statement_vals['paid_amount_in_company_currency'] = data['paid_amount_in_company_currency']
        if data.get('writeoff_amount'):
            statement_vals['writeoff_amount'] =data['writeoff_amount']
        if data.get('pre_line'):
            statement_vals['pre_line'] = data['pre_line']
        if data.get('payment_rate'):
            statement_vals['payment_rate'] = data['payment_rate']
        statement_id = voucher_obj.create(cr, uid, statement_vals, context)
        for line_cr in data.get('line_cr_ids'):
            line_cr.update({'voucher_id':statement_id})
            if line_cr['name'] == invoice_name:
                line_cr['amount'] = line_cr['amount_original']
                line_cr['reconcile'] = True
            line_cr_id=self.pool.get('account.voucher.line').create(cr,uid,line_cr)
        for line_dr in data.get('line_dr_ids'):
            line_dr.update({'voucher_id':statement_id})
            line_dr_id=self.pool.get('account.voucher.line').create(cr,uid,line_dr)
        wf_service = netsvc.LocalService("workflow")
        wf_service.trg_validate(uid, 'account.voucher', statement_id, 'proforma_voucher', cr)
        voucher = voucher_obj.browse(cr, uid, statement_id, context=context)
        ddd = self.pool.get('account.invoice').write(cr, uid, [invoice_obj.id], {
                        'state': 'paid', 
                       # 'payment_ids': [(6, 0, [voucher.move_ids[0].id])] 
                    }, context=context)

        self.pool.get('sale.order').write(cr, uid, [invoice_obj.order_id.id], {'invoiced':True}, context=context)
        return True


    def create_order(self, cr, uid, ids, rs_order, context):
        saleorderid = False
        saleorder_obj = self.pool.get('sale.order')
        partner_obj = self.pool.get('res.partner')
        users_obj = self.pool.get('res.users')
        payment_obj= self.pool.get('cscart.payment.method')
        payment_id = rs_order['payment_id']
        payment_ids = payment_obj.search(cr,uid,[('payment_id','=',rs_order['payment_id'])])
        journal_id = False
        if payment_ids != [] :
            payment = payment_obj.read(cr,uid,payment_ids[0],['journal_id'],context=context)['journal_id'][0]
        else :
            journal_id = context.get('journal_id')[0]

        user_ids = users_obj.search(cr,uid,[('cscart_id','=',rs_order['user_id'])])
        user_id = user_ids[0] if user_ids != [] else False
        customers = {
            'name' :"%s %s " %(rs_order['b_firstname'], rs_order['b_lastname']),
            'email':rs_order['email'],
            'user_id':user_id,
            'customer':True,
            'cscart':True,
            'cscart_id': context.get('instance_id', False),
        }
        if rs_order != {}:
            country_ids =  self.pool.get('res.country').search(cr,uid,[('code','=',rs_order['b_country'])])
            country_id = country_ids[0] if country_ids else False
            state_ids =  self.pool.get('res.country.state').search(cr,uid,[('code','=',rs_order['b_state']),('country_id','=',country_id)])
            billing_address = {
                 'name' :"%s %s " %(rs_order['b_firstname'], rs_order['b_lastname']),
                 'street' :"%s %s " %(rs_order['b_address'], rs_order['b_address_2']),
                 'city' :rs_order['b_city'],
                 'state_id':state_ids[0] if state_ids else False ,
                 'country_id':country_id,
                 'zip':rs_order['b_zipcode'],
                 'phone' :rs_order['b_phone'] or False,
                 'type':'invoice',
                 'user_id':user_id,
                 'cscart':True,
                 'cscart_id': context.get('instance_id', False),
            }
            country_ids =  self.pool.get('res.country').search(cr,uid,[('code','=',rs_order['s_country'])])
            country_id = country_ids[0] if country_ids else False
            state_ids =  self.pool.get('res.country.state').search(cr,uid,[('code','=',rs_order['s_state']),('country_id','=',country_id)])
            shipping_address = {
                 'name' :"%s %s " %(rs_order['s_firstname'], rs_order['s_lastname']),
                 'street' :"%s %s " %(rs_order['s_address'], rs_order['s_address_2']),
                 'city':rs_order['s_city'],
                 'state_id':state_ids[0] if state_ids else False ,
                 'country_id':country_id,
                 'zip':rs_order['s_zipcode'],
                 'phone':rs_order['s_phone'] or False,
                 'type':'delivery',
                 'user_id':user_id,
                 'cscart':True,
                 'cscart_id': context.get('instance_id', False),
            }
            customers.update(shipping_address)
            saleorderid = saleorder_obj.search(cr,uid,[('cscart_order_id','=',rs_order['order_id'])])
            partner_id = False
            partner_billing_id = False
            partner_shipping_id = False
            if not saleorderid:

                #CREATING CUSTOMERS AND ADDRESSES
                customers_ids = self.pool.get('res.partner').search(cr,uid,[('name','=',customers['name']),('street','=',customers['street']),('country_id','=',customers['country_id'])])
                if customers_ids:
                    partner_id = customers_ids[0] if customers_ids else False
                else :
                    partner_id = partner_obj.create(cr,uid,customers,context=context)


                billing_cust_ids = self.pool.get('res.partner').search(cr,uid,[('name','=',billing_address['name']),('street','=', billing_address['street']),('country_id','=',billing_address['country_id'])])
                if billing_cust_ids:
                    billing_address.update({'parent_id':partner_id })
                    partner_billing_id = billing_cust_ids[0] if billing_cust_ids else False
                else :
                    billing_address.update({'parent_id':partner_id })
                    partner_billing_id = partner_obj.create(cr,uid,billing_address,context=context)


                shipping_cust_ids = self.pool.get('res.partner').search(cr,uid,[('name','=',shipping_address['name']),('street','=', shipping_address['street']),('country_id','=',shipping_address['country_id'])])
                if shipping_cust_ids:
                    shipping_address.update({'parent_id':partner_id })
                    partner_shipping_id = shipping_cust_ids[0] if shipping_cust_ids else False
                else :
                    shipping_address.update({'parent_id':partner_id })
                    partner_shipping_id = partner_obj.create(cr,uid,shipping_address,context=context)


                pricelist_id = partner_obj.browse(cr,uid,partner_id)['property_product_pricelist'].id
                ordervals = {
                            'name' : "#%s"%(rs_order['order_id']),
                            'partner_invoice_id' :int(partner_billing_id),
                            'partner_id' : int(partner_id),
                            'partner_shipping_id' : int(partner_shipping_id),
                            'state' : 'draft',
                            'pricelist_id' : int(pricelist_id),
                            'cscart_order_id': rs_order['order_id'],
                            'cscart_instance_id': context.get('instance_id', False),
                            'user_id':user_id,
                            'payment_method_id': payment_ids[0] if payment_ids else False,
                }
                product_obj = self.pool.get('product.product')
                if rs_order:
                     saleorderid = saleorder_obj.create(cr,uid,ordervals)
                     for product in rs_order['products']:
                        product_code = rs_order['products'][product]['product_code']
                        product_ids = rs_order['products'][product]['product_id']
                        product_search = product_obj.search(cr,uid,[('product_code','=',product_code)])
                        product_id = False
                        if not product_search:
                          cscart = self.read(cr, uid, ids, [], context=context)
                          if cscart:
                            cscart = cscart[0]
                            o = api.CsCart(cscart['url'], (cscart['auth_email'],cscart['auth_password']), cscart['rewrite'],cscart['ssl'])
                            rs_product = o.getProduct(product_ids)
                            product_id = self.create_product(cr,uid,ids,rs_product,context,o)
                        else:
                            product_id =product_search[0]
                        product_note = rs_order['products'][product]['product'] 
                        variants = rs_order['products'][product]['extra'].get('product_options_value', False)
                        if variants:
                            product_note += "\n"
                            for v in variants:
                                product_note += "%s: %s (+ %s) \n" % (v['option_name'], v['variant_name'], v['modifier'])
                        supplier_id = False
                        psinfo_pool    = self.pool.get('product.supplierinfo')
                        if not supplier_id:
                            psinfo_partner = psinfo_pool.search(cr, uid, [('product_id','=',product_id)], order='sequence', limit=1)
                        if psinfo_partner:
                            supplier_id  = psinfo_pool.browse(cr, uid, psinfo_partner[0]).name.id
                        product_rec = product_obj.browse(cr,uid,product_id)
                        orderlinevals = {
                            'order_id' : saleorderid,
                            'product_uom' : product_rec.product_tmpl_id.uom_id.id,
                            'product_uom_qty': float(rs_order['products'][product]['amount']),
                            'name' : product_note,
                            'price_unit' : float(rs_order['products'][product]['price']),
                            'price_subtotal': float(rs_order['products'][product]['subtotal']),
                            'delay' : product_obj.browse(cr,uid,product_id).product_tmpl_id.sale_delay,
                            'invoiced' : False,
                            'state' : 'confirmed',
                            'product_id' : product_id,
                            'tax_id' : [],
                            'cscart_item_code' : product,
                        }
                        if product_rec.is_drop_ship and supplier_id:
                            dropship ={'drop_ship': product_rec.is_drop_ship,'supplier_id': supplier_id,}
                            orderlinevals.update(dropship)
                        sale_order_line_obj = self.pool.get('sale.order.line')
                        saleorderlineid = sale_order_line_obj.create(cr, uid, orderlinevals)

                     if saleorderid :
                            if rs_order['status'] in ['P','B']:
                                #operation for processed order.
                                saleorder_obj.create_purchase_quotation(cr, uid, [saleorderid],context=context)
                                saleorder_obj.action_button_confirm(cr, uid, [saleorderid],context=context)
                                wf_service = netsvc.LocalService('workflow')
                                wf_service.trg_validate(uid, 'sale.order', saleorderid, 'manual_invoice', cr)
                                #saleorder_obj.manual_invoice(cr,uid,[saleorderid])
                                for invoice in saleorder_obj.browse(cr, uid, saleorderid, context=context).invoice_ids:
                                     wf_service.trg_validate(uid, 'account.invoice', invoice.id, 'invoice_open', cr)
#                                     self.pool.get('account.invoice').invoice_pay_customer(cr, uid, [invoice.id], context=context)
                                     #amount_total = invoice.amount_total
                                     #journal = self.pool.get('account.journal').browse(cr,uid,context.get('journal_id')[0],context=context)

                                     payment = {
                                            'invoice_id': invoice.id,
                                            'reference': invoice.origin,
                                            'partner_id': invoice.partner_id.id,
                                            'journal_id': journal_id,
                                            'amount': invoice.amount_total
                                     }
                                     self.sales_order_payment(cr, uid, payment, context=context)
                            elif rs_order['status'] == 'C':
                                #operation for Complete order.
                                saleorder_obj.action_button_confirm(cr, uid, [saleorderid],context=context)
                                wf_service = netsvc.LocalService('workflow')
                                wf_service.trg_validate(uid, 'sale.order', saleorderid, 'manual_invoice', cr)
                                for invoice in saleorder_obj.browse(cr, uid, saleorderid, context=context).invoice_ids:
                                    wf_service.trg_validate(uid, 'account.invoice', invoice.id, 'invoice_open', cr)
                                    payment = {
                                           'invoice_id': invoice.id,
                                           'reference': invoice.origin,
                                           'partner_id': invoice.partner_id.id,
                                           'journal_id': journal_id,
                                           'amount': invoice.amount_total
                                    }
                                    self.sales_order_payment(cr, uid, payment, context=context)
                                saleorder_obj.write(cr, uid,[saleorderid],{'invoiced':True,'shipped':True,'state':'done'},context=context)


                            elif rs_order['status'] == 'D':
                                #operation for Declined order.
                                saleorder_obj.action_cancel(cr, uid, [saleorderid],context=context)

                            elif rs_order['status'] == 'I':
                                saleorder_obj.action_cancel(cr, uid, [saleorderid],context=context)
                cr.commit()
        return True

    def check_connnection(self, response):
        if type(response) == type({}) and response.get('status', False) and response.get('message', False):
            message = response.get('message', 'Can not synchronization data. Authorization error.')
            code = response.get('status', '')
            raise osv.except_osv(_('Connection Error!'), _('%s %s'%(message, code)))
        return True

    def check_export_connnection(self, response):
        if response.status_code != 200:
            raise osv.except_osv(_('Connection Error!'), _('%s %s'%(response.reason, response.status_code)))
        return True


    def import_supplier(self, cr, uid, ids, context):
        context = context or {}
        cscart = self.read(cr, uid, ids, [], context=context)
        if cscart:
            cscart = cscart[0]
            o = api.CsCart(cscart['url'], (cscart['auth_email'],cscart['auth_password']), cscart['rewrite'],cscart['ssl'])
            page = 1
            suppliers = []
            while 1:
                params = {'page':page}
                data = o.getSuppliers(params)
                self.check_connnection(data)
                suppliers = o.getSuppliers(params)[0]
                if suppliers == []:
                    break
                page = page + 1
                for supplier in suppliers:
                    suppl = o.getSupplier(int(supplier.get('supplier_id',False)))
                    supplier_id = self.createSuppliers(cr,uid,ids,suppl,context=context)
                cr.commit()
        return True

    def createSuppliers(self, cr, uid, ids, rs_supplier,part_id=0, context={}):
        partner_id = False
        partner_obj = self.pool.get('res.partner')
        country_ids =  self.pool.get('res.country').search(cr,uid,[('code','=',rs_supplier['country'])])
        country_id = country_ids[0] if country_ids else False
        state_ids =  self.pool.get('res.country.state').search(cr,uid,[('code','=',rs_supplier['state']),('country_id','=',country_id)])
        partnervals = {
            'supplier' : True,
            'customer' : False,
            'cscart':True,
            'name' :rs_supplier['name'],
            'cscart_id' : rs_supplier['supplier_id'],
            'email':rs_supplier['email'],
            'city':rs_supplier['city'],
            'fax':rs_supplier['fax'],
            'country_id': country_id,
            'zip':rs_supplier['zipcode'],
            'phone':rs_supplier['phone'],
            'state_id':state_ids[0] if state_ids else False ,
            'street':rs_supplier['address'],
            'website':rs_supplier['url'],
        }
        supplier_search = partner_obj.search(cr,uid,[('supplier','=',True),('cscart_id','=',rs_supplier['supplier_id'])])
        if supplier_search == []:
            partner_id = partner_obj.create(cr,uid, partnervals)
        else:
            partner_id = part_id
        return partner_id


    def export_orders(self, cr, uid, ids, context={}):
        cscart = self.read(cr, uid, ids, [], context=context)
        if cscart:
            cscart = cscart[0]
            o = api.CsCart(cscart['url'], (cscart['auth_email'],cscart['auth_password']), cscart['rewrite'],cscart['ssl'])
        orders_obj = self.pool.get('sale.order')
        orders_ids = orders_obj.search(cr, uid, [('cscart_order_id', '!=', False)], context=context)
        order_states = {
                       'cancel':'I',
                       'done' : 'C',
                      }

        for orders_id in orders_ids :
            orders = orders_obj.read(cr, uid, orders_id,['state','cscart_order_id'],context=context)
            orders_cscart_id = orders.get('cscart_order_id',False)

            state =  order_states.get(orders.get('state'),False)
            if state :
                ordr = o.write('orders',orders_cscart_id,{'status':state})
                self.check_export_connnection(ordr)
        return True

    def light_import_products(self, cr, uid, ids, context={}):
        self.write(cr, uid,ids,{'progress_status':'start'},context=context)
        self._thread_import_products(cr,uid,ids,context=context)


    def _thread_import_products(self, cr, uid, ids, context={}):
        thread_sync = threading.Thread(target = self.import_product, args =(cr,uid,ids,context))
        thread_sync.start()
        return True





class stock_picking(osv.osv):
    _inherit = "stock.picking"
    _columns = {
        'shipping_method':fields.selection((('1','Custom shipping method'),
                                            ('3','FedEx 2nd day'),
                                            ('4','UPS 3day Select'),
                                            ('5','USPS Media Mail')),'Shipping Method'),
        'tracking_number':fields.char('Tracking Number'),
        'carrier' :fields.selection((( 'aup','AUP') ,
                                     ('can','CAN'), 
                                     ('dhl','DHL'),
                                     ('fedex','FedEx'), 
                                     ('swisspost','SwissPost'), 
                                     ('temando','Temando'),
                                     ('ups','UPS'), 
                                     ('usps','USPS')),'Carrier'),
        'comment' : fields.text('Comment'),
        'order_status' :fields.selection((  ('','Do not change'),
                                            ('B','Backordered'),
                                            ('C','Complete'),
                                            ('D','Declined'),
                                            ('F','Failed'),
                                            ('I','Cancelled'),
                                            ('O','Open'),
                                            ('P','Processed')),'Order Status'),
        'notification' : fields.boolean('E-mail Notification'),
        'sent' : fields.boolean('Sent'),
    }
    _defaults ={'order_status' :'C'}

    def check_connnection(self, response):
        if type(response) == type({}) and response.get('status', False) and response.get('message', False):
            message = response.get('message', 'Can not synchronization data. Authorization error.')
            code = response.get('status', '')
            raise osv.except_osv(_('Connection Error!'), _('%s %s'%(message, code)))
        return True

    def new_shipment(self, cr, uid, ids, context={}):
        shipment = self.browse(cr,uid,ids[0],context=context)
        origin = shipment.origin.split(':')[-1]
        if origin and origin[0] != '#':
            return True
        origin =origin[1:]
        cscart= shipment.purchase_id.sale_order_id.cscart_instance_id
        o = api.CsCart(cscart.url,(cscart.auth_email,cscart.auth_password), cscart.rewrite,cscart.ssl)
        if shipment.sent == True :
            return True
        else :
            shipment_data = {
            'shipping':shipment.shipping_method,
            'user_id': u'1',
            'shipping_id': shipment.shipping_method,
            'tracking_number':shipment.tracking_number,
            'order_id': origin,
            'carrier': shipment.carrier,
            'notification' : shipment.notification,
            'comments' : shipment.comment or "",
            }
            products = []
            for move in shipment.move_lines :
                products.append({move.cscart_item_code:move.product_qty})
                shipment_data['products'] = {move.cscart_item_code:str(move.product_qty)}
            data = o.create('shipments',shipment_data)
            self.check_connnection(data)
            self.write(cr, uid,ids,{'sent':True},context=context)
            data = o.write('orders',origin, {'status':shipment.order_status})
#            self.check_connnection(data)




class stock_picking_out(osv.osv):
    _inherit = "stock.picking.out"
    _columns = {
        'shipping_method':fields.selection((('1','Custom shipping method'),
                                            ('3','FedEx 2nd day'),
                                            ('4','UPS 3day Select'),
                                            ('5','USPS Media Mail')),'Shipping Method'),
        'tracking_number':fields.char('Tracking Number'),
        'carrier' :fields.selection((( 'aup','AUP') ,
                                     ('can','CAN'), 
                                     ('dhl','DHL'),
                                     ('fedex','FedEx'), 
                                     ('swisspost','SwissPost'), 
                                     ('temando','Temando'),
                                     ('ups','UPS'), 
                                     ('usps','USPS')),'Carrier'),
        'comment' : fields.text('Comment'),
        'order_status' :fields.selection((  ('','Do not change'),
                                            ('B','Backordered'),
                                            ('C','Complete'),
                                            ('D','Declined'),
                                            ('F','Failed'),
                                            ('I','Cancelled'),
                                            ('O','Open'),
                                            ('P','Processed')),'Order Status'),
        'notification' : fields.boolean('E-mail Notification'),
        'sent' : fields.boolean('Sent'),
    }
    _defaults ={'order_status' :'C'}

    def check_connnection(self, response):
        if type(response) == type({}) and response.get('status', False) and response.get('message', False):
            message = response.get('message', 'Can not synchronization data. Authorization error.')
            code = response.get('status', '')
            raise osv.except_osv(_('Connection Error!'), _('%s %s'%(message, code)))
        return True

    def new_shipment(self, cr, uid, ids, context={}):
        shipment = self.browse(cr,uid,ids[0],context=context)
#        origin = shipment.origin.split(':')[-1]
#        print ">>>>>>>>>>>>>>",origin
#        if origin and origin[0] != '#':
#            return True
#            print ">>>>>>>>>>>>>>",origin
#        origin =origin[1:]
        origin= shipment.sale_id.cscart_order_id
        cscart= shipment.sale_id.cscart_instance_id
        o = api.CsCart(cscart.url,(cscart.auth_email,cscart.auth_password), cscart.rewrite,cscart.ssl)
        if shipment.sent == True or not shipment.tracking_number:
            return True
        else :
            shipment_data = {
            'shipping':shipment.shipping_method,
            'user_id': u'1',
            'shipping_id': shipment.shipping_method,
            'tracking_number':shipment.tracking_number,
            'order_id': origin,
            'carrier': shipment.carrier,
            'notification' : shipment.notification,
            'comments' : shipment.comment or "",
            }
           
            products = []
            for move in shipment.move_lines :
                products.append({move.cscart_item_code:move.product_qty})
                shipment_data['products'] = {move.cscart_item_code:str(move.product_qty)}
            print ">>>>>><<<<<<",shipment_data
            data = o.create('shipments',shipment_data)
            print ">>>>>><<<<<<>>>>>><<<<<<",data
            self.check_connnection(data)
            self.write(cr, uid,ids,{'sent':True},context=context)
            data = o.write('orders', origin, {'status':shipment.order_status})
            print ">>>>>><<<<<<>>>>>><<<<<<",data
#            self.check_connnection(data)




class cscart_payment_method(osv.osv):
    _name = "cscart.payment.method"
    _description = "cscart.payment.method"
    _columns = {
        'name': fields.char('Name',readonly= True),
        'processor': fields.char('Processor',readonly= True),
        'payment_category': fields.selection([('tab1','Credit card'),
                                              ('tab2','Internet payments'),
                                              ('tab3','Other payment options')], 'Payment Category',readonly= True),
        'user_groups_all':fields.boolean('All',readonly= True),
        'user_groups_guest':fields.boolean('Guest',readonly= True),
        'user_groups_registered':fields.boolean('Registered',readonly= True),
        'description': fields.char('Description',readonly= True),
        'a_surcharge':fields.float('Absolute surcharge',readonly= True),
        'p_surcharge':fields.float('Percent Surcharge',readonly= True),
        'payment_id': fields.char('payment id',readonly= True),
        'journal_id': fields.many2one('account.journal', 'Journal', domain=[('type','in',['bank', 'cash'])],required=False),
     }






# vim:expandtab:smartindent:tabstop=4:softtabstop=4:shiftwidth=4:
