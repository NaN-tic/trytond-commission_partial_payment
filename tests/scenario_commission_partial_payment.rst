===================
Commission Scenario
===================

Imports::

    >>> import datetime
    >>> from dateutil.relativedelta import relativedelta
    >>> from decimal import Decimal
    >>> from proteus import config, Model, Wizard
    >>> today = datetime.date.today()
    >>> tomorrow = today + relativedelta(days=1)

Create database::

    >>> config = config.set_trytond()
    >>> config.pool.test = True

Install commission::

    >>> Module = Model.get('ir.module.module')
    >>> module, = Module.find([
    ...         ('name', '=', 'commission_partial_payment'),
    ...         ])
    >>> module.click('install')
    >>> Wizard('ir.module.module.install_upgrade').execute('upgrade')

Create company::

    >>> Currency = Model.get('currency.currency')
    >>> CurrencyRate = Model.get('currency.currency.rate')
    >>> currencies = Currency.find([('code', '=', 'USD')])
    >>> if not currencies:
    ...     currency = Currency(name='U.S. Dollar', symbol='$', code='USD',
    ...         rounding=Decimal('0.01'), mon_grouping='[3, 3, 0]',
    ...         mon_decimal_point='.', mon_thousands_sep=',')
    ...     currency.save()
    ...     CurrencyRate(date=today + relativedelta(month=1, day=1),
    ...         rate=Decimal('1.0'), currency=currency).save()
    ... else:
    ...     currency, = currencies
    >>> Company = Model.get('company.company')
    >>> Party = Model.get('party.party')
    >>> company_config = Wizard('company.company.config')
    >>> company_config.execute('company')
    >>> company = company_config.form
    >>> party = Party(name='Dunder Mifflin')
    >>> party.save()
    >>> company.party = party
    >>> company.currency = currency
    >>> company_config.execute('add')
    >>> company, = Company.find([])

Reload the context::

    >>> User = Model.get('res.user')
    >>> config._context = User.get_preferences(True, config.context)

Create fiscal year::

    >>> FiscalYear = Model.get('account.fiscalyear')
    >>> Sequence = Model.get('ir.sequence')
    >>> SequenceStrict = Model.get('ir.sequence.strict')
    >>> fiscalyear = FiscalYear(name=str(today.year))
    >>> fiscalyear.start_date = today + relativedelta(month=1, day=1)
    >>> fiscalyear.end_date = today + relativedelta(month=12, day=31)
    >>> fiscalyear.company = company
    >>> post_move_seq = Sequence(name=str(today.year), code='account.move',
    ...     company=company)
    >>> post_move_seq.save()
    >>> fiscalyear.post_move_sequence = post_move_seq
    >>> invoice_seq = SequenceStrict(name=str(today.year),
    ...     code='account.invoice', company=company)
    >>> invoice_seq.save()
    >>> fiscalyear.out_invoice_sequence = invoice_seq
    >>> fiscalyear.in_invoice_sequence = invoice_seq
    >>> fiscalyear.out_credit_note_sequence = invoice_seq
    >>> fiscalyear.in_credit_note_sequence = invoice_seq
    >>> fiscalyear.save()
    >>> fiscalyear.click('create_period')

Create chart of accounts::

    >>> AccountTemplate = Model.get('account.account.template')
    >>> Account = Model.get('account.account')
    >>> Journal = Model.get('account.journal')
    >>> account_template, = AccountTemplate.find([('parent', '=', None)])
    >>> create_chart = Wizard('account.create_chart')
    >>> create_chart.execute('account')
    >>> create_chart.form.account_template = account_template
    >>> create_chart.form.company = company
    >>> create_chart.execute('create_account')
    >>> receivable, = Account.find([
    ...         ('kind', '=', 'receivable'),
    ...         ('company', '=', company.id),
    ...         ])
    >>> payable, = Account.find([
    ...         ('kind', '=', 'payable'),
    ...         ('company', '=', company.id),
    ...         ])
    >>> revenue, = Account.find([
    ...         ('kind', '=', 'revenue'),
    ...         ('company', '=', company.id),
    ...         ])
    >>> expense, = Account.find([
    ...         ('kind', '=', 'expense'),
    ...         ('company', '=', company.id),
    ...         ])
    >>> create_chart.form.account_receivable = receivable
    >>> create_chart.form.account_payable = payable
    >>> create_chart.execute('create_properties')
    >>> cash, = Account.find([
    ...         ('kind', '=', 'other'),
    ...         ('name', '=', 'Main Cash'),
    ...         ('company', '=', company.id),
    ...         ])
    >>> cash_journal, = Journal.find([('type', '=', 'cash')])
    >>> cash_journal.credit_account = cash
    >>> cash_journal.debit_account = cash
    >>> cash_journal.save()
    >>> revenue_journal, = Journal.find([('type', '=', 'revenue')])
    >>> revenue_journal.update_posted = True
    >>> revenue_journal.save()
    >>> account_tax, = Account.find([
    ...         ('kind', '=', 'other'),
    ...         ('company', '=', company.id),
    ...         ('name', '=', 'Main Tax'),
    ...         ])

Create tax::

    >>> TaxCode = Model.get('account.tax.code')
    >>> Tax = Model.get('account.tax')
    >>> tax = Tax()
    >>> tax.name = 'Tax'
    >>> tax.description = 'Tax'
    >>> tax.type = 'percentage'
    >>> tax.rate = Decimal('.10')
    >>> tax.invoice_account = account_tax
    >>> tax.credit_note_account = account_tax
    >>> invoice_base_code = TaxCode(name='invoice base')
    >>> invoice_base_code.save()
    >>> tax.invoice_base_code = invoice_base_code
    >>> invoice_tax_code = TaxCode(name='invoice tax')
    >>> invoice_tax_code.save()
    >>> tax.invoice_tax_code = invoice_tax_code
    >>> credit_note_base_code = TaxCode(name='credit note base')
    >>> credit_note_base_code.save()
    >>> tax.credit_note_base_code = credit_note_base_code
    >>> credit_note_tax_code = TaxCode(name='credit note tax')
    >>> credit_note_tax_code.save()
    >>> tax.credit_note_tax_code = credit_note_tax_code
    >>> tax.save()

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
    >>> PaymentTermLine = Model.get('account.invoice.payment_term.line')
    >>> payment_term = PaymentTerm(name='50% direct 50% two days')
    >>> line = payment_term.lines.new()
    >>> line.type = 'percent'
    >>> line.percentage = Decimal('50.0')
    >>> line.days = 0
    >>> line = payment_term.lines.new()
    >>> line.type = 'remainder'
    >>> line.days = 10
    >>> payment_term.save()
    >>> direct_term = PaymentTerm(name='Direct Term')
    >>> line = direct_term.lines.new()
    >>> line.type = 'remainder'
    >>> line.days = 0
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
    >>> invoice.click('post')

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

Break the conciliation and check that the commission is deleted::

    >>> MoveLine = Model.get('account.move.line')
    >>> lines = MoveLine.find([('reconciliation', '!=', None)])
    >>> unreconcile_lines = Wizard('account.move.unreconcile_lines', lines)
    >>> invoice.reload()
    >>> len(invoice.commissions)
    0
    >>> reconcile_lines = Wizard('account.move.reconcile_lines', lines)
    >>> invoice.reload()
    >>> invoice.amount_to_pay
    Decimal('55.00')
    >>> due_commission, = invoice.commissions
    >>> due_commission.amount
    Decimal('5.0000')
    >>> due_commission.date == today
    True

Split the muturities in smaller pieces::

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
