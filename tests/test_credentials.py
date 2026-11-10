from src import credential_store


def test_opt_in_credentials_round_trip_and_removal(monkeypatch):
    entries = {}

    class MemoryBackend:
        def get_password(self, service, account):
            return entries.get((service, account))

        def set_password(self, service, account, value):
            entries[(service, account)] = value

        def delete_password(self, service, account):
            del entries[(service, account)]

    monkeypatch.setattr(credential_store, '_windows_keyring', lambda: MemoryBackend())
    credentials = {'vendor': 'A123', 'access': 'access', 'secret': 'secret'}
    assert credential_store.load_credentials() is None
    credential_store.save_credentials(credentials)
    assert credential_store.load_credentials() == credentials
    credential_store.delete_credentials()
    assert credential_store.load_credentials() is None
