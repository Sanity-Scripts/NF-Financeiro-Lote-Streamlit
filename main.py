import base64
import os
from pathlib import Path


SECRET_SECTION = "meus_arquivos"
SECRET_MAIN_B64_KEYS = ("main_py_b64", "script_oculto_b64")
SECRET_MAIN_KEYS = ("main_py", "script_oculto")
SECRET_MAIN_B64_ENV_KEYS = ("STREAMLIT_SECRET_MAIN_PY_B64", "MAIN_PY_CODE_B64", "SCRIPT_OCULTO_B64")
SECRET_MAIN_ENV_KEYS = ("STREAMLIT_SECRET_MAIN_PY", "MAIN_PY_CODE", "SCRIPT_OCULTO")


def _load_from_streamlit_secrets() -> str:
    try:
        import streamlit as st
    except Exception:
        return ""

    for key in SECRET_MAIN_B64_KEYS:
        try:
            code = _decode_b64(str(st.secrets[SECRET_SECTION][key] or ""))
        except Exception:
            continue

        if code.strip():
            return code

    for key in SECRET_MAIN_KEYS:
        try:
            code = _decode_prefixed_code(str(st.secrets[SECRET_SECTION][key] or ""))
        except Exception:
            continue

        if code.strip():
            return code

    return ""


def _load_from_toml_secrets() -> str:
    secrets_path = Path(__file__).resolve().parent / ".streamlit" / "secrets.toml"
    if not secrets_path.exists():
        return ""

    try:
        import tomllib

        with secrets_path.open("rb") as file:
            secrets_data = tomllib.load(file)
    except Exception:
        return ""

    section = secrets_data.get(SECRET_SECTION, {})
    for key in SECRET_MAIN_B64_KEYS:
        code = _decode_b64(str(section.get(key, "") or ""))
        if code.strip():
            return code

    for key in SECRET_MAIN_KEYS:
        code = _decode_prefixed_code(str(section.get(key, "") or ""))
        if code.strip():
            return code

    return ""


def _load_from_env() -> str:
    for key in SECRET_MAIN_B64_ENV_KEYS:
        code = _decode_b64(os.environ.get(key, ""))
        if code.strip():
            return code

    for key in SECRET_MAIN_ENV_KEYS:
        code = _decode_prefixed_code(os.environ.get(key, ""))
        if code.strip():
            return code

    return ""


def _decode_b64(value: str) -> str:
    try:
        return base64.b64decode(str(value or "").encode("ascii")).decode("utf-8-sig")
    except Exception:
        return ""


def _decode_prefixed_code(value: str) -> str:
    value = str(value or "")
    if value.startswith("BASE64:"):
        return _decode_b64(value[len("BASE64:") :].strip())

    return value


def _run_secret_code(code: str) -> None:
    fake_file = str(Path(__file__).resolve())
    namespace = {
        "__name__": "__main__",
        "__file__": fake_file,
        "__package__": None,
        "__cached__": None,
    }
    exec(compile(code, fake_file, "exec"), namespace)


def main() -> None:
    code = _load_from_streamlit_secrets() or _load_from_toml_secrets() or _load_from_env()
    if not code.strip():
        raise RuntimeError(
            "Backend oculto nao configurado. Defina [meus_arquivos].main_py_b64 "
            "nos Secrets do Streamlit ou a variavel MAIN_PY_CODE_B64 localmente."
        )

    _run_secret_code(code)


if __name__ == "__main__":
    main()
