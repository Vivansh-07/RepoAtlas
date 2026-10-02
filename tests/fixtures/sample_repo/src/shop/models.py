import json
from typing import TYPE_CHECKING

from shop.utils import slugify

if TYPE_CHECKING:
    # Type-only: never runs, so it does NOT close a cycle models -> orders -> models.
    from shop.orders import Order


class Product:
    def __init__(self, name):
        self.slug = slugify(name)

    def to_json(self):
        return json.dumps({"slug": self.slug})

    def add_to(self, order: "Order"):
        order.product = self
