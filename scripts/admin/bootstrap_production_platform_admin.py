"""Administrative entrypoint for the canonical one-time production bootstrap.

All domain and persistence authority lives in kordena_fiscal.runtime.production_first_admin.
"""

from kordena_fiscal.runtime.production_first_admin import main

if __name__ == "__main__":
    raise SystemExit(main())
