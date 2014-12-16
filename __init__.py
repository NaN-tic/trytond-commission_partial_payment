# The COPYRIGHT file at the top level of this repository contains the full
# copyright notices and license terms.
from trytond.pool import Pool
from .commission import *


def register():
    Pool.register(
        Plan,
        Commission,
        Invoice,
        Reconciliation,
        module='commission_partial_payment', type_='model')
