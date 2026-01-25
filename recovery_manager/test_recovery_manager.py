import unittest
from unittest.mock import MagicMock, patch

from recovery_manager import RecoveryManager


class TestRecoveryManager(unittest.TestCase):
    def setUp(self):
        self.recovery_manager = RecoveryManager()

    def test_get_most_recent_snapshot_id(self):
        alert = {"backup_version_id": "snapshot_123"}

        snapshot_id = self.recovery_manager.get_most_recent_snapshot_id(alert)

        self.assertEqual(snapshot_id, "snapshot_123")

    @patch("shutil.copytree")
    @patch("shutil.rmtree")
    @patch("os.path.exists")
    def test_recover_snapshot(self, mock_exists, mock_rmtree, mock_copytree):
        snapshot_id = "snapshot_001"
        snapshot_path = f"{self.recovery_manager.base_snapshot_path}/{snapshot_id}"

        mock_exists.return_value = True

        self.recovery_manager.recover_snapshot(snapshot_id)

        mock_exists.assert_called_once_with(self.recovery_manager.destination_path)
        mock_rmtree.assert_called_once_with(self.recovery_manager.destination_path)
        mock_copytree.assert_called_once_with(snapshot_path, self.recovery_manager.destination_path)

    def test_run_recovery_calls_recover_snapshot(self):
        self.recovery_manager.get_most_recent_snapshot_id = MagicMock(return_value="snapshot_007")
        self.recovery_manager.recover_snapshot = MagicMock()

        alert = {"backup_version_id": "snapshot_007"}

        self.recovery_manager.run_recovery(alert)

        self.recovery_manager.get_most_recent_snapshot_id.assert_called_once_with(alert)
        self.recovery_manager.recover_snapshot.assert_called_once_with("snapshot_007")

    @patch("time.sleep", return_value=None)
    def test_main_triggers_recovery(self, mock_sleep):
        self.recovery_manager.redis_client = MagicMock()
        self.recovery_manager.run_recovery = MagicMock()

        alert_data = {"recommended_action": "ISOLATE_NODE_AND_INITIATE_RECOVERY", "backup_version_id": "snapshot_999"}

        self.recovery_manager.redis_client.xread.side_effect = [
            [("ransomware_alerts", [("1-0", alert_data)])],
            KeyboardInterrupt,
        ]

        self.recovery_manager.redis_client.xdel = MagicMock()

        self.recovery_manager.main()

        self.recovery_manager.run_recovery.assert_called_once_with(alert_data)
        self.recovery_manager.redis_client.xdel.assert_called_once_with(self.recovery_manager.input_stream, "1-0")

    @patch("time.sleep", return_value=None)
    def test_main_triggers_recovery(self, mock_sleep):
        self.recovery_manager.redis_client = MagicMock()
        self.recovery_manager.run_recovery = MagicMock()

        alert_data = {"recommended_action": "ISOLATE_NODE_AND_INITIATE_RECOVERY", "backup_version_id": "snapshot_999"}

        self.recovery_manager.redis_client.xread.side_effect = [
            [("ransomware_alerts", [("1-0", alert_data)])],
            KeyboardInterrupt,
        ]

        self.recovery_manager.redis_client.xdel = MagicMock()

        self.recovery_manager.main()

        self.recovery_manager.run_recovery.assert_called_once_with(alert_data)
        self.recovery_manager.redis_client.xdel.assert_called_once_with(self.recovery_manager.input_stream, "1-0")


# python -m unittest test_recovery_manager.py -v
