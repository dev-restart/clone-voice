"""Credentials stay out of profile JSON and browser responses.

Keychain calls target this app's exact service/account only. No shell commands,
credential discovery, or automatic plaintext fallback are used.
"""
from __future__ import annotations

import ctypes as C
import hashlib
import os
import re
import sys
from pathlib import Path
from uuid import uuid4


class CredentialError(RuntimeError):
    pass


class ApiCredentialVault:
    def __init__(self, directory: Path):
        self.directory = directory
        scope = hashlib.sha256(str(directory.absolute()).encode()).hexdigest()[:20]
        self.service = f"kr.clonevoice.ai-api.{scope}"

    def _file(self, reference: str) -> Path:
        if not re.fullmatch(r"[a-f0-9]{32}", reference):
            raise CredentialError("API 키 참조가 올바르지 않습니다.")
        if self.directory.is_symlink():
            raise CredentialError("API 키 보관 폴더는 심볼릭 링크를 사용할 수 없습니다.")
        return self.directory / reference

    def put(self, secret: str, backend: str) -> str:
        reference = uuid4().hex
        if backend == "keychain":
            self._keychain("add", reference, secret)
        elif backend == "private_file":
            path = self._file(reference)
            self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
            self.directory.chmod(0o700)
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    handle.write(secret)
                    handle.flush()
                    os.fsync(handle.fileno())
            except OSError:
                path.unlink(missing_ok=True)
                raise CredentialError("API 키 파일을 저장하지 못했습니다. 키를 다시 입력하세요.") from None
        else:
            raise CredentialError("지원하지 않는 API 키 보관 방식입니다.")
        return reference

    def get(self, reference: str, backend: str) -> str:
        self._file(reference)  # Validate even when the key is in Keychain.
        if backend == "keychain":
            return self._keychain("get", reference)
        if backend != "private_file":
            raise CredentialError("지원하지 않는 API 키 보관 방식입니다.")
        path = self._file(reference)
        if path.is_symlink():
            raise CredentialError("API 키 파일은 심볼릭 링크를 사용할 수 없습니다.")
        try:
            if path.stat().st_size > 4096:
                raise CredentialError("API 키 파일이 올바르지 않습니다.")
            return path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise CredentialError("저장된 API 키를 읽을 수 없습니다. 키를 다시 입력하세요.") from exc

    def delete(self, reference: str, backend: str) -> None:
        self._file(reference)
        if backend == "keychain":
            self._keychain("delete", reference)
        elif backend == "private_file":
            self._file(reference).unlink(missing_ok=True)
        else:
            raise CredentialError("지원하지 않는 API 키 보관 방식입니다.")

    def _keychain(self, action: str, account: str, secret: str = "") -> str:
        if sys.platform != "darwin":
            raise CredentialError("Keychain은 macOS에서만 사용할 수 있습니다.")
        try:
            cf = C.CDLL("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
            sec = C.CDLL("/System/Library/Frameworks/Security.framework/Security")
            ptr = C.c_void_p
            cf.CFStringCreateWithCString.argtypes = [ptr, C.c_char_p, C.c_uint32]
            cf.CFStringCreateWithCString.restype = ptr
            cf.CFDataCreate.argtypes = [ptr, C.c_char_p, C.c_long]
            cf.CFDataCreate.restype = ptr
            cf.CFDictionaryCreateMutable.argtypes = [ptr, C.c_long, ptr, ptr]
            cf.CFDictionaryCreateMutable.restype = ptr
            cf.CFDictionarySetValue.argtypes = [ptr, ptr, ptr]
            cf.CFRelease.argtypes = [ptr]
            cf.CFDataGetLength.argtypes = [ptr]
            cf.CFDataGetLength.restype = C.c_long
            cf.CFDataGetBytePtr.argtypes = [ptr]
            cf.CFDataGetBytePtr.restype = ptr
            sec.SecItemAdd.argtypes = [ptr, ptr]
            sec.SecItemAdd.restype = C.c_int32
            sec.SecItemCopyMatching.argtypes = [ptr, C.POINTER(ptr)]
            sec.SecItemCopyMatching.restype = C.c_int32
            sec.SecItemDelete.argtypes = [ptr]
            sec.SecItemDelete.restype = C.c_int32
            const = lambda name: ptr.in_dll(sec, name).value
            owned: list[int] = []
            def text(value: str):
                obj = cf.CFStringCreateWithCString(None, value.encode(), 0x08000100)
                if not obj:
                    raise CredentialError("Keychain 문자열을 준비하지 못했습니다.")
                owned.append(obj)
                return obj
            query = cf.CFDictionaryCreateMutable(None, 0, None, None)
            owned.append(query)
            def add(key: str, value):
                cf.CFDictionarySetValue(query, const(key), value)
            try:
                add("kSecClass", const("kSecClassGenericPassword"))
                add("kSecAttrService", text(self.service))
                add("kSecAttrAccount", text(account))
                # Do not stall background API workers on an invisible permission dialog.
                add("kSecUseAuthenticationUI", const("kSecUseAuthenticationUIFail"))
                if action == "add":
                    raw = secret.encode("utf-8")
                    data = cf.CFDataCreate(None, raw, len(raw))
                    owned.append(data)
                    add("kSecValueData", data)
                    code = sec.SecItemAdd(query, None)
                elif action == "delete":
                    code = sec.SecItemDelete(query)
                    if code == -25300:
                        return ""
                else:
                    add("kSecReturnData", ptr.in_dll(cf, "kCFBooleanTrue").value)
                    add("kSecMatchLimit", const("kSecMatchLimitOne"))
                    result = ptr()
                    code = sec.SecItemCopyMatching(query, C.byref(result))
                    if code == 0 and result.value:
                        try:
                            size = cf.CFDataGetLength(result)
                            if size < 1 or size > 4096:
                                raise CredentialError("Keychain의 API 키가 올바르지 않습니다.")
                            return C.string_at(cf.CFDataGetBytePtr(result), size).decode("utf-8")
                        finally:
                            cf.CFRelease(result)
                if code:
                    raise CredentialError(f"Keychain에 접근할 수 없습니다 (상태 {code}). Mac에서 접근 권한을 확인하거나, 파일 보관을 명시적으로 선택하고 키를 다시 입력하세요.")
                return ""
            finally:
                for obj in reversed(owned):
                    if obj:
                        cf.CFRelease(obj)
        except CredentialError:
            raise
        except (OSError, ValueError, UnicodeError, AttributeError) as exc:
            raise CredentialError("Mac Keychain을 사용할 수 없습니다. API 키를 저장하지 않았습니다.") from exc
