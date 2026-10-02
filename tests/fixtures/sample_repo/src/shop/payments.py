from shop.orders import Order  # orders also imports payments: a circular dependency


def charge(order: Order):
    from shop import utils  # function-level import: still a dependency

    return f"charged {utils.slugify(order.product.slug)}"
