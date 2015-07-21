# The COPYRIGHT file at the top level of this repository contains the full
# copyright notices and license terms.
from decimal import Decimal
from sql import Cast
from sql.functions import Substring, Position
from sql.conditionals import Coalesce

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

    from_invoice = fields.Function(fields.Many2One('account.invoice',
            'From invoice'),
        'get_from_invoice', searcher='search_from_invoice')

    @classmethod
    def _get_origin(cls):
        models = super(Commission, cls)._get_origin()
        models.append('account.move.line')
        return models

    def get_from_invoice(self, name):
        pool = Pool()
        Invoice = pool.get('account.invoice')
        InvoiceLine = pool.get('account.invoice.line')
        MoveLine = pool.get('account.move.line')
        if isinstance(self.origin, MoveLine):
            move = self.origin.move
            if isinstance(move.origin, Invoice):
                return move.origin.id
        if isinstance(self.origin, InvoiceLine):
            return self.origin.invoice.id

    @classmethod
    def search_from_invoice(cls, name, clause):
        pool = Pool()
        Invoice = pool.get('account.invoice')
        InvoiceLine = pool.get('account.invoice.line')
        MoveLine = pool.get('account.move.line')
        Move = pool.get('account.move')

        table = cls.__table__()
        invoice_line = InvoiceLine.__table__()
        move_line = MoveLine.__table__()
        move = Move.__table__()
        move_invoice = Cast(Substring(move.origin,
                Position(',', move.origin) + 1), Invoice.id.sql_type().base)
        Operator = fields.SQL_OPERATORS[clause[1]]

        query = table.join(invoice_line, type_='LEFT', condition=((Cast(
                    Substring(table.origin, Position(',', table.origin) + 1),
                InvoiceLine.id.sql_type().base) == invoice_line.id)
                & table.origin.ilike('account.invoice.line,%'))).join(
                    move_line, type_='LEFT', condition=((Cast(Substring(
                                table.origin, Position(',', table.origin) + 1),
                Move.id.sql_type().base) == move_line.id)
                & table.origin.ilike('account.move.line,%'))).join(move,
                    type_='LEFT', condition=(move.id == move_line.move)
                    & move.origin.ilike('account.invoice,%')).select(
                        table.id,
                        where=Operator(Coalesce(invoice_line.id,
                                move_invoice), clause[2]))
        return [('id', 'in', query)]


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
                    ('origin.id', 'in', sub_ids, 'account.move.line'),
                    ])
            to_cancel = Commission.search([
                    ('invoice_line', '!=', None),
                    ('origin.id', 'in', sub_ids, 'account.move.line'),
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
