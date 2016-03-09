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
from trytond.transaction import Transaction

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
        ids = [l.id for l in self.lines_to_pay + self.payment_lines]
        return [x.id for x in Commission.search([
                    ('origin.id', 'in', ids, 'account.move.line'),
                    ])]

    @classmethod
    def create_commissions(cls, invoices):
        non_partial_invoices = []
        for invoice in invoices:
            if (invoice.agent and invoice.agent.plan and
                    invoice.agent.plan.commission_method == 'partial_payment'):
                continue
            non_partial_invoices.append(invoice)
        # Only create commissions for non partial invoices
        return super(Invoice, cls).create_commissions(non_partial_invoices)

    def _get_partial_commission_amount(self, amount, pattern=None):
        if not self.agent or not self.agent.plan:
            return
        return self.agent.plan.compute(amount, None, pattern=pattern)

    def _get_partial_commission(self, amount, date):
        'Returns the partial comission for the invoice for amount'
        pool = Pool()
        Commission = pool.get('commission')
        commission = Commission()
        commission.agent = self.agent
        commission.product = self.agent.plan.commission_product
        commission.amount = amount.quantize(Decimal(str(
                    10 ** -Commission.amount.digits[1])))
        commission.date = date
        return commission

    def compute_untaxed_amount(self, amount):
        '''Apply a ratio to the paid amount in order to extract its untaxed
        amount so we can correctly compute the commission amount'''
        return amount * (self.untaxed_amount / self.total_amount)

    @classmethod
    def write(cls, *args):
        actions = iter(args)
        super(Invoice, cls).write(*args)
        payment_invoices = []
        for invoices, values in zip(actions, actions):
            if set(values) & set(['payment_lines']):
                payment_invoices.extend(invoices)
        if payment_invoices:
            cls.create_partial_commissions(payment_invoices)

    @classmethod
    def create_partial_commissions(cls, invoices):
        pool = Pool()
        Commission = pool.get('commission')
        commissions = []
        for invoice in invoices:
            origins = set([str(x.origin) for x in invoice.commissions])
            for line in invoice.payment_lines:
                if line.reconciliation:
                    continue
                if str(line) not in origins:
                    line_amount = line.credit - line.debit
                    lines, remainder = invoice.get_reconcile_lines_for_amount(
                        line_amount)
                    # Don't create commission if line can be reconcicled
                    if (any(l.debit - l.credit == line_amount for l in lines)
                            or remainder == line_amount):
                        continue
                    amount = invoice._get_partial_commission_amount(
                        line_amount)
                    if not amount:
                        continue
                    amount = invoice.compute_untaxed_amount(amount)
                    commission = invoice._get_partial_commission(amount,
                        line.date)
                    commission.origin = str(line)
                    commissions.append(commission)
        if commissions:
            Commission.create([c._save_values for c in commissions])


class Reconciliation:
    __name__ = 'account.move.reconciliation'

    @classmethod
    def create(cls, vlist):
        pool = Pool()
        Commission = pool.get('commission')
        Invoice = pool.get('account.invoice')

        reconciliations = super(Reconciliation, cls).create(vlist)

        invoices_move_lines = set()
        for reconciliation in reconciliations:
            for line in reconciliation.lines:
                if isinstance(line.move.origin, Invoice):
                    invoices_move_lines.add((line.move.origin, line))

        commissions = []
        for invoice, line in invoices_move_lines:
            if str(line) in (str(c.origin) for c in invoice.commissions):
                continue
            if (not invoice.agent or not invoice.agent.plan or
                    invoice.agent.plan.commission_method != 'partial_payment'):
                continue

            commission_amount = Decimal(0)
            for commission in invoice.commissions:
                if not commission.date:
                    continue
                commission_amount += commission.amount
            paid_amount = line.debit - line.credit
            for move_line in invoice.move.lines:
                paid_amount += (move_line.debit - move_line.credit)
            if invoice.type == 'out_credit_note':
                paid_amount *= -1
            # Apply a ratio to the paid amount in order to extract its
            # untaxed amount so we can correctly compute the commission amount
            paid_amount = invoice.compute_untaxed_amount(paid_amount)
            digits = invoice.currency_digits

            merited_amount = invoice._get_partial_commission_amount(
                paid_amount)
            if not merited_amount:
                continue
            merited_amount = merited_amount.quantize(
                Decimal(str(10 ** -digits)))
            commission_amount = commission_amount.quantize(
                Decimal(str(10 ** -digits)))
            amount = merited_amount - commission_amount
            if amount:
                date = max([l.date for l in line.reconciliation.lines])
                commission = invoice._get_partial_commission(merited_amount,
                    date)
                commission.origin = str(line)
                commissions.append(commission)
        if commissions:
            with Transaction().set_context(_check_access=False):
                Commission.create([x._save_values for x in commissions])
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
            sub_ids = list(sub_ids)
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
