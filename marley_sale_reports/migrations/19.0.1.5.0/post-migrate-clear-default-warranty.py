# -*- coding: utf-8 -*-
"""Remove the auto-applied default warranty text.

Previously product.template.warranty_terms defaulted to a fixed string and the
sale order had the same fallback, so warranty printed on every quotation even
when nobody set it. Per the client's request, warranty must print ONLY when it
is explicitly filled on a product. This clears the exact auto-default from
existing products and orders — any *custom* warranty (text != the default) is
left untouched.
"""
import logging

_logger = logging.getLogger(__name__)

DEFAULT = ('5 Years warranty on Mechanical items & '
           '1 year OEM warranty on Motors & VFD Drive')


def migrate(cr, version):
    cr.execute(
        "UPDATE product_template SET warranty_terms = NULL WHERE warranty_terms = %s",
        (DEFAULT,),
    )
    products = cr.rowcount
    cr.execute(
        "UPDATE sale_order SET warranty_terms = NULL WHERE warranty_terms = %s",
        (DEFAULT,),
    )
    orders = cr.rowcount
    _logger.info(
        "[MIGRATE 1.5.0] Cleared default warranty from %d product(s) and %d order(s).",
        products, orders,
    )
