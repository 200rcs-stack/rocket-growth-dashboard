"""Opt-in storage in the current Windows user's Credential Locker."""
import json

import keyring


SERVICE = 'Rocket Desk Coupang Open API'
ACCOUNT = 'active'


def _windows_keyring():
    backend = keyring.get_keyring()
    if not type(backend).__module__.startswith('keyring.backends.Windows'):
        raise RuntimeError('Windows 자격 증명 보관소를 사용할 수 없어 키를 저장하지 않았습니다.')
    return backend


def load_credentials():
    backend = _windows_keyring()
    raw = backend.get_password(SERVICE, ACCOUNT)
    if not raw:
        return None
    try:
        data = json.loads(raw)
        if all(isinstance(data.get(field), str) and data[field] for field in ('vendor', 'access', 'secret')):
            return {field: data[field] for field in ('vendor', 'access', 'secret')}
    except (ValueError, TypeError, AttributeError):
        pass
    raise RuntimeError('저장된 API 키 형식을 읽을 수 없습니다. API 연결 화면에서 다시 연결해 주세요.')


def save_credentials(credentials):
    backend = _windows_keyring()
    if not all(isinstance(credentials.get(field), str) and credentials[field] for field in ('vendor', 'access', 'secret')):
        raise ValueError('판매자 ID, Access Key, Secret Key를 확인해 주세요.')
    backend.set_password(SERVICE, ACCOUNT, json.dumps(credentials, ensure_ascii=False))


def delete_credentials():
    backend = _windows_keyring()
    if backend.get_password(SERVICE, ACCOUNT):
        backend.delete_password(SERVICE, ACCOUNT)
