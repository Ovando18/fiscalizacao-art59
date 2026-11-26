# DFI Crea-MS · Gestão de Notificações Orientativas – Art. 59

Aplicação web (Streamlit) do **Departamento de Fiscalização (DFI) do Crea-MS** para gerir as notificações orientativas a empresas sem registro (art. 59 da Lei nº 5.194/1966), controlar prazos, investigar a atuação em fontes abertas e emitir o dossiê de fiscalização.

## Fluxo

```
Importação ─► Aguardando Envio ─► (fila SMTP) ─► Notificado - Aguardando Prazo
                                                     │
              ┌──────────────────────────────────────┼─────────────────────────────┐
              ▼                                      ▼                             ▼
   Respondeu / Em Análise        Regularizada (Registro Efetivado)   Prazo Encerrado - Investigar Atuação
                                                                                   │  (OSINT)
                                                             ┌─────────────────────┴───────────────────┐
                                                             ▼                                         ▼
                                       Atuação Confirmada (Investigação / Fiscalização)     Aguardando Visita In-Loco
```

| Página | O que faz |
|---|---|
| 📊 **Painel de Controle** | KPIs, filtros (CNAE, status, lote, busca), situação do prazo, ações por empresa (respondeu, regularizada, corrigir e-mail, alterar status, anotações, dossiê) e exportação para Excel |
| 📥 **Importação e Lotes** | Upload `.xlsx/.csv`, mapeamento visual de colunas, saneamento de CNPJ/e-mail, trava de duplicidade, lote de teste e exclusão segura de lotes |
| ✉️ **Template e Disparo** | Template editável com variáveis e pré-visualização, aquecimento gradual, janela de expediente, jitter, configuração SMTP do Zimbra e fila com pausa |
| 🔎 **Investigação (OSINT)** | Links de busca prontos, registro de evidências e uploads, regra de decisão (atuação confirmada ou visita in-loco) |
| 📄 **Dossiê de Fiscalização** | PDF individual (`Dossie_{CNPJ}_{RazaoSocial}.pdf`) ou vários em `.zip` |

## Instalação

Requisitos: **Python 3.11+**.

```bash
git clone https://github.com/SEU_USUARIO/fiscalizacao-art59.git
cd fiscalizacao-art59
python -m venv .venv
# Windows: .venv\Scripts\activate    |    Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

O sistema abre em `http://localhost:8501`. O banco SQLite (`database/fiscalizacao_art59.db`) é criado automaticamente na primeira execução.

### Logo institucional

Coloque o logo em **`assets/logo_creams.png`** (PNG, de preferência com fundo transparente). Ele aparece na interface e no cabeçalho dos dossiês e pode ser embutido nos e-mails. Se o arquivo não existir, o sistema mostra um aviso e continua funcionando.

### Planilha de exemplo

```bash
python scripts/gerar_planilha_exemplo.py
```

O script gera o arquivo `exemplo_planilha_cnaes.xlsx`, com 30 empresas **fictícias** e casos de teste: e-mail inválido, e-mail vazio, CNPJ sem máscara e linha duplicada.

Colunas reconhecidas (aceita variações de acento, caixa e espaços, como "Razão Social", "E-mail" e "CNPJ Empresa"):

| Obrigatórias | Opcional |
|---|---|
| `Razao_Social`, `CNPJ`, `CNAE`, `Email` | `Descricao_CNAE` |

> CNPJ alfanumérico: o validador aceita o formato numérico tradicional e o novo CNPJ alfanumérico da Receita Federal (emitido desde julho/2026).

## Configuração do SMTP (Zimbra)

Na página **Template e Disparo › 🔐 Servidor SMTP**, preencha os campos e use **Testar Conexão**:

| Campo | Valor típico |
|---|---|
| Servidor | o host SMTP do Zimbra institucional (confirme com a TI) |
| Porta | `587` (STARTTLS) ou `465` (SSL/TLS) |
| Usuário | e-mail institucional completo |
| Senha | senha da conta (fica só na sessão, a menos que você marque para salvar no `.env`) |

Outra opção é copiar `.env.example` para `.env` e preencher os dados. O `.env` está no `.gitignore` e **nunca deve ser enviado ao GitHub**.

### Sobre a assinatura do Gerente

A assinatura automática do Zimbra é inserida pelo **cliente web** quando se compõe uma mensagem. E-mails enviados por SMTP **normalmente não a recebem**, a menos que o servidor aplique rodapé ou disclaimer de domínio. Por isso o template padrão termina no pedido de confirmação de recebimento e nos contatos do DFI, e a opção *"Incluir assinatura/rodapé institucional"* vem **desmarcada**.

**Recomendação:** use *Enviar e-mail de teste* para seu próprio endereço. Se a assinatura não aparecer, marque a opção, ou cole a assinatura no final do template.

### Boas práticas anti-spam já embutidas

- **Aquecimento gradual:** 20 e-mails no 1º dia de envio, +5 por dia de envio, até o teto de 90 por dia (tudo configurável). A cota só avança em dias com envio efetivo. Lotes de teste **não contam** e não consomem a cota.
- **Janela de expediente:** de 12:00 às 18:00 (`America/Campo_Grande`). Fora dela a fila para e informa quando a próxima janela abre.
- **Jitter:** intervalo aleatório de 45 a 90 s entre envios, mantido mesmo depois de pausar e retomar.
- **Formato das mensagens:** `multipart/alternative` (texto puro + HTML leve), sem imagens remotas. O logo opcional vai embutido via CID, e `Message-ID`, `Date` e `Reply-To` são preenchidos corretamente.
- **Proteção contra bloqueio:** a fila é interrompida automaticamente depois de 3 falhas consecutivas.
- **Log:** tudo é registrado em `logs/envios.log`.

> ⚠️ **Mantenha a página "Template e Disparo" aberta durante o envio.** Cada e-mail é gravado no banco assim que é enviado. Se a página for fechada ou pausada, basta clicar em *Iniciar / Retomar fila*.

## Lote de teste (recomendado antes do envio oficial)

1. Importe uma planilha com e-mails de servidores, marcando **Lote de teste**.
2. Dispare (lotes de teste podem ser enviados fora da janela, sem consumir cota).
3. Confira formatação, logo e assinatura.
4. Em **Importação e Lotes › Gerenciar lotes**, exclua o lote de teste. A exclusão remove empresas, histórico, evidências e o log de envios, então as métricas e o aquecimento ficam limpos.

## Supabase e publicação no Streamlit Cloud

O disco do Streamlit Cloud é **apagado a cada reinício**. Em produção, os dados ficam no **Supabase**:

| O quê | Onde | Variáveis |
|---|---|---|
| Empresas, histórico, envios e configurações | PostgreSQL do Supabase | `DATABASE_URL` |
| Prints e comprovantes (evidências) | Supabase Storage, bucket **privado** `evidencias` | `SUPABASE_URL`, `SUPABASE_SERVICE_KEY` |

Sem essas variáveis, o sistema usa o SQLite local e a pasta `evidencias/`. A barra lateral sempre mostra onde os dados estão sendo gravados.

### 1. Obter as credenciais no Supabase

1. **String de conexão:** no painel do projeto, clique em **Connect** e copie a URI do **Session pooler** (porta 5432). Ela tem este formato:
   ```
   postgresql://postgres.SEU_PROJETO:[SENHA]@aws-0-REGIAO.pooler.supabase.com:5432/postgres
   ```
   > Use o **Session pooler**, não a *Direct connection*. A conexão direta usa apenas IPv6, que o Streamlit Cloud não suporta.
   > Troque `[SENHA]` pela senha do banco (*Project Settings › Database › Reset database password*, se não souber). Se a senha tiver caracteres especiais (`@ : / # ?`), codifique-os (por exemplo, `@` vira `%40`), ou use uma senha só com letras e números.
2. **Chave da API:** em *Project Settings › API Keys*, copie uma **Secret key** (`sb_secret_...`) ou a chave legada **service_role**. **Nunca** use a *publishable/anon key*: o bucket é privado.
3. **URL do projeto:** `https://SEU_PROJETO.supabase.co`.

Na primeira execução, o sistema faz duas coisas sozinho:
- cria as tabelas e **ativa o RLS** (Row Level Security) em todas elas. Assim a API pública do Supabase não consegue ler nem gravar os dados; só o aplicativo, que conecta como dono das tabelas, tem acesso;
- cria o bucket privado `evidencias` (e recusa funcionar se ele estiver público).

### 2. Publicar no Streamlit Cloud

1. Em [share.streamlit.io](https://share.streamlit.io), clique em **Create app** e escolha este repositório, branch `main` e arquivo `app.py`.
2. Em *Advanced settings*, escolha **Python 3.12** e cole os Secrets conforme o modelo [`.streamlit/secrets.toml.example`](.streamlit/secrets.toml.example).
3. Depois do deploy:
   - confira na barra lateral se aparece **Banco: PostgreSQL** e **Evidências: Supabase Storage**;
   - use **Template e Disparo › Servidor SMTP › Testar Conexão**. O Zimbra pode bloquear logins vindos de IPs fora do Brasil; nesse caso, peça liberação à TI.
4. Em *Settings › Sharing*, restrinja o acesso aos e-mails da equipe do DFI.

> ⚠️ **Um operador por vez na fila de disparo.** A fila ainda não tem trava para vários usuários simultâneos: duas pessoas disparando ao mesmo tempo podem enviar e-mail duplicado para a mesma empresa.

### Rodar localmente usando o Supabase

Copie `.streamlit/secrets.toml.example` para `.streamlit/secrets.toml` (ou preencha o `.env`) e execute `streamlit run app.py`.

## Estrutura

```
fiscalizacao-art59/
├── app.py                      # navegação (st.navigation) e inicialização
├── assets/logo_creams.png      # logo institucional
├── database/db_manager.py      # modelos, CRUD, duplicidade, lotes, cota de aquecimento
├── services/
│   ├── mailer.py               # SMTP Zimbra, MIME, janela, jitter, logs
│   ├── osint_helper.py         # links/dorks de investigação
│   ├── report_generator.py     # dossiê em PDF (fpdf2)
│   ├── storage.py              # evidências: disco local ou Supabase Storage
│   ├── config.py               # leitura de .env e Secrets do Streamlit
│   └── utils.py                # CNPJ, e-mail, datas/fuso, extenso
├── templates/email_template.html
├── ui/components.py            # CSS institucional e componentes
├── views/                      # páginas (painel, importação, disparo, investigação, dossiê)
├── scripts/gerar_planilha_exemplo.py
├── tests/test_basico.py
├── requirements.txt
└── .gitignore
```

## Testes

```bash
pip install pytest
pytest -q
```

## Publicar no GitHub

```bash
git init
```

```bash
git add .
```

```bash
git commit -m "Sistema de gestão de notificações Art. 59 – DFI Crea-MS"
```

```bash
git branch -M main
```

```bash
git remote add origin https://github.com/SEU_USUARIO/fiscalizacao-art59.git
```

```bash
git push -u origin main
```

> O `.gitignore` já impede o envio do `.env`, do banco `*.db`, da pasta `evidencias/` e dos logs, que contêm dados sensíveis de fiscalização. Antes do primeiro push, confira com `git status`. Prefira um repositório **privado**.
