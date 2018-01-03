===================
Commission Scenario
===================

Imports::

    >>> import datetime
    >>> from dateutil.relativedelta import relativedelta
    >>> from decimal import Decimal
    >>> from proteus import config, Model, Wizard
    >>> from trytond.modules.company.tests.tools import create_company, \
    ...     get_company
    >>> from trytond.modules.account.tests.tools import create_fiscalyear, \
    ...     create_chart, get_accounts, create_tax, set_tax_code
    >>> from trytond.modules.account_invoice.tests.tools import \
    ...     set_fiscalyear_invoice_sequences, create_payment_term
    >>> today = datetime.date.today()
    >>> tomorrow = today + relativedelta(days=1)

Create database::

    >>> config = config.set_trytond()
    >>> config.pool.test = True

Install commission::

    >>> Module = Model.get('ir.module')
    >>> module, = Module.find([
    ...         ('name', '=', 'commission_partial_payment'),
    ...         ])
    >>> module.click('install')
    >>> Wizard('ir.module.install_upgrade').execute('upgrade')

Create company::

    >>> _ = create_company()
    >>> company = get_company()

Create fiscal year::

    >>> fiscalyear = set_fiscalyear_invoice_sequences(
    ...     create_fiscalyear(company))
    >>> fiscalyear.click('create_period')
    >>> period = fiscalyear.periods[0]

Create chart of accounts::

    >>> _ = create_chart(company)
    >>> accounts = get_accounts(company)
    >>> receivable = accounts['receivable']
    >>> revenue = accounts['revenue']
    >>> expense = accounts['expense']
    >>> account_tax = accounts['tax']
    >>> account_cash = accounts['cash']

Create tax::

    >>> tax = set_tax_code(create_tax(Decimal('.10')))
    >>> tax.save()
    >>> invoice_base_code = tax.invoice_base_code
    >>> invoice_tax_code = tax.invoice_tax_code
    >>> credit_note_base_code = tax.credit_note_base_code
    >>> credit_note_tax_code = tax.credit_note_tax_code

Set Cash journal::

    >>> Journal = Model.get('account.journal')
    >>> cash_journal, = Journal.find([('type', '=', 'cash')])
    >>> cash_journal.credit_account = account_cash
    >>> cash_journal.debit_account = account_cash
    >>> cash_journal.save()

Allow cancelling revenuew journal moves::

    >>> revenue_journal, = Journal.find([('type', '=', 'revenue')])
    >>> revenue_journal.update_posted = True
    >>> revenue_journal.save()

Create customer::

    >>> Party = Model.get('party.party')
    >>> customer = Party(name='Customer')
    >>> customer.save()

Create commission product::

    >>> Uom = Model.get('product.uom')
    >>> Template = Model.get('product.template')
    >>> Product = Model.get('product.product')
    >>> unit, = Uom.find([('name', '=', 'Unit')])
    >>> commission_product = Product()
    >>> template = Template()
    >>> template.name = 'Commission'
    >>> template.default_uom = unit
    >>> template.type = 'service'
    >>> template.list_price = Decimal(0)
    >>> template.cost_price = Decimal(0)
    >>> template.account_expense = expense
    >>> template.account_revenue = revenue
    >>> template.save()
    >>> commission_product.template = template
    >>> commission_product.save()

Create commission plan::

    >>> Plan = Model.get('commission.plan')
    >>> plan = Plan(name='Plan')
    >>> plan.commission_product = commission_product
    >>> plan.commission_method = 'partial_payment'
    >>> line = plan.lines.new()
    >>> line.formula = 'amount * 0.1'
    >>> plan.save()

Create payment term::

    >>> PaymentTerm = Model.get('account.invoice.payment_term')
    >>> payment_term = PaymentTerm(name='50% Post 50% ten days')
    >>> line = payment_term.lines.new(type='percent', ratio=Decimal('.5'))
    >>> delta = line.relativedeltas.new(days=0)
    >>> line = payment_term.lines.new(type='remainder')
    >>> delta = line.relativedeltas.new(days=10)
    >>> payment_term.save()
    >>> direct_term = create_payment_term()
    >>> direct_term.save()

Create agent::

    >>> Agent = Model.get('commission.agent')
    >>> agent_party = Party(name='Agent')
    >>> agent_party.supplier_payment_term = payment_term
    >>> agent_party.save()
    >>> agent = Agent(party=agent_party)
    >>> agent.type_ = 'agent'
    >>> agent.plan = plan
    >>> agent.currency = company.currency
    >>> agent.save()

Create product sold::

    >>> product = Product()
    >>> template = Template()
    >>> template.name = 'Product'
    >>> template.default_uom = unit
    >>> template.type = 'service'
    >>> template.list_price = Decimal(100)
    >>> template.cost_price = Decimal(100)
    >>> template.account_expense = expense
    >>> template.account_revenue = revenue
    >>> template.customer_taxes.append(tax)
    >>> template.save()
    >>> product.template = template
    >>> product.save()

Create invoice::

    >>> Invoice = Model.get('account.invoice')
    >>> invoice = Invoice()
    >>> invoice.party = customer
    >>> invoice.payment_term = payment_term
    >>> invoice.agent = agent
    >>> line = invoice.lines.new()
    >>> line.product = product
    >>> line.quantity = 1
    >>> line.unit_price = Decimal(100)
    >>> invoice.click('post')
    >>> invoice.total_amount
    Decimal('110.00')

Pay the invoice partialy::

    >>> pay = Wizard('account.invoice.pay', [invoice])
    >>> pay.form.journal = cash_journal
    >>> pay.form.amount = Decimal('55.00')
    >>> pay.execute('choice')
    >>> invoice.reload()
    >>> invoice.amount_to_pay
    Decimal('55.00')
    >>> due_commission, = invoice.commissions
    >>> due_commission.amount
    Decimal('5.0000')
    >>> due_commission.date == today
    True

Split the maturities in smaller pieces::

    >>> invoice.move.click('draft')
    >>> line, = [l for l in invoice.move.lines if not l.reconciliation and
    ...     l.account == invoice.account]
    >>> line.debit = Decimal('22.00')
    >>> line.save()
    >>> line = invoice.move.lines.new()
    >>> line.debit = Decimal('33.00')
    >>> line.account = invoice.account
    >>> line.party = customer
    >>> line.maturity_date = tomorrow
    >>> invoice.move.click('post')

Pay the next maturity::

    >>> pay = Wizard('account.invoice.pay', [invoice])
    >>> pay.form.journal = cash_journal
    >>> pay.form.amount = Decimal('22.00')
    >>> pay.form.date = tomorrow
    >>> pay.execute('choice')
    >>> invoice.reload()
    >>> invoice.amount_to_pay
    Decimal('33.00')
    >>> _, due_commission = invoice.commissions
    >>> due_commission.amount
    Decimal('2.0000')
    >>> due_commission.date == tomorrow
    True

Pay the rest of the invoice::

    >>> pay = Wizard('account.invoice.pay', [invoice])
    >>> pay.form.journal = cash_journal
    >>> pay.form.amount = Decimal('33.00')
    >>> pay.form.date = tomorrow
    >>> pay.execute('choice')
    >>> invoice.reload()
    >>> invoice.amount_to_pay
    Decimal('0.0')
    >>> _, _, due_commission = invoice.commissions
    >>> due_commission.amount
    Decimal('3.0000')
    >>> due_commission.date == tomorrow
    True

Create a invoice for with direct payment term::

    >>> invoice = Invoice()
    >>> invoice.party = customer
    >>> invoice.payment_term = direct_term
    >>> invoice.agent = agent
    >>> line = invoice.lines.new()
    >>> line.product = product
    >>> line.quantity = 1
    >>> line.unit_price = Decimal('100.00')
    >>> invoice.click('post')

Pay the invoice partialy::

    >>> pay = Wizard('account.invoice.pay', [invoice])
    >>> pay.form.journal = cash_journal
    >>> pay.form.amount = Decimal('22.00')
    >>> pay.execute('choice')
    >>> pay.execute('pay')
    >>> invoice.reload()
    >>> invoice.amount_to_pay
    Decimal('88.00')
    >>> due_commission, = invoice.commissions
    >>> due_commission.amount
    Decimal('2.0000')
    >>> due_commission.date == today
    True

Pay another amount partialy::

    >>> pay = Wizard('account.invoice.pay', [invoice])
    >>> pay.form.journal = cash_journal
    >>> pay.form.amount = Decimal('11.00')
    >>> pay.execute('choice')
    >>> pay.execute('pay')
    >>> invoice.reload()
    >>> invoice.amount_to_pay
    Decimal('77.00')
    >>> _, due_commission, = invoice.commissions
    >>> due_commission.amount
    Decimal('1.0000')
    >>> due_commission.date == today
    True

Pay the rest of the invoice::

    >>> pay = Wizard('account.invoice.pay', [invoice])
    >>> pay.form.journal = cash_journal
    >>> pay.form.date = tomorrow
    >>> pay.execute('choice')
    >>> invoice.reload()
    >>> invoice.amount_to_pay
    Decimal('0.0')
    >>> _, _, due_commission = invoice.commissions
    >>> due_commission.amount
    Decimal('7.0000')
    >>> due_commission.date == tomorrow
    True

Asset all the commissions have been generated::

    >>> agent.reload()
    >>> agent.pending_amount
    Decimal('20.0000')

Create invoices from commissions::

    >>> commission_amount = sum([commission.amount for commission in invoice.commissions])
    >>> commission_amount == Decimal('10.0000')
    True

    >>> create_invoice = Wizard('commission.create_invoice')
    >>> create_invoice.form.from_ = None
    >>> create_invoice.form.to = None
    >>> create_invoice.execute('create_')
    >>> invoice.reload()
    >>> com1, com2, com3 = invoice.commissions
    >>> com1.invoice_state == 'invoiced'
    True

Delete a reconciliation::

    >>> Reconciliation = Model.get('account.move.reconciliation')
    >>> line1, line2, line3 = invoice.move.lines
    >>> reconciliation = line1.reconciliation
    >>> Reconciliation.delete([reconciliation])
    >>> agent.reload()
    >>> agent.pending_amount
    Decimal('-10.0000')
    >>> invoice.reload()
    >>> len(invoice.commissions) == 6
    True
    >>> invoice.reconciled
    False

Pay the invoice that was delete reconciliation::

    >>> pay = Wizard('account.invoice.pay', [invoice])
    >>> pay.form.journal = cash_journal
    >>> pay.form.amount = Decimal('110.00')
    >>> pay.execute('choice')
    >>> pay.execute('pay')
    >>> invoice.reload()
    >>> invoice.reconciled
    True
    >>> len(invoice.commissions) == 7
    True
    >>> commission_amount = sum([commission.amount for commission in invoice.commissions])
    >>> commission_amount == Decimal('10.0000')
    True
