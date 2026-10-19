# RAG Platform – Frontend

React 19 + Vite + TypeScript + Tailwind 4 single-page app for the RAG backend.

## Quick start (Windows PowerShell)

```powershell
npm install
Copy-Item .env.example .env     # VITE_API_BASE_URL=http://localhost:8000/api/v1
npm run dev                     # http://localhost:5173
```
The backend must allow this origin in `CORS_ORIGINS`. If the backend has `API_KEY` set, enter it on
the Settings page (stored in localStorage, sent as `X-API-Key`; never compiled into the bundle).

## Scripts

| Command | Purpose |
|---|---|
| `npm run dev` | Dev server with HMR |
| `npm run build` | Typecheck + production build to `dist/` |
| `npm run preview` | Serve the production build |
| `npm test` | Vitest + Testing Library (mocked API) |
| `npm run lint` / `npm run typecheck` | ESLint / TypeScript |

## Structure

```
src/
  api/          client.ts (base URL, auth header, error handling), chat.ts (SSE streaming),
                documents.ts (XHR upload with progress), evaluation.ts, retrieval.ts, health.ts
  hooks/        useChatStream (streaming state, cancel, retry, session), useSystem (queries, theme)
  components/   layout/, chat/, documents/, evaluation/, charts/, ui/
  pages/        Dashboard, Chat, Documents, Evaluations, Settings, NotFound
  utils/        sse.ts (incremental SSE parser), format.ts, fileValidation.ts, status.ts
  types/api.ts  types mirroring backend schemas
tests/          Vitest suites
```

* **Streaming:** `fetch` + `ReadableStream` + `SSEParser`, which handles frames split across network
  chunks, CRLF endings, multi-line data and comments. A stream that ends without `done` is reported as
  interrupted; the Stop button aborts the request (the backend stops generating).
* **Safety:** model output is rendered with `react-markdown` without `rehype-raw`, so HTML/scripts are
  not executed; images are dropped and only http(s)/mailto links are kept.
* **No fake data:** every number comes from the API; empty states are shown otherwise.
* Heavy pages (chat markdown, evaluation charts) are lazy-loaded chunks.

## Deployment (Vercel)

Root directory `frontend`, set `VITE_API_BASE_URL` to the deployed backend (`https://…/api/v1`).
`vercel.json` adds the SPA rewrite. Docker alternative: `docker build --build-arg
VITE_API_BASE_URL=https://api.example.com/api/v1 -t rag-frontend .` (nginx on port 8080).
