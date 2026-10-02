import os.path
import re


def slugify(text):
    return re.sub(r"\W+", "-", text.lower()).strip("-")


def data_path(name):
    return os.path.join("data", name)
