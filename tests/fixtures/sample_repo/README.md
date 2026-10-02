# sample_repo (test fixture)

A tiny fake project whose dependency graph is known exactly. Not real code: it is
only ever *parsed*, never run.

## Expected internal edges (A → B means "A imports B")

| From | To | Import statement |
|---|---|---|
| `shop` | `shop.models` | `from .models import Product` (relative, inside `__init__.py`) |
| `shop.models` | `shop.utils` | `from shop.utils import slugify` |
| `shop.orders` | `shop.payments` | `from . import payments` (relative, imports a submodule) |
| `shop.orders` | `shop.models` | `from .models import Product` |
| `shop.payments` | `shop.orders` | `from shop.orders import Order` → **cycle with `shop.orders`** |
| `shop.payments` | `shop.utils` | `from shop import utils` (inside a function) |
| `shop.api.routes` | `shop.utils` | `import shop.utils` |
| `shop.api.routes` | `shop.orders` | `from ..orders import Order` (two dots) |
| `shop.api.routes` | `shop.models` | `from ..models import *` |
| `tests.test_orders` | `shop.orders` | `from shop.orders import Order` |

Plus one **type-only** edge `shop.models → shop.orders` (`if TYPE_CHECKING:`). It must
be ignored by analytics; counted, it would grow the cycle to `{models, orders, payments}`.

External: `json`, `os.path`, `re`, `typing` (stdlib); `requests`, `setuptools`, `pytest` (third-party).

## Traps for the parser

- `src/` has no `__init__.py` → it is a source root, so `src/shop/models.py` is `shop.models`.
- `broken.py` is Python 2 syntax → kept as module `broken` with a parse error.
- `scripts/my-tool/run.py` → `my-tool` isn't a valid name, so it's skipped.
- `build/` and `.github/` → never scanned.
- `shop/models.py` has an `if TYPE_CHECKING:` import → flagged `type_only`.
