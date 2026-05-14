# ⚽ Bolão Copa 2026

Sistema de bolão para a Copa do Mundo 2026, com suporte a múltiplas cotas por participante, cálculo automático de pontuação, ranking em tempo real e premiação proporcional.

## Funcionalidades

- **Múltiplas cotas por participante** — cada cota concorre separadamente no ranking
- **Fase de grupos e mata-mata** com multiplicadores por fase
- **Pontuação automática** após lançamento de resultado
- **Bloqueio de palpites 4h antes do primeiro jogo do dia**
- **Palpite do campeão** (10 pts extras)
- **Ranking com critérios de desempate**
- **Premiação proporcional** para as 5 melhores cotas
- **Visibilidade aberta** dos palpites entre participantes do mesmo bolão
- **Simulador de pontuação** por jogo
- **Notificações por e-mail** (abertura de fase, lembretes, resultados)
- **Mobile-first** — interface projetada para smartphones
- **Interface admin completa** — cria jogos, lança resultados, confirma pagamentos

## Regras de pontuação

| Categoria | Placar exato | Classificado | Vencedor |
|---|---:|---:|---:|
| Grupos | 5 pts | — | 3 pts |
| Mata-mata (base) | 6 pts | 4 pts | 2 pts |
| Fase 32 / Oitavas | × 1,5 | × 1,5 | × 1,5 |
| Quartas de final | × 2 | × 2 | × 2 |
| Semifinal | × 3 | × 3 | × 3 |
| Final | × 4 | — | — |

## Stack técnica

- **Backend**: Python 3.12 + FastAPI + Uvicorn
- **Banco remoto**: Turso (libSQL) — fonte de verdade
- **Banco local**: SQLite (réplica efêmera para leitura rápida)
- **Templates**: Jinja2 (server-side rendering, mobile-first)
- **Auth**: JWT via cookie HttpOnly
- **E-mail**: aiosmtplib via SMTP configurável
- **Deploy**: Docker + Portainer (intranet) / Render (internet)

## Setup local

### 1. Clonar e instalar dependências

```bash
git clone https://github.com/maikellt/bolao.git
cd bolao
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Configurar variáveis de ambiente

```bash
cp .env.example .env
# Edite o .env com suas credenciais
```

### 3. Rodar localmente

```bash
python main.py
# Acesse: http://localhost:8000
# Login padrão: admin@bolao.local / admin123
```

## Deploy — ambiente interno (Docker/Portainer)

```bash
# Construir e subir
docker-compose up -d --build

# Verificar logs
docker logs bolao -f

# Reiniciar após patch (sem rebuild)
docker cp arquivo.py bolao:/app/arquivo.py
docker restart bolao
```

A aplicação ficará disponível na porta **8087** do host.

## Deploy — Render

1. Conecte o repositório no [Render](https://render.com)
2. Use o `render.yaml` como Blueprint
3. Configure as variáveis de ambiente no painel do serviço
4. A aplicação escutará na porta definida pela variável `PORT` (automático no Render)

## Estrutura do projeto

```
bolao/
├── main.py                  # Entry point FastAPI
├── database.py              # Conexão, migrations, sync Turso↔local
├── auth.py                  # JWT, hashing, dependências de auth
├── routes/
│   ├── auth.py              # Login, logout, cadastro via convite
│   ├── admin.py             # Painel do organizador
│   ├── participante.py      # Dashboard, ranking, histórico
│   └── palpites.py          # Envio e consulta de palpites
├── services/
│   ├── pontuacao.py         # Cálculo de pontos e ranking
│   └── email_service.py     # Envio de e-mails transacionais
├── templates/
│   ├── base.html
│   ├── login.html
│   ├── register.html
│   ├── dashboard.html
│   ├── palpites.html
│   ├── ranking.html
│   ├── historico.html
│   ├── erro.html
│   └── admin/
│       ├── dashboard.html
│       ├── bolao_form.html
│       ├── bolao_detalhe.html
│       ├── jogos.html
│       └── ranking.html
├── static/
│   ├── css/style.css
│   └── js/app.js
├── Dockerfile
├── docker-compose.yml
├── render.yaml
├── requirements.txt
├── .env.example
└── .gitignore
```

## Variáveis de ambiente

| Variável | Descrição |
|---|---|
| `JWT_SECRET` | Chave secreta para assinar tokens JWT |
| `ADMIN_EMAIL` | E-mail do admin padrão criado na inicialização |
| `ADMIN_PASSWORD` | Senha do admin padrão |
| `TURSO_DATABASE_URL` | URL do banco Turso (libsql://...) |
| `TURSO_AUTH_TOKEN` | Token de autenticação do Turso |
| `SMTP_HOST` | Servidor SMTP |
| `SMTP_PORT` | Porta SMTP (padrão: 587) |
| `SMTP_USER` | Usuário SMTP |
| `SMTP_PASSWORD` | Senha SMTP |
| `SMTP_FROM` | E-mail remetente |
| `LOCAL_DB_PATH` | Caminho do banco SQLite local (padrão: /tmp/bolao/local.db) |

## Fluxo de uso

1. Admin cria o bolão → define valor de cota e divisão do prêmio
2. Admin gera links de convite e envia para participantes
3. Participantes se cadastram pelo link, compram cotas
4. Admin confirma pagamentos → cotas ficam ativas
5. Admin abre fase → participantes enviam palpites
6. Admin lança resultados → pontuação calculada automaticamente
7. Ranking atualizado em tempo real
8. Ao final do torneio, admin consulta premiação final

## Chaveamento Copa 2026

A Copa 2026 terá 48 times e início do mata-mata na **Fase de 32** (não diretamente nas oitavas). O sistema gera os confrontos dinamicamente após o término da fase de grupos, conforme os classificados e melhores terceiros colocados.

## Licença

Projeto privado para uso interno entre amigos.
