import unittest

from hilorama_desktop.config import is_dev_bypass_allowed


class DevBypassGuardTest(unittest.TestCase):
    def test_bypass_denied_when_frozen(self):
        self.assertFalse(
            is_dev_bypass_allowed(
                env="development",
                build_channel="development",
                requested=True,
                frozen=True,
            )
        )

    def test_bypass_denied_in_production_env(self):
        self.assertFalse(
            is_dev_bypass_allowed(
                env="production",
                build_channel="development",
                requested=True,
                frozen=False,
            )
        )

    def test_bypass_denied_in_production_channel(self):
        self.assertFalse(
            is_dev_bypass_allowed(
                env="development",
                build_channel="production",
                requested=True,
                frozen=False,
            )
        )

    def test_bypass_allowed_only_for_local_development(self):
        self.assertTrue(
            is_dev_bypass_allowed(
                env="development",
                build_channel="development",
                requested=True,
                frozen=False,
            )
        )


if __name__ == "__main__":
    unittest.main()
