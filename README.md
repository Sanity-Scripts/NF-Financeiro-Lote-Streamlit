# Analise NF Financeiro em Lote

Um aplicativo Streamlit para leitura em lote de Notas Fiscais (PDF/Planilha), processamento por um backend oculto e geração de documentos (planilha processada e arquivos TXT agrupados em ZIP) prontos para integração com sistemas financeiros.

Principais casos de uso:
- Processamento e validação em lote de notas fiscais a partir de uma planilha Excel.
- Extração de PDFs (local ou via SharePoint) e execução de um backend que faz validações/transformações.
- Geração de arquivos TXT formatados por lote (exportáveis em ZIP) para importação em outros sistemas.

## Stack
- Language(s): Python 3.10+ (principal)
- Framework / runtime: Streamlit (UI) + backend Python executado de forma oculta via secrets
- Notable libraries:
  - pandas, openpyxl — manipulação de planilhas
  - pdfplumber / pymupdf — leitura de PDFs
  - python-dotenv — carregamento de variáveis de ambiente
  - streamlit — interface web

## O que está neste repositório
Estrutura básica (arquivos e função principal):