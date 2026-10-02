from . import payments
from .models import Product


class Order:
    def __init__(self, product: Product):
        self.product = product

    def pay(self):
        return payments.charge(self)
