import inspect
import os
import shutil
import sys
import unittest
import yaml
try:
    from unittest.mock import patch, Mock
except ImportError:
    try:
        from mock import patch, Mock
    except ImportError:
        exit("mock not found. Run: `pip install mock`")

import gnupg


__file__ = os.path.relpath(inspect.getsourcefile(lambda _: None))

TEST_DIR = os.path.join(os.path.dirname(os.path.relpath(__file__)))
TEST_DATA_DIR = os.path.join(TEST_DIR, "data")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.relpath(__file__))))
import pysswords
from pysswords.db import Database


def mock_create_keyring(path, *args, **kwargs):
    """Import key.asc instead of generating new key
    passphrase used to create the key was 'dummy_database'"""
    keyring_path = os.path.join(path, ".keys")
    gpg = gnupg.GPG(homedir=keyring_path)
    with open(os.path.join(TEST_DATA_DIR, "key.asc")) as keyfile:
        gpg.import_keys(keyfile.read())
    return gpg.list_keys()[0]


def mock_gen_key(self, key_input):
    return mock_create_keyring(self.homedir)


def some_credential(**kwargs):
    return pysswords.db.Credential(
        name=kwargs.get("name", "example.com"),
        login=kwargs.get("login", "john.doe"),
        password=kwargs.get("password", "--BEGIN GPG-- X --END GPG--"),
        comment=kwargs.get("comment", "Some comments"),
    )


# @patch("pysswords.crypt.create_keyring", new=mock_create_keyring)
class CryptTests(unittest.TestCase):

    def setUp(self):
        self.path = os.path.join(TEST_DATA_DIR, "database")
        self.passphrase = "dummy_passphrase"
        self.cleanup()

    def tearDown(self):
        self.cleanup()

    def cleanup(self):
        if os.path.exists(self.path):
            shutil.rmtree(self.path)

    @patch("pysswords.crypt.create_keyring", new=mock_create_keyring)
    def test_create_keyring_adds_gpg_keys_to_path(self):
        pysswords.crypt.create_keyring(self.path, self.passphrase)
        pubring = os.path.join(self.path, ".keys", "pubring.gpg")
        secring = os.path.join(self.path, ".keys", "secring.gpg")
        self.assertTrue(os.path.isfile(pubring))
        self.assertTrue(os.path.isfile(secring))

    @patch("pysswords.crypt.create_keyring", new=mock_create_keyring)
    def test_create_keyring_adds_key_to_keyring(self):
        database = Database(self.path)
        pysswords.crypt.create_keyring(self.path, self.passphrase)
        gpg = gnupg.GPG(homedir=database.keys_path)
        self.assertEqual(1, len(gpg.list_keys()))

    @patch("pysswords.crypt.gnupg.GPG.gen_key", new=mock_gen_key)
    def test_generate_keys_return_valid_key(self):
        key = pysswords.crypt.generate_keys(self.path, self.passphrase)
        self.assertIsNotNone(key)
        self.assertEqual(key["fingerprint"],
                         '0927E8F7C7794683AFABDED698894B2D11886DF4')

    def test_generate_key_input_returns_batch_string_with_passphrase(self):
        batch = pysswords.crypt.generate_key_input(self.path, self.passphrase)
        self.assertIn("\nPassphrase: {}".format(self.passphrase), batch)

    def test_create_keyring_generate_keys(self):
        self.cleanup()
        with patch("pysswords.crypt.generate_keys") as mocked_generate:
            pysswords.crypt.create_keyring(self.path, self.passphrase)
            self.assertTrue(mocked_generate.called)


@patch("pysswords.db.database.create_keyring", new=mock_create_keyring)
class DatabaseTests(unittest.TestCase):

    def setUp(self):
        self.path = os.path.join(TEST_DATA_DIR, "database")
        self.passphrase = "dummy_passphrase"
        self.cleanup()

    def tearDown(self):
        self.cleanup()

    def cleanup(self):
        if os.path.exists(self.path):
            shutil.rmtree(self.path)

    def test_create_makedirs_at_path(self):
        test_path = os.path.join(self.path, "creation")
        if os.path.exists(self.path):
            shutil.rmtree(self.path)
        pysswords.db.Database.create(test_path, self.passphrase)
        self.assertTrue(os.path.exists(test_path))

    def test_create_keyring(self):
        database = Database.create(self.path, self.passphrase)
        self.assertIsInstance(database, pysswords.db.Database)
        self.assertTrue(len(database.gpg.list_keys()) == 1)

    def test_keys_path_returns_database_path_joined_with_dot_keys(self):
        database = Database.create(self.path, self.passphrase)
        keys_path = database.keys_path
        self.assertEqual(keys_path, os.path.join(self.path, ".keys"))

    def test_add_credential_make_dir_in_dbpath_with_credential_name(self):
        database = Database.create(self.path, self.passphrase)
        database.add(some_credential())
        credential_dir = os.path.join(self.path, some_credential().name)
        self.assertTrue(os.path.exists(credential_dir))
        self.assertTrue(os.path.isdir(credential_dir))

    def test_add_credential_createas_pyssword_file_named_after_login(self):
        database = Database.create(self.path, self.passphrase)
        credential = some_credential()
        database.add(credential)
        credential_dir = os.path.join(self.path, credential.name)
        credential_filename = "{}.pyssword".format(credential.login)
        credential_file = os.path.join(credential_dir, credential_filename)
        self.assertTrue(os.path.isfile(credential_file))
        with open(credential_file) as f:
            self.assertEqual(yaml.load(f.read()), credential)

    def test_add_credential_creates_dir_when_credential_name_is_a_dir(self):
        database = Database.create(self.path, self.passphrase)
        credential = some_credential(name="emails/misc/example.com")
        emails_dir = os.path.join(self.path, "emails")
        misc_dir = os.path.join(emails_dir, "misc")
        database.add(credential)
        self.assertTrue(os.path.isdir(emails_dir))
        self.assertTrue(os.path.isdir(misc_dir))

    def test_add_credential_returns_credential_path(self):
        database = Database.create(self.path, self.passphrase)
        credential = some_credential()
        credential_path = database.add(credential)
        expected_path = os.path.join(
            self.path,
            os.path.basename(credential.name),
            "{}.pyssword".format(credential.login)
        )
        self.assertEqual(credential_path, expected_path)

    def test_gpg_returns_valid_gnupg_gpg_object(self):
        database = Database.create(self.path, self.passphrase)
        gpg = database.gpg
        self.assertIsInstance(gpg, pysswords.db.database.gnupg.GPG)

    def test_credentials_returns_a_list_of_all_added_credentials(self):
        database = Database.create(self.path, self.passphrase)
        database.add(some_credential(name="example.com"))
        database.add(some_credential(name="archive.org"))
        credentials = database.credentials
        self.assertIsInstance(credentials, list)
        self.assertEqual(2, len(credentials))
        for credential in credentials:
            self.assertIsInstance(credential, pysswords.db.Credential)

    def test_add_repeated_credential_without_overwrite_on_raises_error(self):
        database = Database.create(self.path, self.passphrase)
        credential = some_credential()
        database.add(credential)
        with self.assertRaises(pysswords.db.CredentialExistsError):
            database.add(credential)

    def test_remove_deletes_pysswords_file(self):
        database = Database.create(self.path, self.passphrase)
        credential = some_credential()
        credential_path = pysswords.db.credential.expandpath(
            self.path,
            credential)
        database.add(credential)
        self.assertTrue(os.path.isfile(credential_path))
        database.remove(credential)
        self.assertFalse(os.path.isfile(credential_path))

    def test_remove_deletes_pyssword_dir_if_empty_after_deletion(self):
        database = Database.create(self.path, self.passphrase)
        credential = some_credential()
        credential_path = pysswords.db.credential.expandpath(
            self.path,
            credential)

        database.add(credential)
        self.assertTrue(os.path.exists(os.path.dirname(credential_path)))
        database.remove(credential)
        self.assertFalse(os.path.exists(os.path.dirname(credential_path)))

    def test_get_credential_by_name_returns_expected_credential(self):
        database = Database.create(self.path, self.passphrase)
        credential = some_credential(name="example.com")
        database.add(credential)
        found = database.credential(name=credential.name)

        self.assertIsInstance(found, pysswords.db.Credential)
        self.assertEqual(found, credential)

    def test_search_database_returns_list_with_matched_credentials(self):
        database = Database.create(self.path, self.passphrase)
        database.add(some_credential(name="example.com"))
        database.add(some_credential(name="github.com"))
        database.add(some_credential(name="twitter.com"))

        self.assertEqual(len(database.search("it")), 2)
        self.assertEqual(len(database.search("github")), 1)
        self.assertEqual(len(database.search("not there")), 0)


class CredentialTests(unittest.TestCase):

    def setUp(self):
        self.path = os.path.join(TEST_DATA_DIR, "database")
        self.cleanup()

    def tearDown(self):
        self.cleanup()

    def cleanup(self):
        if os.path.exists(self.path):
            shutil.rmtree(self.path)

    def test_credential_expandpath_returns_expected_path_to_credential(self):
        credential = some_credential()
        credential_path = pysswords.db.credential.expandpath(
            self.path,
            credential
        )
        expected_path = os.path.join(
            self.path,
            os.path.basename(credential.name),
            "{}.pyssword".format(credential.login)
        )
        self.assertEqual(credential_path, expected_path)

    def test_credential_content_returns_yaml_content_parseable_to_dict(self):
        content = pysswords.db.credential.content(some_credential())
        self.assertEqual(yaml.load(content), some_credential())


class UtilsTests(unittest.TestCase):

    def test_which_handle_windows_exe_extension_for_executables(self):
        with patch("pysswords.utils.os") as mocker:
            mocker.name = "nt"
            mocker.environ = {"PATH": "/"}
            mocker.pathsep = ":"
            mocked_join = Mock()
            mocker.path.join = mocked_join
            pysswords.utils.which("python")
            mocked_join.assert_any_call("/", "python.exe")


if __name__ == "__main__":
    if sys.version_info >= (3,):
        unittest.main(warnings=False)
    else:
        unittest.main()
