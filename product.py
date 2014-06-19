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

from osv import fields, osv

class product_category(osv.osv):
   _inherit ="product.category"
   _columns = {
        'category_id' : fields.char('CategoryId',size=20),
        'cscart_parent_id':fields.char('CategoryId',size=20),
    }

product_category()

class product_product(osv.osv):
    _inherit = 'product.product'
    _columns = {
        'product_code': fields.char('Product Code', size=20,readonly=True),
        'cs_cart': fields.boolean('CsCart', size=20,readonly=True),
        'cscart_id': fields.char('cscart id'),
    }

product_product()

# vim:expandtab:smartindent:tabstop=4:softtabstop=4:shiftwidth=4:
