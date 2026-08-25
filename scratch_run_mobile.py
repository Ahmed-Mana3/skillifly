import os
import sys
import unittest

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "skillifly.settings")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import scratch_e2e_nav  # noqa: E402

if __name__ == "__main__":
    loader = unittest.defaultTestLoader
    suite = loader.loadTestsFromName(
        "BuilderNavigationE2E.test_mobile_viewport_navigation_and_dirty_state",
        scratch_e2e_nav,
    )
    try:
        result = unittest.TextTestRunner(verbosity=2).run(suite)
    finally:
        try:
            scratch_e2e_nav.runner.teardown_databases(scratch_e2e_nav.old_config)
            from django.test.utils import teardown_test_environment

            teardown_test_environment()
        except Exception as e:
            print("[cleanup]", e)
    sys.exit(0 if result.wasSuccessful() else 1)
