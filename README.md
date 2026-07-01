<p align="center">
  <img src="static/brand.png" alt="VideoDrop" width="116" />
</p>

<h1 align="center">VideoDrop</h1>

<p align="center">
  Baixador e gravador local de vídeos, com seleção de resolução, áudio em MP3,
  gravação de tela, legendas SRT e compartilhamento nativo pelo sistema.
</p>

<p align="center">
  <a href="https://github.com/isacfmaia/videodrop/releases/latest/download/VideoDrop-Setup.exe">
    <img alt="Baixar VideoDrop para Windows" src="https://img.shields.io/badge/Baixar%20VideoDrop-Windows%20Setup-F6C945?style=for-the-badge&logo=windows&logoColor=111111" />
  </a>
</p>

<p align="center">
  <a href="#-sobre-o-projeto">Sobre</a> •
  <a href="#-funcionalidades">Funcionalidades</a> •
  <a href="#-download-e-instalação">Download</a> •
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

O **VideoDrop** é uma aplicação web/local feita para colar a URL de um post público e baixar o vídeo em MP4, escolhendo a resolução disponível. Ele também oferece download do áudio em MP3, mostra tamanho previsto, exibe miniatura e tenta normalizar vídeos para um formato mais compatível com WhatsApp.

A interface foi pensada para ser direta: colou a URL, o app analisa, mostra as opções e deixa baixar ou compartilhar pelo painel nativo do sistema. Também há um modo de gravação local de tela, com preview ao vivo, opção de microfone, áudio do sistema quando o navegador permitir e geração de legenda `.srt` quando houver transcrição do microfone.

> O VideoDrop usa `yt-dlp` como motor de extração. A disponibilidade de formatos depende da plataforma de origem e das regras públicas de acesso ao conteúdo.

## 🚀 Funcionalidades

- Download de vídeos públicos em MP4 a partir de URLs compatíveis com `yt-dlp`.
- Análise de URLs públicas do YouTube, X/Twitter, Instagram, Facebook e outras plataformas compatíveis com `yt-dlp`.
- Login dedicado do VideoDrop via Firefox para posts do Instagram que exigem sessão.
- Detecção automática de URL com `Ctrl + V` em qualquer lugar da página.
- Lista de resoluções MP4 disponíveis com tamanho real ou estimado.
- Download de áudio em MP3 quando há faixa de áudio disponível.
- Preview com miniatura, título, duração e plataforma detectada.
- Proxy local para miniaturas com fallback quando a plataforma bloqueia hotlink.
- Conversão/normalização de MP4 para H.264/AAC quando necessário.
- Compartilhamento via Web Share API, usando o painel nativo do sistema.
- Gravação de tela local via navegador, sem upload do vídeo para servidor externo.
- Captura opcional de áudio do sistema e microfone, desligados por padrão.
- Preview ao vivo, contador de tempo e botão de parada durante a gravação.
- Download separado da gravação em WebM.
- Conversão local da gravação para MP4 antes de compartilhar pelo WhatsApp.
- Geração e download de legenda `.srt` quando o microfone está ligado e o navegador reconhece fala.
- Loading visual durante análise, thumbnail e preparação de compartilhamento.
- Aplicativo Windows com instalador, ícone, atalhos, janela maximizada e bandeja do sistema.
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
| Desktop Windows | PyInstaller, pystray, Inno Setup |
| Testes | pytest, TestClient, httpx |

## 📁 Estrutura

```text
videodrop/
├── app.py
├── desktop_launcher.py
├── requirements.txt
├── requirements-dev.txt
├── requirements-desktop.txt
├── README.md
├── LICENSE
├── installer/
│   └── videodrop.iss
├── scripts/
│   ├── build_windows.ps1
│   └── make_windows_icon.py
├── videodrop/
│   ├── main.py
│   ├── config.py
│   ├── desktop.py
│   ├── schemas.py
│   ├── routers.py
│   ├── security.py
│   ├── thumbnails.py
│   ├── extractor.py
│   └── downloads.py
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

O backend segue um **modular monolith enxuto**: o projeto continua simples de executar com `uvicorn app:app`, mas a lógica fica separada por responsabilidade técnica.

## 📥 Download e instalação

### Windows

Baixe a versão mais recente do instalador em:

```text
https://github.com/isacfmaia/videodrop/releases/latest
```

O instalador gerado pelo build local fica em:

```text
dist\installer\VideoDrop-Setup.exe
```

Ele instala o VideoDrop no perfil do usuário, cria atalho com o ícone do app, pode iniciar junto com o Windows e não precisa de alteração em `hosts` nem permissão de administrador. Ao abrir, o VideoDrop sobe o servidor local em `127.0.0.1`, abre a janela em modo app maximizado e mantém um ícone na bandeja do sistema com opções para abrir ou encerrar.

Para usar sem instalador, gere a pasta portátil e execute:

```text
dist\VideoDrop\VideoDrop.exe
```

### Build do instalador

Com Python e Inno Setup 6 instalados, gere o pacote Windows:

```powershell
.\scripts\build_windows.ps1
```

Para gerar apenas a pasta portátil `dist\VideoDrop`:

```powershell
.\scripts\build_windows.ps1 -SkipInstaller
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
.\.venv\Scripts\python.exe -m compileall -q app.py videodrop
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
- garantia de que o compartilhamento não usa texto/link como fallback;
- gravação de tela, legendas `.srt` e fallback de navegador sem suporte;
- launcher desktop, instalador Windows e ausência de alteração em `hosts`;
- conversão local de gravações WebM para MP4 antes do compartilhamento.

## 🔌 Endpoints

| Método | Rota | Descrição |
| --- | --- | --- |
| `GET` | `/` | Interface principal |
| `POST` | `/api/probe` | Analisa a URL e retorna metadados, miniatura e formatos |
| `GET` | `/api/download` | Baixa vídeo ou áudio no formato selecionado |
| `POST` | `/api/recordings/whatsapp` | Converte gravações WebM locais para MP4 compatível com WhatsApp |
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
| `MAX_RECORDING_UPLOAD_BYTES` | `1073741824` | Tamanho máximo aceito para converter uma gravação WebM local em MP4 |
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

## 🪟 Windows Desktop

O projeto também tem um launcher desktop para Windows. Ele sobe o servidor local do VideoDrop, abre a interface em modo app no Edge/Chrome e fica ativo na bandeja do sistema quando a janela é fechada.

Funcionalidades do pacote Windows:

- janela em modo app usando o navegador instalado, sem barra de endereço;
- abertura maximizada por padrão;
- ícone do VideoDrop na bandeja, com opções **Abrir VideoDrop**, **Abrir no navegador** e **Encerrar**;
- instância única: clicar no atalho novamente reabre a janela existente;
- instalador sem elevação de administrador, com atalho na Área de Trabalho e opção de iniciar com o Windows;
- endereço local em `127.0.0.1`, preservando compatibilidade com gravação de tela no navegador.

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
- No app local, a opção **Login dedicado do VideoDrop** abre o Instagram em um perfil Firefox separado para links que exigem sessão.
- Para usar esse fluxo, instale o Firefox e faça login no Instagram pela janela aberta pelo botão **Entrar no Instagram**.
- O painel de login dedicado aparece apenas quando uma URL do Instagram falha ao carregar e a janela Firefox dedicada é fechada após a análise com login funcionar.
- O VideoDrop usa apenas esse perfil dedicado como fonte de cookies para Instagram; Chrome, Edge e Brave não são usados para autenticação.
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
