# The COPYRIGHT file at the top level of this repository contains the full
# copyright notices and license terms.
from decimal import Decimal
from trytond.model import fields
from trytond.pool import Pool, PoolMeta
from trytond.pyson import Eval
from trytond.tools import grouped_slice

__all__ = ['Plan', 'Commission', 'Invoice', 'Reconciliation']
__metaclass__ = PoolMeta


class Plan:
    __name__ = 'commission.plan'

    @classmethod
    def __setup__(cls):
        super(Plan, cls).__setup__()
        partial_payment = ('partial_payment', 'On Partial Payment')
        if not partial_payment in cls.commission_method.selection:
            cls.commission_method.selection.append(partial_payment)


class Commission:
    __name__ = 'commission'

    @classmethod
    def _get_origin(cls):
        models = super(Commission, cls)._get_origin()
        models.append('account.move.line')
        return models


class Invoice:
    __name__ = 'account.invoice'
    commissions = fields.Function(fields.One2Many('commission', None,
            'Commissions',
            states={
                'invisible': ~Eval('commissions'),
                }),
        'get_commissions')

    def get_commissions(self, name):
        pool = Pool()
        Commission = pool.get('commission')
        ids = [l.id for l in self.lines_to_pay]
        return [x.id for x in Commission.search([
                    ('origin.id', 'in', ids, 'account.move.line'),
                    ])]

    @classmethod
    def create_commissions(cls, invoices):
        pool = Pool()
        Commission = pool.get('commission')
        non_partial_invoices = []
        partial_invoices = []
        for invoice in invoices:
            if (invoice.agent and invoice.agent.plan and
                    invoice.agent.plan.commission_method == 'partial_payment'):
                partial_invoices.append(invoice)
            else:
                non_partial_invoices.append(invoice)
        to_create = []
        for invoice in partial_invoices:
            commissions = invoice.get_partial_commissions()
            if commissions:
                to_create += [c._save_values for c in commissions]
        super_commissions = super(Invoice, cls).create_commissions(
            non_partial_invoices)
        commissions = Commission.create(to_create)
        return super_commissions + commissions

    def get_partial_commissions(self):
        pool = Pool()
        Currency = pool.get('currency.currency')
        Commission = pool.get('commission')
        commissions = []
        if not self.agent or not self.agent.plan or not self.move:
            return commissions
        ids = [l.id for l in self.lines_to_pay]
        existing_lines = set([x.origin.id for x in Commission.search([
                        ('origin.id', 'in', ids, 'account.move.line'),
                        ])])
        plan = self.agent.plan
        total = Currency.compute(self.currency, self.untaxed_amount,
            self.agent.currency)
        term_lines = self.payment_term.compute(total,
            self.company.currency, self.invoice_date)
        if not term_lines:
            term_lines = [(self.invoice_date, total)]
        for (date, amount), line in zip(term_lines, self.lines_to_pay):
            if line.id in existing_lines:
                continue
            if self.type == 'out_credit_note':
                amount *= -1
            amount = self._get_partial_commission_amount(amount, plan)
            if amount:
                digits = Commission.amount.digits
                amount = amount.quantize(Decimal(str(10.0 ** -digits[1])))
            if not amount:
                continue
            commission = Commission()
            commission.origin = str(line)
            commission.agent = self.agent
            commission.product = plan.commission_product
            commission.amount = amount
            commissions.append(commission)

        return commissions

    def _get_partial_commission_amount(self, amount, plan, pattern=None):
        return plan.compute(amount, None, pattern=pattern)


class Reconciliation:
    __name__ = 'account.move.reconciliation'

    @classmethod
    def create(cls, vlist):
        pool = Pool()
        Commission = pool.get('commission')

        reconciliations = super(Reconciliation, cls).create(vlist)

        line_ids = set()
        for reconciliation in reconciliations:
            line_ids |= {l.id for l in reconciliation.lines}

        for sub_ids in grouped_slice(line_ids):
            commissions = Commission.search([
                    ('date', '=', None),
                    ('origin.id', 'in', sub_ids, 'account.move.line'),
                    ])
            to_write = []
            for commission in commissions:
                date = max(l.date for l in
                    commission.origin.reconciliation.lines)
                to_write.extend(([commission], {
                            'date': date,
                            }))
            if to_write:
                Commission.write(*to_write)
        return reconciliations

    @classmethod
    def delete(cls, reconciliations):
        pool = Pool()
        Commission = pool.get('commission')

        to_delete = []
        to_write = []

        line_ids = set()
        for reconciliation in reconciliations:
            line_ids |= {l.id for l in reconciliation.lines}

        for sub_ids in grouped_slice(line_ids):
            to_delete += Commission.search([
                    ('invoice_line', '=', None),
                    ('origin.invoice', 'in', sub_ids, 'account.move.line'),
                    ])
            to_cancel = Commission.search([
                    ('invoice_line', '!=', None),
                    ('origin.invoice', 'in', sub_ids, 'account.move.line'),
                    ])
            for commission in Commission.copy(to_cancel):
                commission.amount * -1
                to_write.extend(([commission], {
                            'amount': commission.amount * -1,
                            }))

        Commission.delete(to_delete)
        if to_write:
            Commission.write(*to_write)
        super(Reconciliation, cls).delete(reconciliations)
