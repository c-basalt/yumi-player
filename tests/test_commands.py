import unittest
import sys
from pathlib import Path

# Add project root to Python path
project_root = Path(__file__).parent.parent
sys.path.append(str(project_root))

from backend.player.commands import (  # noqa: E402
    PausedCmd, ShowEventCmd, NextCmd, SeekCmd,
    ProgressCmd, CancelCmd, StatusCmd,
    BaseEvent, player_commands, SetIsFallbackCmd, UnsetIsFallbackCmd,
    MoveToEndCmd, MoveToTopCmd, MoveDownCmd, VolumeReportCmd,
)


class TestCommands(unittest.TestCase):
    def test_allowed_value_types(self):
        """Test that allowed_value_type returns correct types for each command"""
        self.assertEqual(PausedCmd.allowed_value_type(), bool)
        self.assertEqual(ShowEventCmd.allowed_value_type(), BaseEvent)
        self.assertEqual(NextCmd.allowed_value_type(), int)
        self.assertEqual(SeekCmd.allowed_value_type(), int)
        self.assertEqual(ProgressCmd.allowed_value_type(), int)
        self.assertEqual(CancelCmd.allowed_value_type(), int)
        self.assertEqual(StatusCmd.allowed_value_type(), type(None))
        self.assertEqual(SetIsFallbackCmd.allowed_value_type(), int)
        self.assertEqual(UnsetIsFallbackCmd.allowed_value_type(), int)
        self.assertEqual(MoveToEndCmd.allowed_value_type(), int)
        self.assertEqual(MoveToTopCmd.allowed_value_type(), int)
        self.assertEqual(MoveDownCmd.allowed_value_type(), int)
        self.assertEqual(VolumeReportCmd.allowed_value_type(), (float, int))

    def test_valid_command_values(self):
        """Test that commands accept valid values"""
        PausedCmd(True)
        PausedCmd(False)
        NextCmd(1)
        SeekCmd(100)
        ProgressCmd(50)
        CancelCmd(2)
        StatusCmd(None)
        SetIsFallbackCmd(3)
        UnsetIsFallbackCmd(4)
        MoveToEndCmd(5)
        MoveToTopCmd(6)
        MoveDownCmd(7)
        VolumeReportCmd(100)
        VolumeReportCmd(1.0)

    def test_invalid_command_values(self):
        """Test that commands reject invalid values"""
        with self.assertRaises(ValueError):
            PausedCmd("True")  # type: ignore

        with self.assertRaises(ValueError):
            NextCmd("1")  # type: ignore

        with self.assertRaises(ValueError):
            SeekCmd(3.14)  # type: ignore

        with self.assertRaises(ValueError):
            ProgressCmd("50")  # type: ignore

        with self.assertRaises(ValueError):
            CancelCmd(None)  # type: ignore

        with self.assertRaises(ValueError):
            StatusCmd(False)  # type: ignore

        with self.assertRaises(ValueError):
            MoveToEndCmd(None)  # type: ignore

        with self.assertRaises(ValueError):
            MoveToTopCmd(None)  # type: ignore

        with self.assertRaises(ValueError):
            MoveDownCmd(None)  # type: ignore

        with self.assertRaises(ValueError):
            VolumeReportCmd('a')  # type: ignore

    def test_player_commands_registration(self):
        """Test that all imported commands are properly registered in player_commands"""
        expected_commands = {
            'paused': PausedCmd,
            'show-event': ShowEventCmd,
            'next': NextCmd,
            'seek': SeekCmd,
            'progress': ProgressCmd,
            'cancel': CancelCmd,
            'status': StatusCmd,
            'set-is-fallback': SetIsFallbackCmd,
            'unset-is-fallback': UnsetIsFallbackCmd,
            'move-to-end': MoveToEndCmd,
            'move-to-top': MoveToTopCmd,
            'move-down': MoveDownCmd,
            'volume-report': VolumeReportCmd
        }

        # Check that all expected commands are registered
        for cmd_key, cmd_class in expected_commands.items():
            self.assertIn(cmd_key, player_commands)
            self.assertEqual(player_commands[cmd_key], cmd_class)

        # Check that there aren't any extra commands registered
        self.assertEqual(set(player_commands.keys()), set(expected_commands.keys()))


if __name__ == '__main__':
    unittest.main()
