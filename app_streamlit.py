import base64
import html
import io
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unicodedata
import uuid
import zipfile
from pathlib import Path

import pandas as pd
import streamlit as st
from dotenv import dotenv_values, set_key



ROOT_DIR = Path(__file__).resolve().parent

STREAMLIT_CLOUD = os.environ.get("STREAMLIT_CLOUD", "false").lower() == "true"
ENV_PATH = ROOT_DIR / ".env"
DEFAULT_ENV_PATH = ROOT_DIR / "default.env"
MAIN_PATH = ROOT_DIR / "main.py"
LOGO_PATH = ROOT_DIR / "logo-sanity-medium-new.png"
UPLOAD_DIR = ROOT_DIR / "uploads_streamlit"
TMP_PDFS_DIR = ROOT_DIR / "pdfs_tmp_sharepoint"
SECRET_SECTION = "meus_arquivos"
SECRET_MAIN_B64_KEYS = ("main_py_b64", "script_oculto_b64")
SECRET_MAIN_KEYS = ("main_py", "script_oculto")
SECRET_MAIN_B64_ENV_KEYS = ("STREAMLIT_SECRET_MAIN_PY_B64", "MAIN_PY_CODE_B64", "SCRIPT_OCULTO_B64")
SECRET_MAIN_ENV_KEYS = ("STREAMLIT_SECRET_MAIN_PY", "MAIN_PY_CODE", "SCRIPT_OCULTO")
SECRET_CONFIG_SECTIONS = ("config", "env", "ambiente", SECRET_SECTION)
SECRET_CODE_KEYS = set(SECRET_MAIN_B64_KEYS + SECRET_MAIN_KEYS)

DEFAULTS = {
    "ACCESS_TOKEN": "",
    "TENANT_ID": "",
    "APP_ID": "",
    "CLIENT_SECRET": "",
    "HOSTNAME": "",
    "SITE_PATH": "/sites/ContasaPagar",
    "FILE_NAME": "BANCO_DE_DADOS  1 03_2026.xlsx",
    "SHEET_NAME": "CARGA HORARIA",
    "MODEL": "",
    "OPENAI_API_KEY": "",
    "MODO_LOCAL": "false",
    "CAMINHO_PLANILHA_LOCAL": "",
    "PATH_PDFS": "",
    "BAIXAR_PDFS_SHAREPOINT": "false",
    "CAMINHO_PASTA_PDFS_SHAREPOINT": (
        "CONTAS A PAGAR/3 - NOTAS FISCAIS TERCEIROS (Consultores)/"
        "SANITY CONSULTORIA/2026/03.2026/SIMPLES NACIONAL - FORA DE SP"
    ),
    "PROMPT": "",
}


def limpar_pdfs_tmp_sharepoint() -> None:
    """
    Remove todos os arquivos da area temporaria usada pelo modo nuvem.
    """
    if not TMP_PDFS_DIR.exists():
        return

    try:
        for item in TMP_PDFS_DIR.iterdir():
            if item.is_dir():
                shutil.rmtree(item)
            else:
                item.unlink()
    except Exception as e:
        print(f"Aviso: Erro ao limpar PDFs temporarios antes de processar: {e}")



def load_config() -> dict:
    # 1. Começa com os valores padrão hardcoded (se houver)
    values = DEFAULTS.copy()

    # 2. Atualiza com o arquivo padrão/base (.env.default), se existir
    if DEFAULT_ENV_PATH.exists():
        values.update(
            {
                k: v
                for k, v in dotenv_values(DEFAULT_ENV_PATH).items()
                if v is not None
            }
        )

    # 3. Atualiza com o arquivo local (.env), se existir
    if ENV_PATH.exists():
        values.update(
            {k: v for k, v in dotenv_values(ENV_PATH).items() if v is not None}
        )
    elif not ENV_PATH.exists() and not DEFAULT_ENV_PATH.exists():
        # Opcional: Cria o arquivo local apenas se nenhum dos dois existir (evita criar na nuvem sem necessidade)
        pass

    # 3.5. Atualiza com Secrets simples do Streamlit, se existirem.
    secrets_data = _flatten_config_secrets(_load_secrets_dict())
    for key in values.keys():
        if key in secrets_data and not isinstance(secrets_data[key], dict):
            values[key] = str(secrets_data[key])
            
    # if secrets_data:
    #     token = values.get('TENANT_ID', '')
    #     hostname = values.get('HOSTNAME', '')
    #     st.info(f"Hostname: {hostname}" if hostname else "❌ Hostname vazio")
    #     st.info(f"Tenant ID: {token[:8]}..." if token else "❌ Tenant ID vazio")
        
    # else:
    #     st.warning("⚠️ Nenhum secret encontrado — verifique .env ou .streamlit/secrets.toml")

    # 4. CRUCIAL: Sobrescreve com as variáveis reais do ambiente do sistema (Nuvem/OS)
    # Só trazemos para o dicionário as chaves que o seu app realmente espera usar
    for key in values.keys():
        env_value = os.environ.get(key)
        if env_value is not None:
            values[key] = env_value

    return values


def save_config(values: dict) -> None:
    if not ENV_PATH.exists():
        ENV_PATH.write_text("", encoding="utf-8")

    for key, value in values.items():
        set_key(str(ENV_PATH), key, str(value or ""))


def _load_secrets_dict() -> dict:
    try:
        return st.secrets.to_dict()
    except Exception as err:
        print(f"Erro ao carregar secrets via dict: {err}")
        secrets_path = ROOT_DIR / ".streamlit" / "secrets.toml"
        if not secrets_path.exists():
            return {}
        
        
        try:
            import tomllib

            with secrets_path.open("rb") as file:
                return tomllib.load(file)
        except Exception as err:
            print(f"Erro ao carregar secrets via path dir: {err}")
            return {}


def _flatten_config_secrets(secrets_data: dict) -> dict:
    flat = {}

    for key, value in secrets_data.items():
        if not isinstance(value, dict) and key not in SECRET_CODE_KEYS:
            flat[key] = value

    for section in SECRET_CONFIG_SECTIONS:
        section_values = secrets_data.get(section, {})
        if not isinstance(section_values, dict):
            continue

        for key, value in section_values.items():
            if not isinstance(value, dict) and key not in SECRET_CODE_KEYS:
                flat[key] = value

    return flat


def _secret_value(section: str, key: str) -> str:
    try:
        value = st.secrets[section][key]
    except Exception:
        value = _secret_value_from_toml(section, key)

    return str(value or "")


def _secret_value_from_toml(section: str, key: str) -> str:
    secrets_path = ROOT_DIR / ".streamlit" / "secrets.toml"
    if not secrets_path.exists():
        return ""

    try:
        import tomllib

        with secrets_path.open("rb") as file:
            secrets_data = tomllib.load(file)
    except Exception:
        return ""

    return str(secrets_data.get(section, {}).get(key, "") or "")


def _decode_secret_code(raw_value: str) -> str:
    raw_value = str(raw_value or "")
    if raw_value.startswith("BASE64:"):
        encoded = raw_value[len("BASE64:") :].strip()
        try:
            return base64.b64decode(encoded).decode("utf-8-sig")
        except Exception:
            return ""
    return raw_value


def load_hidden_backend_code() -> str:
    for key in SECRET_MAIN_B64_KEYS:
        code = _decode_secret_code(f"BASE64:{_secret_value(SECRET_SECTION, key)}")
        if code.strip():
            return code

    for key in SECRET_MAIN_KEYS:
        code = _decode_secret_code(_secret_value(SECRET_SECTION, key))
        if code.strip():
            return code

    for key in SECRET_MAIN_B64_ENV_KEYS:
        code = _decode_secret_code(f"BASE64:{os.environ.get(key, '')}")
        if code.strip():
            return code

    for key in SECRET_MAIN_ENV_KEYS:
        code = _decode_secret_code(os.environ.get(key, ""))
        if code.strip():
            return code

    return ""


def build_secret_backend_command(secret_code: str) -> tuple[list[str], Path | None]:
    if not secret_code.strip():
        return [sys.executable, "-u", str(MAIN_PATH)], None

    temp_dir = Path(tempfile.mkdtemp(prefix="streamlit_secret_backend_"))
    secret_file = temp_dir / "main_secret.py"
    secret_file.write_text(secret_code, encoding="utf-8")

    runner = (
        "import pathlib, sys; "
        "secret_path = pathlib.Path(sys.argv[1]); "
        "fake_file = sys.argv[2]; "
        "code = secret_path.read_text(encoding='utf-8-sig'); "
        "namespace = {'__name__': '__main__', '__file__': fake_file, "
        "'__package__': None, '__cached__': None}; "
        "exec(compile(code, fake_file, 'exec'), namespace)"
    )

    return [sys.executable, "-u", "-c", runner, str(secret_file), str(MAIN_PATH)], temp_dir


def save_uploaded_file(uploaded_file, target_dir: Path) -> Path:
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / uploaded_file.name
    target.write_bytes(uploaded_file.getbuffer())
    return target


def limpar_uploads_anteriores(base_dir: Path, manter_ultimos: int = 3) -> None:
    """
    Remove diretórios antigos de upload, mantendo apenas os mais recentes.
    
    Args:
        base_dir: Diretório base de uploads (ex: uploads_streamlit/pdfs)
        manter_ultimos: Número de execuções anteriores a manter
    """
    if not base_dir.exists():
        return
    
    try:
        # Lista todos os diretórios com timestamp
        diretorios = sorted(
            [d for d in base_dir.iterdir() if d.is_dir()],
            key=lambda p: p.stat().st_mtime,
            reverse=True
        )
        
        # Remove tudo exceto os últimos N diretórios
        for dir_antigo in diretorios[manter_ultimos:]:
            try:
                shutil.rmtree(dir_antigo)
            except Exception as e:
                print(f"Aviso: Não foi possível remover {dir_antigo}: {e}")
    except Exception as e:
        print(f"Aviso: Erro ao limpar uploads anteriores: {e}")


def _gerar_log_processamento(output_lines: list) -> str:
    """
    Gera um arquivo de log com toda a saída do processamento.
    Retorna o caminho do arquivo gerado.
    """
    from datetime import datetime
    
    try:
        # Cria diretório de logs
        logs_dir = UPLOAD_DIR / "logs_processamento"
        logs_dir.mkdir(parents=True, exist_ok=True)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        arquivo_log = logs_dir / f"processamento_{timestamp}.log"
        
        # Escreve o arquivo de log com toda a saída
        with open(arquivo_log, 'w', encoding='utf-8') as f:
            f.write(f"Arquivo de Log de Processamento - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write("=" * 80 + "\n\n")
            for line in output_lines:
                f.write(line + "\n")
        
        return str(arquivo_log)
    except Exception as e:
        print(f"Erro ao gerar arquivo de log: {e}")
        return ""


def _carregar_arquivo_bytes(file_path: str):
    if not file_path:
        return None

    path = Path(file_path)
    if not path.exists():
        return None

    return path.name, path.read_bytes()


def somente_digitos(valor) -> str:
    return re.sub(r"\D", "", str(valor or ""))


def remover_acentos(texto) -> str:
    texto = str(texto or "")
    texto = unicodedata.normalize("NFKD", texto)
    return "".join(ch for ch in texto if not unicodedata.combining(ch))


def limpar_texto(valor, maiusculo=True, sem_acentos=True) -> str:
    texto = str(valor or "").strip().replace("\r", " ").replace("\n", " ")
    texto = re.sub(r"\s+", " ", texto)
    if sem_acentos:
        texto = remover_acentos(texto)
    if maiusculo:
        texto = texto.upper()
    return texto


def campo_num(valor, tamanho, vazio_zero=True) -> str:
    digitos = somente_digitos(valor)
    if not digitos and vazio_zero:
        digitos = "0"
    return digitos[-tamanho:].zfill(tamanho)


def campo_texto(valor, tamanho, maiusculo=True, sem_acentos=False) -> str:
    texto = limpar_texto(valor, maiusculo=maiusculo, sem_acentos=sem_acentos)
    return texto[:tamanho].ljust(tamanho, " ")


def campo_discriminacao(valor, limite=1000) -> str:
    texto = str(valor or "").strip()
    texto = texto.replace("\r\n", "|").replace("\n", "|").replace("\r", "|")
    texto = re.sub(r"\s+", " ", texto)
    return remover_acentos(texto).upper()[:limite]


def regime_por_tipo_empresa(tipo_empresa) -> str:
    tipo = limpar_texto(tipo_empresa)
    if tipo == "MEI":
        return "5"
    if "SIMPLES" in tipo:
        return "4"
    return "0"


def preparar_campos_nfts(campos: dict) -> dict:
    tipo_empresa = campos.get("tipo_empresa", "")
    return {
        "tipo": campo_num(campos.get("tipo", "1"), 1),
        "versao": campo_num(campos.get("versao", "001"), 3),
        "ccm_sanity": campo_num(campos.get("ccm_sanity", "30993881"), 8),
        "data_inicio": campo_num(campos.get("data_inicio") or campos.get("data_prestacao"), 8),
        "data_fim": campo_num(campos.get("data_fim") or campos.get("data_prestacao"), 8),
        "tipo_registro_detalhe": campo_num(campos.get("tipo_registro_detalhe", "4"), 1),
        "tipo_documento": campo_num(campos.get("tipo_documento", "02"), 2),
        "serie": campo_texto(campos.get("serie", "7"), 5),
        "numero_documento": campo_num(campos.get("numero_documento", "4329"), 12),
        "data_prestacao": campo_num(campos.get("data_prestacao"), 8),
        "situacao": campo_texto(campos.get("situacao", "N"), 1),
        "tributacao": campo_texto(campos.get("tributacao", "T"), 1),
        "valor_servicos": campo_num(campos.get("valor_servicos", "0"), 15),
        "valor_deducoes": campo_num(campos.get("valor_deducoes", "0"), 15),
        "codigo_servico": campo_num(campos.get("codigo_servico"), 5),
        "codigo_subitem": campo_num(campos.get("codigo_subitem", "0000"), 4),
        "aliquota": campo_num(campos.get("aliquota", "0500"), 4),
        "iss_retido": campo_num(campos.get("iss_retido", "2"), 1),
        "indicador_cpf_cnpj": campo_num(campos.get("indicador_cpf_cnpj", "2"), 1),
        "cnpj_prestador": campo_num(campos.get("cnpj_prestador"), 14),
        "ccm_prestador": campo_num(campos.get("ccm_prestador", "0"), 8),
        "razao_social": campo_texto(campos.get("razao_social"), 75),
        "tipo_logradouro": campo_texto(campos.get("tipo_logradouro"), 3),
        "endereco": campo_texto(campos.get("endereco"), 50),
        "numero": campo_texto(campos.get("numero"), 10),
        "complemento": campo_texto(campos.get("complemento"), 30),
        "bairro": campo_texto(campos.get("bairro"), 30),
        "cidade": campo_texto(campos.get("cidade"), 50),
        "uf": campo_texto(campos.get("uf"), 2),
        "cep": campo_num(campos.get("cep"), 8),
        "email": campo_texto(campos.get("email"), 75, maiusculo=True),
        "tipo_nfts": campo_num(campos.get("tipo_nfts", "1"), 1),
        "regime_tributacao": campo_num(campos.get("regime_tributacao") or regime_por_tipo_empresa(tipo_empresa), 1),
        "data_pagamento": campo_num(campos.get("data_pagamento", "0"), 8),
        "discriminacao": campo_discriminacao(campos.get("discriminacao")),
        "tipo_registro_trailer": campo_num(campos.get("tipo_registro_trailer", "9"), 1),
        "total_deducoes": campo_num(campos.get("total_deducoes") or campos.get("valor_deducoes", "0"), 15),
    }


def gerar_txt_lote(registros: list[dict]) -> str:
    preparados = [preparar_campos_nfts(registro) for registro in registros]
    qtd_notas = len(preparados)
    total_servicos = str(sum(int(item["valor_servicos"]) for item in preparados)).zfill(15)[-15:]
    total_deducoes = str(sum(int(item["valor_deducoes"]) for item in preparados)).zfill(15)[-15:]
    datas = [item["data_prestacao"] for item in preparados if item["data_prestacao"] != "00000000"]
    data_inicio = min(datas) if datas else preparados[0]["data_inicio"]
    data_fim = max(datas) if datas else preparados[0]["data_fim"]

    cabecalho = preparados[0]["tipo"] + preparados[0]["versao"] + preparados[0]["ccm_sanity"] + data_inicio + data_fim
    detalhes = []
    for c in preparados:
        detalhes.append(
            c["tipo_registro_detalhe"] + c["tipo_documento"] + c["serie"] + c["numero_documento"]
            + c["data_prestacao"] + c["situacao"] + c["tributacao"] + c["valor_servicos"]
            + c["valor_deducoes"] + c["codigo_servico"] + c["codigo_subitem"] + c["aliquota"]
            + c["iss_retido"] + c["indicador_cpf_cnpj"] + c["cnpj_prestador"] + c["ccm_prestador"]
            + c["razao_social"] + c["tipo_logradouro"] + c["endereco"] + c["numero"]
            + c["complemento"] + c["bairro"] + c["cidade"] + c["uf"] + c["cep"] + c["email"]
            + c["tipo_nfts"] + c["regime_tributacao"] + c["data_pagamento"] + c["discriminacao"]
        )
    trailer = preparados[0]["tipo_registro_trailer"] + campo_num(qtd_notas, 7) + total_servicos + total_deducoes
    return "\r\n".join([cabecalho, *detalhes, trailer]) + "\r\n"


def gerar_zip_txts_planilha(uploaded_file, qtd_por_lote: int) -> tuple[bytes, int, int]:
    qtd_por_lote = max(1, int(qtd_por_lote or 50))
    df = pd.read_excel(uploaded_file, dtype=str).fillna("")
    registros = df.to_dict(orient="records")
    if not registros:
        raise ValueError("Planilha revisada sem registros.")

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as zip_file:
        for indice, inicio in enumerate(range(0, len(registros), qtd_por_lote), start=1):
            lote = registros[inicio:inicio + qtd_por_lote]
            lote = [{**registro, "qtd_notas": str(len(lote))} for registro in lote]
            txt = gerar_txt_lote(lote)
            zip_file.writestr(f"nfts_lote_{indice:03d}.txt", txt.encode("iso-8859-1", errors="replace"))

    total_lotes = (len(registros) + qtd_por_lote - 1) // qtd_por_lote
    return buffer.getvalue(), len(registros), total_lotes


def logo_data_uri() -> str:
    if not LOGO_PATH.exists():
        return ""

    encoded = base64.b64encode(LOGO_PATH.read_bytes()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def inject_style() -> None:
    logo_uri = logo_data_uri()
    background_logo = (
        f"""
        .stApp::before {{
            content: "";
            position: fixed;
            inset: 0;
            background-image: url("{logo_uri}");
            background-repeat: no-repeat;
            background-position: center 42%;
            background-size: min(56vw, 620px);
            opacity: 0.075;
            pointer-events: none;
            z-index: 0;
        }}
        """
        if logo_uri
        else ""
    )

    st.markdown(
        f"""
        <style>
        .stApp {{
            background:
                radial-gradient(circle at top left, rgba(255, 255, 255, 0.14), transparent 34rem),
                linear-gradient(135deg, #1F029F 0%, #330062 100%);
            color: #f7fbff;
        }}
        {background_logo}
        .block-container {{
            max-width: 1180px;
            padding-top: 2.2rem;
            padding-bottom: 3rem;
            position: relative;
            z-index: 1;
        }}
        .hero {{
            display: flex;
            align-items: center;
            gap: 1.2rem;
            margin-bottom: 1.6rem;
            margin-top: 2rem;
        }}
        .hero img {{
            width: 132px;
            height: auto;
            filter: drop-shadow(0 18px 30px rgba(0, 0, 0, 0.28));
        }}
        .hero h1 {{
            font-size: clamp(.8rem, 2vw, 2.5rem);
            line-height: 1;
            margin: 0;
            letter-spacing: 0;
        }}
        .hero p {{
            margin: 0.4rem 0 0;
            color: rgba(247, 251, 255, 0.82);
            font-size: 1.02rem;
        }}
        section[data-testid="stSidebar"] {{
            background: rgba(20, 0, 72, 0.84);
        }}
        div[data-testid="stForm"], div[data-testid="stExpander"] {{
            background: rgba(255, 255, 255, 0.10);
            border: 1px solid rgba(255, 255, 255, 0.18);
            border-radius: 8px;
            padding: 1rem;
            box-shadow: 0 24px 60px rgba(1, 18, 38, 0.22);
            backdrop-filter: blur(16px);
        }}
        .stTextInput input, .stTextArea textarea, .stSelectbox div[data-baseweb="select"] > div {{
            border-radius: 8px;
        }}
        .stButton > button, .stDownloadButton > button, .stFormSubmitButton > button {{
            border-radius: 8px;
            border: 1px solid rgba(255, 255, 255, 0.22);
            background: linear-gradient(135deg, #1F029F, #330062);
            color: white;
            min-height: 2.75rem;
            font-weight: 700;
        }}
        .log-box {{
            min-height: 420px;
            max-height: 620px;
            overflow: auto;
            white-space: pre-wrap;
            background: rgba(0, 13, 31, 0.78);
            border: 1px solid rgba(151, 215, 255, 0.26);
            border-radius: 8px;
            padding: 1rem;
            font-family: Consolas, "Courier New", monospace;
            font-size: 0.88rem;
            color: #dff3ff;
        }}
        input {{
            background: rgba(0, 0, 0, 0.9) !important;
            border: 1px solid rgba(255, 255, 255, 0.18);
            color: white !important;
        }}
        
        div[data-testid="stMarkdownContainer"] {{
           color: white !important;
        }}
        button[kind="segmented_control"] {{
            background: rgba(255, 255, 255, 0.10) !important;
        }}
        span[class="stTooltipIcon"] {{
            color: white !important;
        }}
        
        /* Esconde o menu de 3 pontinhos (Settings, Main Menu) */
        #MainMenu {{visibility: hidden}}
        
        /* Esconde a barra superior inteira */
        header {{background: transparent}}
        
        /* Esconde o rodapé (Made with Streamlit) */
        footer {{visibility: hidden}}
        
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_header() -> None:
    logo_uri = logo_data_uri()
    logo_html = f'<img src="{logo_uri}" alt="Sanity">' if logo_uri else ""
    st.markdown(
        f"""
        <div class="hero">
            {logo_html}
            <div>
                <h1>Analise Notas Fiscais Financeiro Lote</h1>
                <p>Processamento local ou em nuvem com logs visiveis durante toda a execução.</p>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def build_env_payload(config: dict, modo_operacao: str, token_acesso: str, form_values: dict) -> dict:
    modo_local = modo_operacao == "LOCAL"
    path_pdfs = form_values["path_pdfs"]

    if not modo_local:
        limpar_pdfs_tmp_sharepoint()
        TMP_PDFS_DIR.mkdir(parents=True, exist_ok=True)
        path_pdfs = str(TMP_PDFS_DIR)

    return {
        "ACCESS_TOKEN": token_acesso,
        "TENANT_ID": form_values["tenant_id"],
        "APP_ID": form_values["app_id"],
        "CLIENT_SECRET": form_values["client_secret"],
        "HOSTNAME": form_values["hostname"],
        "SITE_PATH": form_values["site_path"],
        "FILE_NAME": form_values["file_name"],
        "SHEET_NAME": form_values["sheet_name"],
        "MODEL": form_values["model"],
        "OPENAI_API_KEY": form_values["openai_api_key"],
        "MODO_LOCAL": str(modo_local).lower(),
        "CAMINHO_PLANILHA_LOCAL": form_values["caminho_planilha_local"] if modo_local else "",
        "PATH_PDFS": path_pdfs,
        "LOCAL_UPLOAD_PDFS_DIR": path_pdfs if modo_local else "",
        "BAIXAR_PDFS_SHAREPOINT": str(not modo_local).lower(),
        "CAMINHO_PASTA_PDFS_SHAREPOINT": (
            "" if modo_local else form_values["caminho_pasta_pdfs_sharepoint"]
        ),
        "PROMPT": form_values["prompt"] or config.get("PROMPT", ""),
    }


def run_backend() -> tuple[int, str, str]:
    """
    Executa o backend e retorna (código_retorno, caminho_excel, caminho_log).
    """
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    backend_command, temp_secret_dir = build_secret_backend_command(load_hidden_backend_code())

    try:
        process = subprocess.Popen(
            backend_command,
            cwd=str(ROOT_DIR),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
        )

        log_area = st.empty()
        output = []
        caminho_excel = ""
        caminho_log = ""

        assert process.stdout is not None
        for line in iter(process.stdout.readline, ""):
            output.append(line.rstrip())
            
            # Extrai o caminho do arquivo processado se o script o imprimir
            if "Arquivo salvo com sucesso:" in line:
                try:
                    caminho_excel = line.split("Arquivo salvo com sucesso:")[-1].strip()
                except Exception:
                    pass
            
            safe_output = "<br>".join(html.escape(item) for item in output[:])
            log_area.markdown(
                f'<div class="log-box">{safe_output}</div>',
                unsafe_allow_html=True,
            )

        process.wait()
        
        # Gera arquivo de log com toda a saída do processamento
        caminho_log = _gerar_log_processamento(output)
        
        return process.returncode, caminho_excel, caminho_log
    finally:
        if temp_secret_dir is not None:
            shutil.rmtree(temp_secret_dir, ignore_errors=True)


def main() -> None:
    st.set_page_config(
        page_title="Analise NF Financeiro",
        page_icon=str(LOGO_PATH) if LOGO_PATH.exists() else None,
        layout="wide",
    )
    inject_style()
    render_header()

    config = load_config()

    if "last_result" not in st.session_state:
        st.session_state["last_result"] = None
    if "show_result_messages" not in st.session_state:
        st.session_state["show_result_messages"] = False

    with st.sidebar:
        if LOGO_PATH.exists():
            st.image(str(LOGO_PATH), width='stretch')
        # st.caption("Configure, salve e execute o backend.")
        # st.info(f"Ambiente: {ENV_PATH.name}")

    tab_processar, tab_txt = st.tabs(["Processar notas", "Gerar TXT"])

    with tab_processar:
        # Segmented control FORA do formulário para ser reativo
        modo_atual = "LOCAL" if config.get("MODO_LOCAL", "false").lower() == "true" else "NUVEM"
        modo_operacao = st.segmented_control(
            "Origem dos arquivos",
            ["NUVEM", "LOCAL"],
            default=modo_atual,
        )
    
        with st.form("config_form"):
    
            token_acesso = st.text_input(
                "Token de acesso obrigatorio",
                type="password",
                help="Token para validação",
            )
            
            tenant_id = config.get("TENANT_ID", "")
            app_id = config.get("APP_ID", "")
            client_secret = config.get("CLIENT_SECRET", "")
            hostname = config.get("HOSTNAME", "")
            model = config.get("MODEL", "")
            openai_api_key = config.get("OPENAI_API_KEY", "")
    
            col_a, col_b = st.columns(2)
            with col_a:
                if modo_operacao == "NUVEM":
                    site_path = st.text_input("SITE_PATH", value=config.get("SITE_PATH", DEFAULTS["SITE_PATH"]), help="Site onde estão todos os arquivos")
                    file_name = st.text_input("FILE_NAME", value=config.get("FILE_NAME", DEFAULTS["FILE_NAME"]), help="Nome do arquivo Excel que está no SharePoint (ex: BANCO_DE_DADOS  1 03_2026.xlsx)")
                if modo_operacao == "LOCAL":
                    sheet_name = st.text_input("SHEET_NAME", value=config.get("SHEET_NAME", DEFAULTS["SHEET_NAME"]), help="Nome da aba da planilha")
            
            with col_b:
                if modo_operacao == "NUVEM":
                    sheet_name = st.text_input("SHEET_NAME", value=config.get("SHEET_NAME", DEFAULTS["SHEET_NAME"]), help="Nome da aba da planilha")
    
                if modo_operacao == "LOCAL":
                    uploaded_sheet = st.file_uploader("Planilha local (.xlsx)", type=["xlsx", "xlsm"], help="Envie a planilha Excel que está no SharePoint para processamento local.")
                    # caminho_planilha_local = st.text_input(
                    #     "CAMINHO_PLANILHA_LOCAL",
                    #     placeholder="Caso não tenha enviado a planilha, informe o caminho local onde ela está disponível para leitura (ex: C:/meus_arquivos/planilha.xlsx)",
                    # )
                    site_path = ""
                    file_name = uploaded_sheet.name if uploaded_sheet is not None else ""
                    uploaded_pdfs = st.file_uploader(
                        "PDFs locais",
                        type=["pdf"],
                        accept_multiple_files=True,
                        help="Envie os arquivos PDF que estão no SharePoint para processamento local."
                    )
                    path_pdfs = ""  # Sempre começa vazio em modo LOCAL
                    caminho_pasta_pdfs_sharepoint = config.get(
                        "CAMINHO_PASTA_PDFS_SHAREPOINT",
                        DEFAULTS["CAMINHO_PASTA_PDFS_SHAREPOINT"],
                    )
                    caminho_planilha_local = ""  # Inicializa aqui também
                else:
                    uploaded_sheet = None
                    uploaded_pdfs = []
                    caminho_planilha_local = ""
                    path_pdfs = str(TMP_PDFS_DIR)
                    caminho_pasta_pdfs_sharepoint = st.text_input(
                        "CAMINHO_PASTA_PDFS_SHAREPOINT",
                        value=config.get(
                            "CAMINHO_PASTA_PDFS_SHAREPOINT",
                            DEFAULTS["CAMINHO_PASTA_PDFS_SHAREPOINT"],
                        ),
                        help="Caminho da pasta onde os arquivos PDF estão armazenados no SharePoint."
                    )
    
            prompt = config.get("PROMPT", "")
    
            submitted = st.form_submit_button("Salvar configuracao e executar", width='stretch')
    
        can_run = submitted
    
        if submitted:
            if not token_acesso.strip():
                st.error("Informe o token de acesso obrigatorio antes de executar.")
                can_run = False
            elif token_acesso.strip() != config.get("ACCESS_TOKEN", ""):
                st.error("Token de acesso invalido. Verifique e tente novamente.")
                can_run = False
    
            if modo_operacao == "LOCAL" and can_run:
                if uploaded_sheet is not None:
                    # Cria um diretório único por execução
                    session_id = f"{int(time.time() * 1000)}_{uuid.uuid4().hex[:8]}"
                    planilhas_dir = UPLOAD_DIR / "planilhas" / session_id
                    caminho_planilha_local = str(save_uploaded_file(uploaded_sheet, planilhas_dir))
                if uploaded_pdfs:
                    session_id = f"{int(time.time() * 1000)}_{uuid.uuid4().hex[:8]}"
                    pdf_dir = UPLOAD_DIR / "pdfs" / session_id
                    for uploaded_pdf in uploaded_pdfs:
                        save_uploaded_file(uploaded_pdf, pdf_dir)
                    path_pdfs = str(pdf_dir)
                    # Limpa uploads antigos (mantém últimas 3 execuções)
                    limpar_uploads_anteriores(UPLOAD_DIR / "pdfs", manter_ultimos=3)
                    limpar_uploads_anteriores(UPLOAD_DIR / "planilhas", manter_ultimos=3)
                if uploaded_sheet is None or str(caminho_planilha_local).strip() == "":
                    st.error("Envie a planilha local obrigatoria.")
                    can_run = False
                if not path_pdfs:
                    st.error("Informe ou envie os PDFs locais.")
                    can_run = False
    
            if can_run:
                form_values = {
                    "tenant_id": tenant_id,
                    "app_id": app_id,
                    "client_secret": client_secret,
                    "hostname": hostname,
                    "site_path": site_path,
                    "file_name": file_name,
                    "sheet_name": sheet_name,
                    "model": model,
                    "openai_api_key": openai_api_key,
                    "caminho_planilha_local": caminho_planilha_local,
                    "path_pdfs": path_pdfs,
                    "caminho_pasta_pdfs_sharepoint": caminho_pasta_pdfs_sharepoint,
                    "prompt": prompt,
                }
    
                payload = build_env_payload(config, modo_operacao, token_acesso, form_values)
                for key, value in payload.items():
                    os.environ[key] = str(value or "")
    
                # Limpa PDFs temporários do modo NUVEM antes de processar (última execução)
                if modo_operacao == "NUVEM" and TMP_PDFS_DIR.exists():
                    limpar_pdfs_tmp_sharepoint()
    
                # save_config(payload)
    
                # st.success("Configuracao salva no .env. Iniciando processamento...")
                with st.spinner("Executando backend..."):
                    return_code, caminho_excel, caminho_log = run_backend()
    
                modo_local = os.environ.get('MODO_LOCAL', 'false').lower() == 'true'
                excel_info = _carregar_arquivo_bytes(caminho_excel)
                log_info = _carregar_arquivo_bytes(caminho_log)
    
                st.session_state["last_result"] = {
                    "return_code": return_code,
                    "modo_local": modo_local,
                    "excel": excel_info,
                    "log": log_info,
                }
                st.session_state["show_result_messages"] = True
    
        last_result = st.session_state.get("last_result")
        show_messages = st.session_state.get("show_result_messages", False)
    
        if last_result:
            if show_messages:
                if last_result["return_code"] == 0:
                    st.success("✅ Processamento finalizado com sucesso.")
                else:
                    st.error(f"❌ Processamento finalizado com erro. Código: {last_result['return_code']}")
    
            # Download da planilha processada (LOCAL e NUVEM)
            if last_result["excel"]:
                excel_name, excel_bytes = last_result["excel"]
                st.download_button(
                    label=f"📥 Baixar Planilha Processada: {excel_name}",
                    data=excel_bytes,
                    file_name=excel_name,
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True,
                    key="download_excel"
                )
            elif show_messages:
                st.warning(
                    "⚠️ Planilha processada não encontrada. "
                    "Verifique se a planilha foi salva corretamente ou consulte os logs."
                )
    
            # Download do arquivo de log (LOCAL e NUVEM)
            if last_result["log"]:
                log_name, log_bytes = last_result["log"]
                st.download_button(
                    label=f"📥 Baixar Arquivo de Log: {log_name}",
                    data=log_bytes,
                    file_name=log_name,
                    mime="text/plain",
                    use_container_width=True,
                    key="download_log"
                )
            elif show_messages:
                if last_result["modo_local"]:
                    st.warning("⚠️ Arquivo de log não foi gerado nesta execução.")
                else:
                    st.info(
                        "ℹ️ Processamento concluído. "
                        "Os dados foram atualizados no SharePoint. "
                        "Arquivo de log não foi gerado nesta execução."
                    )
    
            if show_messages:
                st.session_state["show_result_messages"] = False

    with tab_txt:
        with st.form("txt_form"):
            planilha_revisada = st.file_uploader(
                "Planilha revisada (.xlsx)",
                type=["xlsx", "xlsm"],
                help="Envie a planilha gerada na etapa anterior, já revisada."
            )
            qtd_por_lote = st.number_input(
                "Quantidade de notas por TXT",
                min_value=1,
                max_value=999999,
                value=50,
                step=1,
            )
            gerar_txt = st.form_submit_button("Gerar TXT em ZIP", width='stretch')

        if gerar_txt:
            if planilha_revisada is None:
                st.error("Envie a planilha revisada para gerar os arquivos TXT.")
            else:
                try:
                    zip_bytes, total_notas, total_lotes = gerar_zip_txts_planilha(planilha_revisada, qtd_por_lote)
                    st.success(f"ZIP gerado com {total_lotes} lote(s) e {total_notas} nota(s).")
                    st.download_button(
                        label="📥 Baixar TXT(s) em ZIP",
                        data=zip_bytes,
                        file_name=f"nfts_txt_lotes_{int(time.time())}.zip",
                        mime="application/zip",
                        use_container_width=True,
                        key="download_txt_zip",
                    )
                except Exception as err:
                    st.error(f"Não foi possível gerar o ZIP: {err}")


if __name__ == "__main__":
    main()
