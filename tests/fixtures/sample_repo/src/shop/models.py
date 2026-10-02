import json

from shop.utils import slugify


class Product:
    def __init__(self, name):
        self.slug = slugify(name)

    def to_json(self):
        return json.dumps({"slug": self.slug})
