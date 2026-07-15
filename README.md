# PermRAG — permission-aware local knowledge assistant

PermRAG is a self-contained demo of the important RAG security property: **a role is required for every search, and authorization occurs before ranking or answer-context creation.** A prompt cannot override that boundary because the prompt is processed only after retrieval has returned permitted chunks.

It includes a polished local web UI, signed role tokens, SQLite audit storage, a document-access map for administrators, sample documents, and a 30-case red-team suite.

## Run the chat

Requirements: Python 3.11 or newer. There are no packages to install and no API keys.

Open <http://127.0.0.1:8000> in a browser. Stop the server with `Ctrl+C`.

The chat page deliberately has no fixed question suggestions: users can ask naturally about the knowledge available to their role.

## Run the Master Control Center

Use this instead of `run.py` whenever you want to manage the workspace or enable Gemini. It serves both the normal chat at `/` and the protected master screen at `/master` from the same running app.


Open <http://127.0.0.1:8000/master> and sign in as `admin` / `admin`. The Master Control Center lets an admin:

- create and delete roles;
- create and delete chat accounts;
- add, edit, and delete corpus documents;
- choose the allowed roles and classification for each document; and
- configure the optional Gemini answer writer.

Corpus changes are detected automatically for new chat questions—there is no separate ingestion command. The master routes perform a server-side admin-role check; hiding a button in the browser is never the access-control mechanism.

The demo users are below. Each password is deliberately the same as its username.

| Username | Password | Purpose |
|---|---|---|
| `sales` | `sales` | Restricted user; can see Sales and the company leave policy |
| `engineering` | `engineering` | Engineering documents plus the leave policy |
| `hr` | `hr` | HR documents plus the leave policy |
| `finance` | `finance` | Finance documents plus the leave policy |
| `admin` | `admin` | All documents, the document access map, and audit log |

Try this contrast:

1. Sign in as **sales** and ask: `What are the salary bands for engineers?` The chat reports that it has no permitted context.
2. Sign out, sign in as **finance**, and ask the same question. It cites `salary_bands.md` and returns the permitted, grounded result.
3. Sign in as **admin** to use **Document access map** and **Query audit log** in the sidebar.

## Gemini: conversational answers without weakening permissions

Without a model key, PermRAG produces a short local grounded answer. To make responses more natural, start `MASTERrun.py`, open **Gemini answer mode**, and paste a Gemini API key. Select the model available to your key; the default field contains `gemini-3.5-flash`.

The supplied key is held only in the running `MASTERrun.py` process. It is not returned to the browser, written into the corpus, or recorded in the audit database. You will need to enter it again after restarting the server. This option requires internet access because the permitted context is sent to Gemini.

You can also supply the key without using the master UI:

```powershell
$env:PERMRAG_GEMINI_API_KEY = "your-key"
$env:PERMRAG_GEMINI_MODEL = "gemini-3.5-flash"  # optional
python run.py
```

Gemini is only an answer writer, not a retriever. The app first filters chunks using the signed user role, scores only the permitted chunks, and then sends that small permitted context to Gemini. Gemini is called without web search, tools, file access, or access to the SQLite database. Therefore, it cannot see a finance document for a Sales query.

## Included test documents

The sample corpus is under [`corpus`](corpus). It deliberately contains both shared and restricted content:

| Document | Roles |
|---|---|
| `hr/leave_policy.md` | HR, Sales, Engineering, Finance, Admin |
| `hr/employee_handbook.md` | HR, Admin |
| `engineering/architecture_overview.md` | Engineering, Admin |
| `engineering/incident_postmortem_2026.md` | Engineering, Admin |
| `finance/salary_bands.md` | Finance, Admin |
| `finance/q3_budget.md` | Finance, Admin |
| `finance/vendor_payment_process.md` | Finance, Admin |
| `sales_playbook.md` | Sales, Admin |

Every document starts with small front matter. The simplest way to add one is through **Master Control Center → Corpus & permissions**. You may also add a file directly:

```markdown
---
department: legal
allowed_roles: admin
sensitivity: restricted
---
# Example document

Only an admin can retrieve this text.
```

The built-in roles are `sales`, `engineering`, `hr`, `finance`, and `admin`. Create extra roles and accounts in the Master Control Center; do not edit Python code for ordinary role changes.

## Security design

The control point is [`PermissionAwareRetriever.search`](app/retrieval.py). Its signature is:

```python
search(query: str, user_role: str, top_k: int = 4)
```

`user_role` has no default. The retriever first selects chunks containing that role in `allowed_roles`, then scores only that permitted set. It also has a post-search assertion as a fail-closed canary. The service obtains the role from the verified token and never accepts a role from the chat request body.

It also applies a minimum relevance score. That prevents generic words in an attempted bypass (such as “document”) from producing an unrelated permitted answer, while still never making restricted content searchable.

The bundled index is a local TF-IDF-style sparse vector index. That makes the complete demo run immediately without Docker or model downloads. The security invariant is the same one used with a vector database: a non-optional metadata filter is part of the vector search operation, before top-k selection—not an LLM prompt instruction and not a clean-up pass after retrieval.

The default answerer is concise and extractive so the product is deterministic and works offline. To use a local Ollama model for natural-language generation, start Ollama and run:

```powershell
$env:PERMRAG_USE_OLLAMA = "1"
$env:PERMRAG_OLLAMA_MODEL = "llama3.2:3b"  # optional
python run.py
```

Even in this mode, Ollama receives only the already-filtered chunks.

## Verify the red-team claim

Run the test suite:

```powershell
python -m unittest tests.test_permission_enforcement -v
python scripts/generate_results.py
```

The attack set covers direct asks, rephrasing, prompt injection, impersonation, base64/encoding attempts, inference, multi-turn escalation fragments, system-prompt extraction, and tool/SQL bypass claims. The generated portfolio-ready evidence is [`results.md`](results.md).

## API summary

The app exposes a small JSON API used by the UI:

| Endpoint | Access | Description |
|---|---|---|
| `POST /api/login` | Public | Issues a signed JWT with the account’s role |
| `POST /api/chat` | Authenticated | Runs role-filtered retrieval and logs the result |
| `GET /api/me` | Authenticated | Returns current token claims |
| `GET /api/audit` | Admin | Reads the query audit trail |
| `GET /api/documents` | Admin | Reads the document-to-role access map |

For a production deployment, replace demo passwords and the local secret, use HTTPS, move the SQLite database to managed storage, and make the equivalent server-side metadata filter mandatory in Qdrant or another production vector database.
