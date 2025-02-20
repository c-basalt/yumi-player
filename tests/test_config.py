import unittest
import json
import tempfile
import os
import sys
from pathlib import Path
import dataclasses
import typing
import logging

# Add project root to Python path
project_root = Path(__file__).parent.parent
sys.path.append(str(project_root))

# Disable logging for tests
logging.getLogger().disabled = True

from backend.config import DataConfig  # noqa: E402


@dataclasses.dataclass
class TestConfig(DataConfig):
    name: str = "default"
    count: int = 0
    enabled: bool = False
    value: float = 0.0
    items: tuple = dataclasses.field(default_factory=tuple)
    mixed_num: typing.Union[int, float] = 0
    mixed_status: typing.Union[str, bool] = False
    optional_str: typing.Optional[str] = None
    optional_num: typing.Optional[int] = None


@dataclasses.dataclass
class SubTestConfig(DataConfig):
    enabled: bool = False
    priority: int = 1
    name: str = "sub"
    scale: float = 1.0


@dataclasses.dataclass
class UnionTestConfig(DataConfig):
    # Union types
    number: typing.Union[int, float] = 0
    status: typing.Union[str, bool] = False
    # Optional types (Union[type, None])
    optional_str: typing.Optional[str] = None
    optional_num: typing.Optional[int] = None


class TestDataConfig(unittest.TestCase):
    def setUp(self):
        self.temp_file = tempfile.NamedTemporaryFile(mode='w', delete=False)
        json.dump({
            "name": "test",
            "count": 42,
            "enabled": True,
            "value": 3.14
        }, self.temp_file)
        self.config_path = self.temp_file.name
        self.temp_file.close()

    def tearDown(self):
        os.unlink(self.config_path)

    def load_json(self):
        with open(self.config_path, 'r') as f:
            return json.load(f)

    def test_root_config_loading(self):
        root_config = TestConfig.create_root(self.config_path)
        root_config.load_config()

        self.assertEqual(root_config.name, "test")
        self.assertEqual(root_config.count, 42)
        self.assertEqual(root_config.enabled, True)
        self.assertEqual(root_config.value, 3.14)

    def test_sub_config(self):
        root_config = TestConfig.create_root(self.config_path)
        sub_config = SubTestConfig.create_sub(root_config, "sub", name="sub")
        sub_config.save_config()
        saved_data = self.load_json()

        self.assertTrue("sub" in saved_data)
        self.assertEqual(saved_data["sub"]["name"], "sub")

        sub_config.priority = 100
        saved_data = self.load_json()
        self.assertEqual(saved_data["sub"]["priority"], 100)

    def test_list_handling(self):
        # Test with initial list data
        with open(self.config_path, 'w') as f:
            json.dump({
                "name": "test",
                "items": ["item1", "item2", "item3"]
            }, f)

        root_config = TestConfig.create_root(self.config_path)
        root_config.load_config()

        # Verify list was loaded correctly as tuple
        self.assertEqual(root_config.items, ("item1", "item2", "item3"))

        # Test tuple modification
        root_config.items = ("new1", "new2")
        saved_data = self.load_json()
        self.assertEqual(saved_data["items"], ["new1", "new2"])  # Saved as list in JSON

        # Test invalid type assignment
        root_config.items = "not_a_tuple"  # type: ignore
        saved_data = self.load_json()
        self.assertEqual(saved_data["items"], ["new1", "new2"])  # Should remain unchanged

    def test_empty_list(self):
        root_config = TestConfig.create_root(self.config_path)
        root_config.items = ()
        saved_data = self.load_json()
        self.assertEqual(saved_data["items"], [])


class TestSubConfig(unittest.TestCase):
    def setUp(self):
        self.temp_file = tempfile.NamedTemporaryFile(mode='w', delete=False)
        json.dump({
            "name": "test",
            "count": 42,
            "enabled": True,
            "value": 3.14,
            "sub": {
                "enabled": True,
                "priority": 5,
                "name": "sub",
                "scale": 1.0
            }
        }, self.temp_file)
        self.config_path = self.temp_file.name
        self.temp_file.close()

    def tearDown(self):
        os.unlink(self.config_path)

    def verify_json(self):
        with open(self.config_path, 'r') as f:
            return json.load(f)

    def test_sub_config_creation(self):
        root_config = TestConfig.create_root(self.config_path)
        sub_config = SubTestConfig.create_sub(root_config, "sub")
        sub_config.load_config()

        self.assertTrue(sub_config.enabled)
        self.assertEqual(sub_config.priority, 5)
        self.assertEqual(sub_config.name, "sub")
        self.assertEqual(sub_config.scale, 1.0)

    def test_sub_config_modification(self):
        root_config = TestConfig.create_root(self.config_path)
        sub_config = SubTestConfig.create_sub(root_config, "sub")

        sub_config.priority = 10
        sub_config.name = "modified"
        sub_config.scale = 2.0

        saved_data = self.verify_json()
        self.assertEqual(saved_data["sub"]["priority"], 10)
        self.assertEqual(saved_data["sub"]["name"], "modified")
        self.assertEqual(saved_data["sub"]["scale"], 2.0)


class TestDataConfigErrors(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.config_path = os.path.join(self.temp_dir, "config.json")

    def tearDown(self):
        if os.path.exists(self.temp_dir):
            import shutil
            shutil.rmtree(self.temp_dir)

    def test_no_file(self):
        # Test when file doesn't exist
        root_config = TestConfig.create_root(self.config_path)
        root_config.load_config()  # Should create with defaults

        self.assertEqual(root_config.name, "default")
        self.assertEqual(root_config.count, 0)
        self.assertEqual(root_config.enabled, False)
        self.assertEqual(root_config.value, 0.0)

        # Save the config to create the file
        root_config.save_config()

        # Now verify the saved file
        with open(self.config_path, 'r') as f:
            saved_data = json.load(f)
            self.assertEqual(saved_data["name"], "default")
            self.assertEqual(saved_data["count"], 0)
            self.assertEqual(saved_data["enabled"], False)
            self.assertEqual(saved_data["value"], 0.0)

    def test_empty_file(self):
        # Test with empty file
        with open(self.config_path, 'w') as f:
            f.write("")

        root_config = TestConfig.create_root(self.config_path)
        root_config.load_config()  # Should reset to defaults

        self.assertEqual(root_config.name, "default")
        self.assertEqual(root_config.count, 0)
        self.assertEqual(root_config.enabled, False)
        self.assertEqual(root_config.value, 0.0)

    def test_malformed_json(self):
        # Test with malformed JSON
        with open(self.config_path, 'w') as f:
            f.write("{\"name\": \"test\", \"count\": 42, ")  # Incomplete JSON

        root_config = TestConfig.create_root(self.config_path)
        root_config.load_config()  # Should reset to defaults

        self.assertEqual(root_config.name, "default")
        self.assertEqual(root_config.count, 0)
        self.assertEqual(root_config.enabled, False)
        self.assertEqual(root_config.value, 0.0)

    def test_partial_config(self):
        # Test with partial configuration
        with open(self.config_path, 'w') as f:
            json.dump({"name": "test"}, f)  # Only name field

        root_config = TestConfig.create_root(self.config_path)
        root_config.load_config()

        # Should keep the valid field and use defaults for others
        self.assertEqual(root_config.name, "test")
        self.assertEqual(root_config.count, 0)
        self.assertEqual(root_config.enabled, False)
        self.assertEqual(root_config.value, 0.0)

    def test_invalid_types(self):
        # Test with wrong types in JSON
        with open(self.config_path, 'w') as f:
            json.dump({
                "name": 123,  # Should be string
                "count": "42",  # Should be int
                "enabled": "True",  # Should be bool
                "value": "3.14"  # Should be float
            }, f)

        root_config = TestConfig.create_root(self.config_path)
        root_config.load_config()  # Should reset to defaults and filter invalid types

        self.assertEqual(root_config.name, "default")
        self.assertEqual(root_config.count, 0)
        self.assertEqual(root_config.enabled, False)
        self.assertEqual(root_config.value, 0.0)

    def test_partial_config_with_sub(self):
        # Write initial config
        initial_data = {
            'name': 'test',
            'sub': {
                'name': 'sub',
                'enabled': True,
                'priority': 1,
                'scale': 1.0
            }
        }
        with open(self.config_path, 'w') as f:
            json.dump(initial_data, f)

        # Create and load root config
        root_config = TestConfig.create_root(self.config_path)
        root_config.load_config()  # Load initial data

        # Create and load sub config before saving
        sub_config = SubTestConfig.create_sub(root_config, 'sub')
        sub_config.load_config()

        # Save after both configs are loaded
        root_config.save_config()

        # Verify the saved data includes all default values
        with open(self.config_path, 'r') as f:
            saved_data = json.load(f)

        expected_saved_data = {
            'name': 'test',
            'count': 0,
            'enabled': False,
            'value': 0.0,
            'items': [],
            'mixed_num': 0,
            'mixed_status': False,
            'optional_str': None,
            'optional_num': None,
            'sub': {
                'name': 'sub',
                'enabled': True,
                'priority': 1,
                'scale': 1.0
            }
        }

        # Convert both dictionaries to sorted string representation for comparison
        def normalize_dict(d):
            return json.dumps(d, sort_keys=True)

        self.assertEqual(
            normalize_dict(saved_data),
            normalize_dict(expected_saved_data),
            f"\nSaved data: {saved_data}\nExpected: {expected_saved_data}"
        )

    def test_type_validation_and_conversion(self):
        root_config = TestConfig.create_root(self.config_path)

        # Test basic types
        root_config.name = 123  # type: ignore
        self.assertEqual(root_config.name, "default")  # Should keep original value

        root_config.count = "not a number"  # type: ignore
        self.assertEqual(root_config.count, 0)  # Should keep original value

        # Test union types
        root_config.mixed_num = 42
        self.assertEqual(root_config.mixed_num, 42)
        root_config.mixed_num = 3.14
        self.assertEqual(root_config.mixed_num, 3.14)
        root_config.mixed_num = "invalid"  # type: ignore
        self.assertEqual(root_config.mixed_num, 3.14)  # Should keep previous value

        root_config.mixed_status = True
        self.assertEqual(root_config.mixed_status, True)
        root_config.mixed_status = "active"
        self.assertEqual(root_config.mixed_status, "active")
        root_config.mixed_status = 42  # type: ignore
        self.assertEqual(root_config.mixed_status, "active")  # Should keep previous value

        # Test optional types
        root_config.optional_str = "test"
        self.assertEqual(root_config.optional_str, "test")
        root_config.optional_str = None
        self.assertIsNone(root_config.optional_str)
        root_config.optional_str = 42  # type: ignore
        self.assertIsNone(root_config.optional_str)  # Should keep previous value

        # Test persistence
        root_config.save_config()
        new_config = TestConfig.create_root(self.config_path)
        new_config.load_config()
        self.assertEqual(new_config.mixed_num, 3.14)
        self.assertEqual(new_config.mixed_status, "active")
        self.assertIsNone(new_config.optional_str)

    def test_invalid_type_definitions(self):
        # Test with invalid type hints
        with self.assertRaises(ValueError):
            @dataclasses.dataclass
            class InvalidConfig(DataConfig):
                invalid_list: list = dataclasses.field(default_factory=list)
                invalid_union: typing.Union[str, list] = "default"
                invalid_optional: typing.Optional[dict] = None
            InvalidConfig()


class TestAdvancedTypeConfig(unittest.TestCase):
    def setUp(self):
        self.temp_file = tempfile.NamedTemporaryFile(mode='w', delete=False)
        self.config_path = self.temp_file.name
        self.temp_file.close()

    def tearDown(self):
        os.unlink(self.config_path)

    def test_union_types(self):
        # Initialize with default values
        config = UnionTestConfig.create_root(self.config_path)

        # Test number field (Union[int, float])
        config.number = 42
        self.assertEqual(config.number, 42)

        config.number = 3.14
        self.assertEqual(config.number, 3.14)

        # Invalid type should be ignored
        config.number = "123"  # type: ignore
        self.assertEqual(config.number, 3.14)  # Previous value retained

        # Test status field (Union[str, bool])
        config.status = True
        self.assertEqual(config.status, True)

        config.status = "active"
        self.assertEqual(config.status, "active")

        # Invalid type should be ignored
        config.status = 42  # type: ignore
        self.assertEqual(config.status, "active")  # Previous value retained

    def test_optional_types(self):
        config = UnionTestConfig.create_root(self.config_path)

        # Test optional string
        self.assertIsNone(config.optional_str)  # Default None

        config.optional_str = "test"
        self.assertEqual(config.optional_str, "test")

        config.optional_str = None
        self.assertIsNone(config.optional_str)

        # Invalid type should be ignored
        config.optional_str = 42  # type: ignore
        self.assertIsNone(config.optional_str)

        # Test optional number
        self.assertIsNone(config.optional_num)  # Default None

        config.optional_num = 42
        self.assertEqual(config.optional_num, 42)

        config.optional_num = None
        self.assertIsNone(config.optional_num)

        # Invalid type should be ignored
        config.optional_num = "42"  # type: ignore
        self.assertIsNone(config.optional_num)

    def test_union_type_persistence(self):
        # Test that union types are correctly saved and loaded
        config = UnionTestConfig.create_root(self.config_path)

        # Set some values
        config.number = 3.14
        config.status = "active"
        config.optional_str = "test"
        config.optional_num = 42

        # Save and create new instance
        config.save_config()
        new_config = UnionTestConfig.create_root(self.config_path)
        new_config.load_config()

        # Verify values
        self.assertEqual(new_config.number, 3.14)
        self.assertEqual(new_config.status, "active")
        self.assertEqual(new_config.optional_str, "test")
        self.assertEqual(new_config.optional_num, 42)

    def test_invalid_union_types(self):
        # Test that invalid union type definitions are caught
        with self.assertRaises(ValueError):
            @dataclasses.dataclass
            class InvalidUnionConfig(DataConfig):
                # Union with invalid type (list)
                invalid_union: typing.Union[str, list] = "default"

            InvalidUnionConfig()

        with self.assertRaises(ValueError):
            @dataclasses.dataclass
            class InvalidOptionalConfig(DataConfig):
                # Optional with invalid type (dict)
                invalid_optional: typing.Optional[dict] = None

            InvalidOptionalConfig()


if __name__ == '__main__':
    unittest.main()
