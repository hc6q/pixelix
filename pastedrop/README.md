# PasteDrop

Compartilhe texto, código, Markdown, imagens, vídeos e arquivos por um link curto. FastAPI, SQLite e interface responsiva em HTML, CSS e JavaScript. Funciona diretamente por IP e porta na rede local.

## Instalação

```bash
cp .env.example .env
# Edite PUBLIC_HOST em .env para o IP local do seu servidor.
mkdir -p data
sudo chown -R 10001:10001 data
docker compose up -d --build
```

Abra `http://192.168.1.24:8766` se este for o IP configurado. Em outros dispositivos da LAN, use o mesmo endereço. Libere a porta **8766/TCP** no firewall do servidor se necessário. A aplicação escuta em `0.0.0.0`; nenhum domínio, HTTPS ou proxy é exigido. Mudar `PUBLIC_HOST` muda os links gerados após `docker compose up -d`; os IDs existentes permanecem, mas links com IP antigo precisarão do IP atualizado.

O container usa o usuário UID 10001. `./data` precisa permitir escrita a ele. O Compose monta `./data:/data`, portanto `docker compose down` e posterior `up -d` preservam os dados.

## Configuração

Copie `.env.example` para `.env` e ajuste:

| Variável | Padrão | Descrição |
| --- | --- | --- |
| `APP_NAME` | `PasteDrop` | Nome na interface |
| `HOST` | `0.0.0.0` | Interface de rede |
| `PORT` | `8766` | Porta HTTP e links |
| `PUBLIC_HOST` | `192.168.1.24` | IP da LAN nos links, sem protocolo |
| `UPLOAD_DIR` | `/data/uploads` | Arquivos enviados |
| `DATABASE_PATH` | `/data/database.db` | Banco SQLite |
| `MAX_UPLOAD_SIZE` | `2147483648` | Limite por upload em bytes (2 GiB) |
| `DEFAULT_EXPIRATION` | `86400` | Prazo padrão: 600, 3600, 86400, 604800, 2592000 ou 0 |

## Uso

Arraste ou selecione um arquivo, digite texto, ou cole com Ctrl+V uma imagem/captura de tela. Escolha título, prazo, senha e opção de apagar após a primeira visualização. O resultado mostra URL completa, QR Code e botões para copiar e abrir. Em HTTP pela LAN o botão copiar usa um fallback compatível com navegadores que restringem a API moderna de clipboard.

A primeira abertura de um link de visualização única impede novas visitas de outros navegadores. O navegador que abriu conserva a sessão por 30 minutos para terminar de carregar a imagem ou buscar trechos de vídeo; então registro e arquivo são removidos. Formulário de senha e QR Code não contam como abertura. O acesso a `/api/paste/{id}` conta; requisições internas de mídia após abrir a página não contam novamente.

## Armazenamento e backup

`./data/database.db` guarda metadados, `./data/uploads/` guarda arquivos e `./data/.cookie_secret` mantém as sessões de senha após reinício. Faça backup da pasta inteira com o serviço parado:

```bash
docker compose stop
cp -a data data-backup
docker compose start
```

Para restaurar, pare o container, reponha a pasta `data` inteira e inicie novamente. A limpeza automática acontece na inicialização e a cada minuto. Prazos vencidos também são verificados imediatamente ao acessar o link.

## API

Documentação interativa: `http://192.168.1.24:8766/docs`.

| Método | Rota | Uso |
| --- | --- | --- |
| `POST` | `/api/paste` | JSON com `text_content`, `format` (`text`, `code`, `markdown`), título, senha, prazo e visualização única |
| `POST` | `/api/upload` | Multipart com `file`, `title`, `password`, `expiration`, `delete_after_view` |
| `GET` | `/api/paste/{id}` | Metadados e texto após autenticação; conta visualização |
| `DELETE` | `/api/paste/{id}` | Cabeçalho `X-Delete-Token` da resposta de criação |
| `GET` | `/{id}` | Página do conteúdo ou senha |
| `GET` | `/raw/{id}` | Texto puro ou arquivo original, com Range para vídeo |
| `GET` | `/qr/{id}` | SVG de QR Code para download |

`expiration` é um dos segundos listados na configuração; `0` significa nunca. O `delete_token` só aparece na resposta de criação e também fica salvo no armazenamento local do navegador. Guarde-o se quiser excluir por API depois.

```bash
curl -s http://192.168.1.24:8766/api/paste \
  -H 'Content-Type: application/json' \
  -d '{"text_content":"Olá","format":"text","expiration":3600}'
```

## Segurança

IDs e nomes internos são aleatórios; nomes enviados são sanitizados; senhas usam PBKDF2 com sal. Cookies são HTTP only, Markdown é sanitizado, texto é escapado e respostas incluem CSP e `nosniff`. HTML e SVG enviados são forçados a download; o servidor nunca executa uploads. Arquivos são gravados em blocos de 1 MiB. O parser multipart pode usar armazenamento temporário em disco: garanta espaço para uploads grandes. O texto enviado por JSON tem limite de 10 MiB.

**HTTP na LAN não criptografa conteúdo nem senhas em trânsito.** Use uma rede confiável; esta aplicação não inclui contas, controle de acesso por usuário ou proteção contra abuso de uma porta pública.

## Testes

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt httpx
.venv/bin/python -m unittest discover -s tests -v
```

Os testes cobrem texto, imagem, vídeo e Range, raw, expiração e limpeza física, senha, visualização única, URL com IP e reabertura do banco. A conectividade de outro aparelho e a reinicialização real do container devem ser conferidas no seu homeserver.
