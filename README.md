# 🧠 Second Brain

AI-gestütztes persönliches Wissensmanagement-System. Notizen diktieren, automatisch strukturieren lassen, und per Fragen an dein eigenes Wissen abfragen — powered by Gemini, Qdrant und PostgreSQL.

![Tech Stack](https://img.shields.io/badge/FastAPI-009688?style=flat&logo=fastapi&logoColor=white)
![Next.js](https://img.shields.io/badge/Next.js_14-000?style=flat&logo=next.js&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-4169E1?style=flat&logo=postgresql&logoColor=white)
![Qdrant](https://img.shields.io/badge/Qdrant-FF4F64?style=flat&logo=data:image/svg+xml;base64,&logoColor=white)
![Gemini](https://img.shields.io/badge/Gemini_API-4285F4?style=flat&logo=google&logoColor=white)

---

## Features

- **Notizen-Assistent** — Gib Infos ein, die KI strukturiert sie mit Markdown (Tabellen, Admonitions, Listen) und schlägt passende Ordner vor
- **Hybrid Search Q&A (RAG)** — Stelle Fragen an dein Second Brain, Antworten basieren auf deinen eigenen Notizen
- **Ordnerstruktur** — Hierarchisches Ordnersystem für deine Notizen
- **AI-Editing** — Notizen per KI-Anweisung bearbeiten lassen
- **Akzeptieren / Nachbessern / Ablehnen** — Drei-Button-Workflow für KI-Vorschläge
- **Admonitions** — Merksatz, Tipp, Wichtig, Definition, Beispiel, Warnung als visuelle Callout-Blöcke
- **Tägliche Backups** — Automatische Qdrant-Snapshots mit 60-Tage-Rotation
- **Dark Mode UI** — Durchgehend dunkles Design

---

## Architektur

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│   Next.js 14    │────▶│    FastAPI        │────▶│  PostgreSQL     │
│   (Frontend)    │     │    (Backend)      │     │  (Notizen, User,│
│   TypeScript    │     │    Python 3.12    │     │   Sessions)     │
│   Tailwind CSS  │     │                  │     └─────────────────┘
│   Zustand       │     │  ┌────────────┐  │     ┌─────────────────┐
└─────────────────┘     │  │ Gemini API │  │────▶│  Qdrant         │
                        │  │ - LLM      │  │     │  (Vektor-DB,    │
                        │  │ - Embedding│  │     │   Embeddings)   │
                        │  └────────────┘  │     └─────────────────┘
                        └──────────────────┘
```

### Hybrid Search (RAG)

Die Q&A-Funktion kombiniert zwei Suchquellen per **Reciprocal Rank Fusion (RRF)**:

| Quelle | Methode | Stärke |
|--------|---------|--------|
| **Qdrant** | Vektor-Cosine-Similarity (`gemini-embedding-001`, 768d) | Semantisch ähnliche Inhalte |
| **PostgreSQL** | Full-Text-Search (`tsvector`, deutsch, Titel-Boost) | Exakte Schlüsselwörter |

Top 10 fusionierte Ergebnisse → Gemini als RAG-Kontext → Antwort mit Quellenangabe.

---

## Tech Stack

| Komponente | Technologie |
|-----------|-------------|
| Frontend | Next.js 14, TypeScript, Tailwind CSS, Zustand, React-Markdown |
| Backend | FastAPI, SQLAlchemy (async), Pydantic |
| Datenbank | PostgreSQL (asyncpg) |
| Vektor-DB | Qdrant |
| LLM | Google Gemini 3 Flash (Preview) |
| Embeddings | Gemini Embedding 001 (768d, MRL-normalized) |
| Auth | JWT (HS256, 30 Tage), Single-Admin |
| Backups | APScheduler, Qdrant Snapshots, 60-Tage-Rotation |
| Deployment | Railway (Docker) |

---

## Lokale Entwicklung

### Voraussetzungen

- Python 3.12+
- Node.js 20+
- PostgreSQL
- Qdrant (Docker: `docker run -p 6333:6333 qdrant/qdrant`)
- Google Gemini API Key ([hier holen](https://aistudio.google.com/apikey))

### Backend

```bash
cd backend
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# .env erstellen (siehe .env.example)
cp .env.example .env
# Werte ausfüllen

uvicorn app.main:app --reload
```

### Frontend

```bash
cd frontend
npm install

# .env.local erstellen
cp .env.example .env.local
# NEXT_PUBLIC_API_URL=http://localhost:8000

npm run dev
```

App läuft auf `http://localhost:3000`.

---

## Environment Variables

### Backend (`backend/.env`)

| Variable | Beschreibung | Beispiel |
|----------|-------------|---------|
| `DATABASE_URL` | PostgreSQL Connection String | `postgresql://user:pass@localhost:5432/brain` |
| `QDRANT_URL` | Qdrant Server URL | `http://localhost` oder `https://qdrant.up.railway.app` |
| `QDRANT_PORT` | Qdrant Port | `6333` |
| `GEMINI_API_KEY` | Google Gemini API Key | `AIza...` |
| `ADMIN_EMAIL` | Login E-Mail | `admin@example.com` |
| `ADMIN_PASSWORD` | Login Passwort | `mein-sicheres-passwort` |
| `JWT_SECRET` | JWT Signing Secret | `openssl rand -hex 32` |
| `FRONTEND_URLS` | Erlaubte CORS Origins (kommagetrennt) | `https://my-frontend.up.railway.app` |

### Frontend (`frontend/.env.local`)

| Variable | Beschreibung | Beispiel |
|----------|-------------|---------|
| `NEXT_PUBLIC_API_URL` | Backend API URL | `http://localhost:8000` oder `https://my-backend.up.railway.app` |

---

## Deployment (Railway)

### Services einrichten

1. **PostgreSQL** — Railway Add-on, Connection String als `DATABASE_URL`
2. **Qdrant** — Docker Image `qdrant/qdrant`, Port `6333`
   - **Volume mounten**: `/qdrant/storage` (damit Daten + Backups persistent sind)
3. **Backend** — Dockerfile im `backend/` Ordner
4. **Frontend** — Dockerfile im `frontend/` Ordner, Build-Arg `NEXT_PUBLIC_API_URL` setzen

### Railway Build Settings

**Backend:**
- Root Directory: `backend`
- Dockerfile Path: `Dockerfile`

**Frontend:**
- Root Directory: `frontend`
- Dockerfile Path: `Dockerfile`
- Build Args: `NEXT_PUBLIC_API_URL=https://dein-backend.up.railway.app`

### Wichtig für Qdrant

Qdrant auf Railway braucht ein **persistentes Volume** auf `/qdrant/storage`. Ohne Volume gehen Collection-Daten und Backup-Snapshots bei jedem Redeploy verloren.

---

## Backup-System

- **Automatisch**: Täglicher Qdrant-Snapshot um 03:00 UTC via APScheduler
- **Rotation**: Snapshots älter als 60 Tage werden automatisch gelöscht
- **Speicherort**: Qdrant-intern unter `/qdrant/storage` (muss als Volume gemountet sein)
- **Manuell**: `POST /collections/brain_notes/snapshots` auf dem Qdrant REST API

---

## Projektstruktur

```
backend/
├── app/
│   ├── main.py              # FastAPI App, Lifespan, CORS
│   ├── config.py             # Pydantic Settings
│   ├── database.py           # SQLAlchemy async Engine
│   ├── models.py             # User, Folder, Note, ChatSession, ChatMessage
│   ├── schemas.py            # Pydantic Request/Response Schemas
│   ├── auth.py               # JWT Auth, Admin-User-Erstellung
│   ├── routes/
│   │   ├── auth_routes.py    # Login
│   │   ├── folder_routes.py  # Ordner CRUD
│   │   ├── note_routes.py    # Notizen CRUD + Embedding-Sync
│   │   ├── chat_routes.py    # Chat Sessions + Messages (Notes & Q&A)
│   │   └── ai_routes.py      # AI-Edit Endpoint
│   └── services/
│       ├── ai_service.py     # Gemini Prompts (Notiz-Aufbereitung, RAG, Edit)
│       ├── vector_service.py  # Qdrant + Hybrid Search (RRF)
│       └── backup_service.py  # Tägliche Qdrant-Backups
├── requirements.txt
├── Dockerfile
└── .env.example

frontend/
├── src/
│   ├── app/
│   │   ├── layout.tsx        # Root Layout, Metadata
│   │   ├── page.tsx          # Redirect → /dashboard
│   │   ├── globals.css       # Markdown Styles, Admonitions
│   │   ├── login/page.tsx    # Login Page
│   │   └── dashboard/page.tsx # Haupt-Dashboard
│   ├── components/
│   │   ├── Sidebar.tsx       # Navigation Sidebar
│   │   ├── FolderTree.tsx    # Ordner-Baum
│   │   ├── ChatView.tsx      # Dual-Chat-Layout (Notes + Q&A)
│   │   ├── ChatPanel.tsx     # Chat-Messages + Aktions-Buttons
│   │   ├── NotesView.tsx     # Notizen-Übersicht
│   │   ├── NoteViewer.tsx    # Einzelne Notiz anzeigen
│   │   ├── NoteEditor.tsx    # Notiz bearbeiten (Markdown)
│   │   ├── AIEditModal.tsx   # KI-Edit Modal (Original vs. Vorschlag)
│   │   └── CreateFolderModal.tsx
│   └── lib/
│       ├── api.ts            # Axios API Client
│       ├── store.ts          # Zustand State Management
│       ├── types.ts          # TypeScript Types
│       └── markdownComponents.tsx  # Admonition Renderer
├── public/
│   └── brain.png             # Favicon / App Icon
├── package.json
├── Dockerfile
└── .env.example
```

---

## Lizenz

Private Nutzung.
