<p align="center">
  <img src="static/brand.png" alt="VideoDrop" width="116" />
</p>

<h1 align="center">VideoDrop</h1>

<p align="center">
  Baixador de vídeos sociais em MP4, com seleção de resolução, extração de áudio em MP3,
  preview inteligente e compartilhamento nativo pelo sistema.
</p>

<p align="center">
  <a href="#-sobre-o-projeto">Sobre</a> •
  <a href="#-funcionalidades">Funcionalidades</a> •
  <a href="#-rodando-localmente">Rodando</a> •
  <a href="#-testes">Testes</a> •
  <a href="#-observações-importantes">Observações</a>
</p>

<p align="center">
  <img alt="Python" src="https://img.shields.io/badge/Python-3.12+-3776AB?style=for-the-badge&logo=python&logoColor=white" />
  <img alt="FastAPI" src="https://img.shields.io/badge/FastAPI-Backend-009688?style=for-the-badge&logo=fastapi&logoColor=white" />
  <img alt="yt-dlp" src="https://img.shields.io/badge/yt--dlp-Extractor-111111?style=for-the-badge" />
  <img alt="License" src="https://img.shields.io/badge/License-MIT-F6C945?style=for-the-badge" />
</p>

---

## ✨ Sobre o projeto

O **VideoDrop** é uma aplicação web feita para colar a URL de um post público e baixar o vídeo em MP4, escolhendo a resolução disponível. Ele também oferece download do áudio em MP3, mostra tamanho previsto, exibe miniatura e tenta normalizar vídeos para um formato mais compatível com WhatsApp.

A interface foi pensada para ser direta: colou a URL, o app analisa, mostra as opções e deixa baixar ou compartilhar pelo painel nativo do sistema.

> O VideoDrop usa `yt-dlp` como motor de extração. A disponibilidade de formatos depende da plataforma de origem e das regras públicas de acesso ao conteúdo.

## 🚀 Funcionalidades

- Análise de URLs públicas do YouTube, X/Twitter, Instagram, Facebook e outras plataformas compatíveis com `yt-dlp`.
- Detecção automática de URL com `Ctrl + V` em qualquer lugar da página.
- Lista de resoluções MP4 disponíveis com tamanho real ou estimado.
- Download de áudio em MP3 quando há faixa de áudio disponível.
- Preview com miniatura, título, duração e plataforma detectada.
- Proxy local para miniaturas com fallback quando a plataforma bloqueia hotlink.
- Conversão/normalização de MP4 para H.264/AAC quando necessário.
- Compartilhamento via Web Share API, usando o painel nativo do sistema.
- Loading visual durante análise, thumbnail e preparação de compartilhamento.
- Tema claro/escuro com detecção automática e alternância manual.
- Layout responsivo para desktop e smartphone.
- SEO básico com Open Graph, Twitter Card, JSON-LD, `robots.txt` e `sitemap.xml`.
- Manifest, favicon e ícones para atalhos mobile.
- Cache em memória para acelerar análises repetidas.

## 🧱 Stack

| Camada | Tecnologia |
| --- | --- |
| Backend | Python, FastAPI, Uvicorn |
| Extração | yt-dlp |
| Conversão | imageio-ffmpeg / ffmpeg |
| Frontend | HTML, CSS e JavaScript puro |
| Testes | pytest, TestClient, httpx |

## 📁 Estrutura

```text
videodownload/
├── app.py
├── requirements.txt
├── requirements-dev.txt
├── README.md
├── LICENSE
├── tests/
│   └── test_app.py
└── static/
    ├── index.html
    ├── styles.css
    ├── app.js
    ├── brand.png
    ├── brand.svg
    ├── favicon.png
    ├── favicon.svg
    ├── apple-touch-icon.png
    ├── icon-192.png
    ├── icon-512.png
    ├── site.webmanifest
    └── videodrop_loader_animado.svg
```

## ⚙️ Rodando localmente

Clone o projeto e instale as dependências:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

Suba o servidor:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app:app --host 127.0.0.1 --port 8000 --reload --log-level info
```

Acesse:

```text
http://127.0.0.1:8000
```

## 🧪 Testes

Rode a suíte:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Checagens rápidas de sintaxe:

```powershell
.\.venv\Scripts\python.exe -m py_compile app.py
node --check static\app.js
```

A suíte cobre:

- rotas estáticas e SEO básico;
- análise com cache;
- geração de opção MP3;
- download com `Content-Type` correto;
- validação de token de miniatura;
- erros de probe;
- detecção de compatibilidade para WhatsApp;
- garantia de que o compartilhamento não usa texto/link como fallback.

## 🔌 Endpoints

| Método | Rota | Descrição |
| --- | --- | --- |
| `GET` | `/` | Interface principal |
| `POST` | `/api/probe` | Analisa a URL e retorna metadados, miniatura e formatos |
| `GET` | `/api/download` | Baixa vídeo ou áudio no formato selecionado |
| `GET` | `/api/thumbnail/{token}` | Proxy temporário para miniaturas |
| `GET` | `/robots.txt` | Regras para buscadores |
| `GET` | `/sitemap.xml` | Sitemap dinâmico |

Exemplo de análise:

```powershell
Invoke-WebRequest `
  -UseBasicParsing `
  -Method POST `
  -ContentType "application/json" `
  -Body '{"url":"https://www.youtube.com/watch?v=taiWCJK5J-U"}' `
  http://127.0.0.1:8000/api/probe
```

## 🔐 Variáveis de ambiente

| Variável | Padrão | Descrição |
| --- | --- | --- |
| `PUBLIC_BASE_URL` | vazio | URL pública usada em canonical, Open Graph, sitemap e robots |
| `PROBE_TIMEOUT_SECONDS` | `120` | Tempo máximo para análise de uma URL |
| `PROBE_CACHE_TTL_SECONDS` | `300` | Tempo de cache das análises em memória |
| `PROBE_CONCURRENCY` | `2` | Quantidade máxima de análises simultâneas |
| `DOWNLOAD_CONCURRENCY` | `1` | Quantidade máxima de downloads simultâneos |
| `MAX_URL_LENGTH` | `2048` | Tamanho máximo de URL aceita |
| `THUMBNAIL_TTL_SECONDS` | `900` | Tempo de validade dos tokens de miniatura |
| `MAX_THUMBNAIL_BYTES` | `8388608` | Tamanho máximo da miniatura proxificada |
| `SECURITY_HEADERS_ENABLED` | `0` | Liga headers extras de segurança quando definido como `1` |

Exemplo para produção:

```powershell
$env:PUBLIC_BASE_URL="https://seudominio.com"
$env:SECURITY_HEADERS_ENABLED="1"
.\.venv\Scripts\python.exe -m uvicorn app:app --host 0.0.0.0 --port 8000
```

## 🌎 SEO

O projeto já sai com uma base pronta para indexação:

- `title` e `description`;
- meta robots;
- canonical dinâmico;
- Open Graph;
- Twitter Card;
- JSON-LD do tipo `WebApplication`;
- `robots.txt`;
- `sitemap.xml`;
- manifest para instalação como atalho/app.

Para produção, configure `PUBLIC_BASE_URL` com o domínio final.

## 🛡️ Segurança e produção

Para publicar com mais tranquilidade:

- rode atrás de HTTPS;
- configure `PUBLIC_BASE_URL`;
- ative `SECURITY_HEADERS_ENABLED=1`;
- limite concorrência conforme o tamanho do servidor;
- use rate limit no proxy, CDN ou WAF;
- bloqueie acesso de saída para redes internas no firewall/provedor;
- considere Redis ou outro cache externo se usar múltiplos workers;
- monitore erros do `yt-dlp`, porque as plataformas mudam com frequência.

## ⚠️ Observações importantes

- Links privados, restritos por login, idade, região ou cookies podem falhar.
- O tamanho exibido depende dos metadados da plataforma; quando não há tamanho real, o app estima por bitrate e duração.
- No Chrome/Windows, o compartilhamento nativo precisa de uma etapa extra: primeiro o app prepara o arquivo, depois o botão **Compartilhar agora** abre o painel do sistema.
- O app não envia texto/link como fallback no compartilhamento.
- Alguns sites entregam `.mp4` com VP9, AV1 ou HEVC. O VideoDrop tenta normalizar para H.264/AAC quando necessário para melhorar compatibilidade.

## 🗺️ Roadmap

- Persistir cache em Redis.
- Adicionar fila de downloads.
- Criar histórico local de links analisados.
- Preparar Dockerfile para deploy.
- Adicionar autenticação/limites por usuário para ambientes públicos.

## 🤝 Uso responsável

Use o VideoDrop apenas com vídeos públicos que você tem direito de baixar, arquivar ou compartilhar. Respeite direitos autorais, termos de uso das plataformas e leis aplicáveis.

## 📄 Licença

Distribuído sob licença MIT. Veja [LICENSE](LICENSE) para mais detalhes.
