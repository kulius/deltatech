# -*- coding: utf-8 -*-
# ©  2017 Deltatech
# See README.rst file on addons root folder for license details


import base64
import zipfile
from io import StringIO
from io import BytesIO
import configparser

from odoo import models, fields, api, _
from odoo.exceptions import except_orm, Warning, RedirectWarning
import odoo.addons.decimal_precision as dp

import html2text


class export_mentor(models.TransientModel):
    _name = 'export.mentor'
    _description = "Export Mentor"

    name = fields.Char(string='File Name', readonly=True)
    data_file = fields.Binary(string='File', readonly=True)
    state = fields.Selection([('choose', 'choose'),  # choose period
                              ('get', 'get')], default='choose')  # get the file

    item_details = fields.Boolean(string="Item Details")
    code_article = fields.Char(string="Code Article")

    # period_id = fields.Many2one('account.period', string='Period' , required=True )

    date_range_id = fields.Many2one('date.range', string='Date range')
    date_from = fields.Date(string='Start Date', required=True, default=fields.Date.today)
    date_to = fields.Date(string='End Date', required=True, default=fields.Date.today)

    result = fields.Html(string="Result Export", readonly=True)

    journal_ids = fields.Many2many('account.journal', string='Journals')

    @api.onchange('date_range_id')
    def onchange_date_range_id(self):
        """Handle date range change."""
        if self.date_range_id:
            self.date_from = self.date_range_id.date_start
            self.date_to = self.date_range_id.date_end

    def get_cod_fiscal(self, partner):
        if partner.is_company:
            if not partner.vat_subjected:
                cod_fiscal = partner.vat.replace('RO', '')
            else:
                cod_fiscal = partner.vat
        else:
            cod_fiscal = partner.cnp
        return cod_fiscal

    def get_cont(self, account_id):
        cont = account_id.code
        while cont[-1] == '0':
            cont = cont[:-1]
        return cont

    def get_temp_file(self, data):
        temp_file = StringIO()
        data.write(temp_file)
        txt = temp_file.getvalue()
        txt = txt.replace('\n', '\r\n')
        txt = txt.replace('False', '')
        txt = txt.replace(' = ', '=')
        temp_file.seek(0)
        temp_file.write(txt)
        return temp_file

    @api.model
    def do_export_parteneri(self, partner_ids):
        result_html = ''
        parteneri = configparser.ConfigParser()
        parteneri.optionxform = lambda option: option
        for partner in partner_ids:
            cod_fiscal = self.get_cod_fiscal(partner)

            sections_name = "ParteneriNoi_%s" % cod_fiscal
            parteneri[sections_name] = {
                'Denumire': partner.name,
                'Tara': partner.country_id.name,
                'Judet': partner.state_id.code,
                'Adresa': partner.street,
                'Sediu': '',
                'Telefon': partner.phone,
                'Email': partner.email
            }
        temp_file = self.get_temp_file(parteneri)

        return temp_file, result_html

    @api.model
    def do_export_articole(self, product_ids):
        result_html = ''
        articole = configparser.ConfigParser()
        articole.optionxform = lambda option: option

        for product in product_ids:
            sections_name = "ArticoleNoi_%s" % product.default_code
            articole[sections_name] = {
                'Denumire': product.name,
                'Serviciu': product.type == 'service' and 'D' or 'N',
                'TipContabil': product.categ_id.tip_contabil
            }
            if product.type == 'service':
                articole[sections_name]['ContServiciu'] = self.get_cont(product.categ_id.property_account_income_categ)

        temp_file = self.get_temp_file(articole)
        return temp_file, result_html

    @api.model
    def do_export_intrari(self, invoice_in_ids, voucher_in_ids):
        result_html = ''
        intrari = configparser.ConfigParser()
        intrari.optionxform = lambda option: option
        if invoice_in_ids:
            invoice = invoice_in_ids[0]

        intrari['InfoPachet'] = {
            'AnLucru': invoice.date_invoice[:4],
            'LunaLucru': invoice.date_invoice[5:7],
            'TipDocument': 'FACTURA INTRARE',
            'TotalFacturi': len(invoice_in_ids) + len(voucher_in_ids)
        }
        index = 1
        for invoice in invoice_in_ids:
            cod_fiscal = self.get_cod_fiscal(invoice.commercial_partner_id)

            sections_name = 'Factura_%s' % index
            NrDoc = invoice.reference or invoice.number
            # NrDoc = ''.join([s for s in invoice.number if s.isdigit()])
            intrari[sections_name] = {
                'NrDoc': NrDoc,
                'Data': invoice.date_invoice,  # todo: de verificat care este formatul de data
                'CodFurnizor': cod_fiscal,
                'TVAINCASARE': '',  # todo: determinare
                'PRORATA': '',
                'Moneda': '', # invoice.currency_id.name,
                'Curs': '',
                'Scadenta': '',
                'Majorari': '',
                'Observatii': '',
                'Discount': '',
                'TotalArticole': len(invoice.invoice_line_ids)
            }
            sections_name = 'Items_%s' % index
            intrari[sections_name] = {}
            item = 0
            for line in invoice.invoice_line_ids:
                item += 1
                intrari[sections_name]['Item_%s' % item] = ';'.join([
                    line.product_id.default_code or '',  # Cod intern/extern articol;
                    line.uom_id.name or '',
                    str(line.quantity),
                    str(line.price_unit_without_taxes),  # line.price_unit,
                    '',  # Simbol gestiune: pentru receptie/repartizare cheltuieli
                    str(line.discount),  # Discount linie
                    self.get_cont(line.account_id),  # Simbol cont articol serviciu;
                    '',  # Pret inregistrare;
                    '',  # Termen garantie;
                    '',  # Valoare suplimentara;
                    ''  # Observatii la nivel articol;
                ])
            index += 1

        temp_file = self.get_temp_file(intrari)

        return temp_file, result_html

    @api.model
    def do_export_iesiri(self, invoice_out_ids):
        result_html = ''
        iesiri = configparser.ConfigParser()
        iesiri.optionxform = lambda option: option
        temp_file = StringIO()
        iesiri.write(temp_file)
        return temp_file, result_html

    @api.multi
    def do_export(self):

        buff = BytesIO()

        files = []

        # This is my zip file
        zip_archive = zipfile.ZipFile(buff, mode='w')
        # zip_archive.comment = 'Arhiva pentru Mentor'

        partner_ids = self.env['res.partner']
        partner_in_ids = self.env['res.partner']
        product_ids = self.env['product.template']

        invoice_in_ids = self.env['account.invoice'].search([('date', '>=', self.date_from),
                                                             ('date', '<=', self.date_to),
                                                             ('state', 'in', ['open', 'paid']),
                                                             ('type', 'in', ['in_invoice', 'in_refund'])])

        voucher_in_ids = self.env['account.voucher'].search([('date', '>=', self.date_from),
                                                             ('date', '<=', self.date_to),
                                                             ('state', 'in', ['posted']),
                                                             ('voucher_type', 'in', ['purchase'])])

        for invoice in invoice_in_ids:
            for line in invoice.invoice_line_ids:
                product_ids |= line.product_id.product_tmpl_id

        for invoice in invoice_in_ids:
            partner_in_ids |= invoice.commercial_partner_id

        for voucher in voucher_in_ids:
            partner_in_ids |= voucher.partner_id.commercial_partner_id

        partner_out_ids = self.env['res.partner']
        invoice_out_ids = self.env['account.invoice'].search([('date', '>=', self.date_from),
                                                              ('date', '<=', self.date_to),
                                                              ('state', 'in', ['open', 'paid']),
                                                              ('type', 'in', ['out_invoice', 'out_refund'])])

        for invoice in invoice_out_ids:
            for line in invoice.invoice_line_ids:
                product_ids |= line.product_id.product_tmpl_id

        for invoice in invoice_out_ids:
            partner_out_ids |= invoice.commercial_partner_id

        date_start = fields.Date.from_string(self.date_from)
        date_stop = fields.Date.from_string(self.date_to)

        result_html = ' <div>Au fost exportate:</div>'
        result_html += '<div>Facturi de intrare: %s</div>' % str(len(invoice_in_ids))
        result_html += '<div>Bonuri fiscale: %s</div>' % str(len(voucher_in_ids))
        result_html += '<div>Facturi de iesire %s</div>' % str(len(invoice_out_ids))
        result_html += '<div>Produse %s</div>' % str(len(product_ids))
        result_html += '<div>Furnizori %s</div>' % str(len(partner_in_ids))
        result_html += '<div>Client %s</div>' % str(len(partner_out_ids))

        partner_ids = partner_in_ids | partner_out_ids
        temp_file, messaje = self.do_export_parteneri(partner_ids)

        result_html += messaje

        file_name = 'Partner.txt'
        zip_archive.writestr(file_name, temp_file.getvalue())

        temp_file, messaje = self.do_export_articole(product_ids)
        result_html += messaje

        file_name = 'Articole.txt'
        zip_archive.writestr(file_name, temp_file.getvalue())

        temp_file, messaje = self.do_export_intrari(invoice_in_ids, voucher_in_ids)
        result_html += messaje
        file_name = 'Facturi_Intrare.txt'
        zip_archive.writestr(file_name, temp_file.getvalue())

        temp_file, messaje = self.do_export_iesiri(invoice_out_ids)
        result_html += messaje
        file_name = 'Facturi_Iesire.txt'
        zip_archive.writestr(file_name, temp_file.getvalue())

        data = {'item_details': self.item_details,
                'code_article': self.code_article}

        # if invoice_in_ids:
        #     result = self.env['report'].get_html(records=invoice_in_ids, report_name='deltatech_mentor.report_invoice',
        #                                          data=data)
        #     if result:
        #         result = html2text.html2text(result).decode('utf8', 'replace')
        #         result = result.replace(chr(13), '\n')
        #         result = result.replace('\n\n', '\r\n')
        #         zip_archive.writestr('Facturi_Intrare.txt', result.encode('utf8'))
        #
        # if invoice_out_ids:
        #     result = self.env['report'].get_html(records=invoice_out_ids, report_name='deltatech_mentor.report_invoice',
        #                                          data=data)
        #     if result:
        #         result = html2text.html2text(result.decode('utf8', 'replace'))
        #         result = result.replace(chr(13), '\n')
        #         result = result.replace('\n\n', '\r\n')
        #         zip_archive.writestr('Facturi_Iesire.txt', result.encode('utf8'))
        #
        # if product_ids:
        #     result = self.env['report'].get_html(records=product_ids,
        #                                          report_name='deltatech_mentor.report_product_template')
        #     if result:
        #         result = html2text.html2text(result.decode('utf8', 'replace'))
        #         result = result.replace(chr(13), '\n')
        #         result = result.replace('\n\n', '\r\n')
        #         zip_archive.writestr('Articole.txt', result.encode('utf8'))
        #
        # if partner_ids:
        #     result = self.env['report'].get_html(records=partner_ids, report_name='deltatech_mentor.report_res_partner')
        #     if result:
        #         result = html2text.html2text(result.decode('utf8', 'replace'))
        #         result = result.replace(chr(13), '\n')
        #         result = result.replace('\n\n', '\r\n')
        #         zip_archive.writestr('Partner.txt', result.encode('utf8'))

        # Here you finish editing your zip. Now all the information is
        # in your buff StringIO object
        zip_archive.close()

        out = base64.encodestring(buff.getvalue())
        buff.close()

        filename = 'ExportOdooMentor_%s_%s' % (self.date_from, self.date_to)
        extension = 'zip'

        name = "%s.%s" % (filename, extension)
        self.write({'state': 'get',
                    'data_file': out,
                    'name': name,
                    'result': result_html})

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'export.mentor',
            'view_mode': 'form',
            'view_type': 'form',
            'res_id': self.id,
            'views': [(False, 'form')],
            'target': 'new',
        }
