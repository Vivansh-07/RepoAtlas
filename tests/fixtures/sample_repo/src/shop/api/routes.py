import requests

import shop.utils
from ..models import *
from ..orders import Order


def create_order(name):
    order = Order(Product(name))
    requests.post("https://example.com/orders", json={"slug": shop.utils.slugify(name)})
    return order
