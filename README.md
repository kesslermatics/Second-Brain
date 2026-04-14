# 🧠 Second Brain

AI-gestütztes persönliches Wissensmanagement-System. Notizen diktieren, automatisch strukturieren lassen, mit Rich-Text-Editor bearbeiten, Bilder per AI interpretieren, Lernkarten generieren, und per Fragen an dein eigenes Wissen abfragen — powered by Gemini, Qdrant und PostgreSQL.

![Tech Stack](https://img.shields.io/badge/FastAPI-009688?style=flat&logo=fastapi&logoColor=white)
![Next.js](https://img.shields.io/badge/Next.js_14-000?style=flat&logo=next.js&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-4169E1?style=flat&logo=postgresql&logoColor=white)
![Qdrant](https://img.shields.io/badge/Qdrant-FF4F64?style=flat&logo=data:image/svg+xml;base64,&logoColor=white)
![Gemini](https://img.shields.io/badge/Gemini_API-4285F4?style=flat&logo=google&logoColor=white)

---

## Features

### 📝 Notizen & Editor

- **Notizen-Assistent** — Gib Infos ein, die KI strukturiert sie mit Markdown (Tabellen, Admonitions, Listen) und schlägt passende Ordner vor
- **Rich Text Editor** — Word-ähnlicher TipTap-Editor mit Toolbar: Fett, Kursiv, Unterstrichen, Überschriften (H1-H3), Listen, Tabellen, Code-Blöcke (Syntax-Highlighting), Farben, Textausrichtung, Links, Zitate, Trennlinien
- **Bild-Upload & Paste** — Bilder direkt in Notizen einfügen per Drag & Drop, Datei-Auswahl oder Clipboard-Paste (Ctrl+V)
- **Datei-Anhänge** — PDFs, Word-Dokumente, Excel-Dateien als Links in Notizen einbetten
- **Excalidraw-Zeichnungen** — Integrierter Whiteboard-/Zeichnungs-Editor für visuelle Notizen
- **Markdown-Vorschau** — Umschalten zwischen Editor und gerenderter Markdown-Ansicht
- **Admonitions** — Visuelle Callout-Blöcke: Merksatz, Tipp, Wichtig, Definition, Beispiel, Warnung
- **Versionsverlauf** — Jede Änderung wird automatisch versioniert, ältere Versionen können wiederhergestellt werden
- **AI-Editing** — Notizen per natürlicher Sprache bearbeiten lassen (z.B. „Füge eine Tabelle hinzu", „Fasse den Text kürzer zusammen")
- **Akzeptieren / Nachbessern / Ablehnen** — Drei-Button-Workflow für alle KI-Vorschläge

### 🔍 Suche & RAG

- **Hybrid Search** — Kombiniert semantische Vektorsuche (Qdrant) mit Volltextsuche (PostgreSQL) per Reciprocal Rank Fusion (RRF)
- **Q&A-Chat (RAG)** — Stelle Fragen an dein Second Brain, Antworten basieren auf deinen eigenen Notizen + Bildbeschreibungen mit Quellenangabe
- **Streaming-Antworten (SSE)** — AI-Antworten werden Wort für Wort gestreamt für schnelleres Feedback
- **Semantische Suche** — Eigene Suchansicht mit Relevanz-Score, Snippets und Tag-Anzeige
- **Bilder im RAG** — AI-generierte Bildbeschreibungen werden als Vektoren eingebettet und bei Suchanfragen und im Chat berücksichtigt

### 🖼️ Bilder & AI Vision

- **Bilder-Galerie** — Alle hochgeladenen Bilder in einer Grid-Ansicht mit Thumbnail-Vorschau, Filter und Detail-Modal
- **Gemini Vision** — Jedes hochgeladene Bild wird automatisch von Gemini AI analysiert: Motiverkennung, OCR (Text im Bild), Diagramm-Beschreibung
- **RAG-Einbettung** — Bildbeschreibungen werden automatisch in Qdrant eingebettet und sind über Suche und Q&A-Chat abrufbar
- **Re-Analyse** — Bilder können jederzeit erneut von der AI interpretiert werden
- **DB-Persistenz** — Alle Bilder werden in der Datenbank getrackt (Metadaten, AI-Beschreibung, Embedding-Status)

### 🏷️ Tags & Organisation

- **Tag-System** — Notizen mit Tags versehen, farbige Tags erstellen
- **AI Tag-Vorschläge** — KI schlägt passende Tags basierend auf Notizinhalt vor, bevorzugt bestehende Tags
- **Ordnerstruktur** — Hierarchisches Ordnersystem mit Unterordnern
- **Ordner-Aktionen** — Direkt im Ordnerbaum: Unterordner erstellen, neue Notiz anlegen
- **Auto-Ordner** — KI schlägt passende Ordnerpfade für neue Notizen vor, erstellt fehlende Ordner automatisch

### 🕸️ Knowledge Graph

- **Wissens-Graph** — Interaktive Force-Directed-Visualisierung aller Notizen und deren Verbindungen
- **Auto-Linking** — KI erkennt inhaltliche Zusammenhänge zwischen Notizen und erstellt automatisch Verlinkungen
- **Manuelle Links** — Notizen manuell verknüpfen (related, references, extends)
- **Graph-Navigation** — Durch Klick auf Knoten direkt zur Notiz springen

### 📚 Spaced Repetition (Lernkarten)

- **Lernkarten-Generator** — AI generiert Frage-Antwort-Karten aus Notizen
- **SM-2 Algorithmus** — Wissenschaftlich fundierter Wiederholungsalgorithmus mit Easiness-Faktor, Intervall und Wiederholungszähler
- **Review-Sessions** — Tägliche Lerneinheiten mit konfigurierbarer Kartenanzahl
- **Ordner-Lernkarten** — Lernkarten für ganze Ordner auf einmal generieren
- **Statistiken** — Übersicht über fällige, gemeisterte und lernende Karten

### 📊 Dashboard & Analytics

- **Dashboard** — Übersicht mit Gesamtstatistiken: Notizen, Ordner, Tags, Lernkarten, Wörter
- **Aktivitäts-Heatmap** — Visuelle Darstellung der Notiz-Aktivität über die Zeit
- **Top-Ordner & Tags** — Die meistgenutzten Ordner und Tags auf einen Blick
- **Spaced-Repetition-Stats** — Lernfortschritt im Dashboard integriert

### 📦 Export & Zusammenfassungen

- **ZIP-Export** — Notizen als Markdown oder JSON exportieren (einzeln, nach Ordner oder alle)
- **AI-Zusammenfassungen** — KI-generierte Zusammenfassungen über Ordner, Tags oder das gesamte Brain
- **Quellenanzahl** — Anzeige wie viele Notizen in die Zusammenfassung eingeflossen sind

### ⚙️ System & Einstellungen

- **Custom Prompts** — Alle drei AI-Prompts (Notiz-Aufbereitung, Q&A, AI-Edit) individuell anpassbar mit Reset auf Standard
- **Tägliche Backups** — Automatische Qdrant-Snapshots um 03:00 UTC mit 60-Tage-Rotation
- **JWT-Auth** — Single-Admin-Login mit 30-Tage-Token
- **Dark Mode UI** — Durchgehend dunkles Design mit Brain-Akzentfarben

---

## Architektur

```
┌─────────────────────┐     ┌──────────────────────────┐     ┌─────────────────┐
│   Next.js 14        │────▶│    FastAPI                │────▶│  PostgreSQL      │
│   (Frontend)        │     │    (Backend)              │     │  (Notes, Users,  │
│   TypeScript        │     │    Python 3.12            │     │   Images, Tags,  │
│   Tailwind CSS      │     │                          │     │   Flashcards)    │
│   Zustand           │     │  ┌──────────────────┐    │     └─────────────────┘
│   TipTap Editor     │     │  │ Gemini API       │    │     ┌─────────────────┐
│   Excalidraw        │     │  │ - 3 Flash (LLM)  │    │────▶│  Qdrant          │
│   react-force-graph │     │  │ - Vision (Bilder)│    │     │  (Embeddings,    │
│   recharts          │     │  │ - Embedding 001  │    │     │   768d, COSINE)  │
└─────────────────────┘     │  └──────────────────┘    │     └─────────────────┘
                            └──────────────────────────┘
```

### Hybrid Search (RAG)

Die Q&A-Funktion kombiniert zwei Suchquellen per **Reciprocal Rank Fusion (RRF)**:

| Quelle | Methode | Stärke |
|--------|---------|--------|
| **Qdrant** | Vektor-Cosine-Similarity (`gemini-embedding-001`, 768d) | Semantisch ähnliche Inhalte (Notizen + Bildbeschreibungen) |
| **PostgreSQL** | Full-Text-Search (`tsvector`, deutsch, Titel-Boost) | Exakte Schlüsselwörter |

Top 10 fusionierte Ergebnisse → Gemini als RAG-Kontext → Antwort mit Quellenangabe.

### AI Vision Pipeline

```
Bild Upload → Disk speichern → DB persistieren → Gemini Vision (Beschreibung)
                                                         ↓
                                              Beschreibung in DB speichern
                                                         ↓
                                              Embedding in Qdrant upserten
                                                         ↓
                                              Bild ist über Suche & Chat abrufbar
```

---

## Tech Stack

| Komponente | Technologie |
|-----------|-------------|
| Frontend | Next.js 14, TypeScript, Tailwind CSS, Zustand |
| Rich Text Editor | TipTap (Markdown, Tabellen, Code-Highlighting, Bilder) |
| Zeichnungen | Excalidraw |
| Knowledge Graph | react-force-graph-2d |
| Charts | recharts |
| Markdown Rendering | react-markdown, remark-gfm |
| Backend | FastAPI, SQLAlchemy (async), Pydantic |
| Datenbank | PostgreSQL (asyncpg) |
| Vektor-DB | Qdrant |
| LLM | Google Gemini 3 Flash Preview |
| Vision AI | Google Gemini 3 Flash Preview (Multimodal) |
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
| `BACKEND_URL` | Öffentliche Backend-URL (für Bild-URLs) | `https://my-backend.up.railway.app` |

### Frontend (`frontend/.env.local`)

| Variable | Beschreibung | Beispiel |
|----------|-------------|---------|
| `NEXT_PUBLIC_API_URL` | Backend API URL | `http://localhost:8000` oder `https://my-backend.up.railway.app` |

---

## API Endpoints

### Auth
| Methode | Pfad | Beschreibung |
|---------|------|-------------|
| `POST` | `/api/auth/login` | Login → JWT Token |
| `GET` | `/api/auth/me` | Aktueller User |

### Ordner
| Methode | Pfad | Beschreibung |
|---------|------|-------------|
| `GET` | `/api/folders/` | Alle Ordner |
| `GET` | `/api/folders/tree` | Ordner als Baumstruktur |
| `POST` | `/api/folders/` | Ordner erstellen |
| `POST` | `/api/folders/ensure-path` | Ordnerpfad sicherstellen (erstellt fehlende) |
| `DELETE` | `/api/folders/{id}` | Ordner löschen |

### Notizen
| Methode | Pfad | Beschreibung |
|---------|------|-------------|
| `GET` | `/api/notes/` | Alle Notizen (optional `?folder_id=`) |
| `GET` | `/api/notes/{id}` | Einzelne Notiz |
| `POST` | `/api/notes/` | Notiz erstellen (+ auto Embedding) |
| `PUT` | `/api/notes/{id}` | Notiz aktualisieren (+ Versionierung + re-Embedding) |
| `DELETE` | `/api/notes/{id}` | Notiz löschen (+ Embedding entfernen) |

### Notiz-Versionen
| Methode | Pfad | Beschreibung |
|---------|------|-------------|
| `GET` | `/api/notes/{id}/versions` | Alle Versionen einer Notiz |
| `GET` | `/api/notes/{id}/versions/{vid}` | Einzelne Version |
| `POST` | `/api/notes/{id}/versions/{vid}/restore` | Version wiederherstellen |

### Bilder
| Methode | Pfad | Beschreibung |
|---------|------|-------------|
| `POST` | `/api/images/upload` | Bild hochladen (+ AI Vision + RAG Embedding) |
| `POST` | `/api/images/paste` | Bild aus Clipboard einfügen |
| `GET` | `/api/images/` | Alle Bilder (optional `?folder_id=`, `?note_id=`) |
| `GET` | `/api/images/{id}` | Einzelnes Bild mit AI-Beschreibung |
| `POST` | `/api/images/{id}/reanalyze` | AI-Beschreibung neu generieren |
| `DELETE` | `/api/images/{id}` | Bild löschen (Disk + DB + Qdrant) |

### Uploads (Legacy, für Editor-Kompatibilität)
| Methode | Pfad | Beschreibung |
|---------|------|-------------|
| `POST` | `/api/uploads/` | Datei hochladen (Bilder werden auch in DB + AI persistiert) |
| `POST` | `/api/uploads/paste` | Clipboard-Bild (wie oben) |

### Tags
| Methode | Pfad | Beschreibung |
|---------|------|-------------|
| `GET` | `/api/tags` | Alle Tags |
| `POST` | `/api/tags` | Tag erstellen |
| `DELETE` | `/api/tags/{id}` | Tag löschen |
| `POST` | `/api/tags/suggest` | AI Tag-Vorschläge für Notizinhalt |

### Chat
| Methode | Pfad | Beschreibung |
|---------|------|-------------|
| `GET` | `/api/chat/sessions` | Sessions auflisten (`?session_type=notes\|qa`) |
| `POST` | `/api/chat/sessions` | Neue Session |
| `GET` | `/api/chat/sessions/{id}` | Session mit Nachrichten |
| `PUT` | `/api/chat/sessions/{id}` | Session-Titel ändern |
| `DELETE` | `/api/chat/sessions/{id}` | Session löschen |
| `POST` | `/api/chat/sessions/{id}/messages` | Nachricht senden → AI-Antwort |

### Streaming
| Methode | Pfad | Beschreibung |
|---------|------|-------------|
| `POST` | `/api/stream/chat/{session_id}` | SSE-Stream für Chat-Antworten |

### Suche
| Methode | Pfad | Beschreibung |
|---------|------|-------------|
| `GET` | `/api/search?q=...` | Hybrid Search (Vektor + Volltext, inkl. Bilder) |

### Knowledge Graph & Links
| Methode | Pfad | Beschreibung |
|---------|------|-------------|
| `GET` | `/api/links/graph` | Graph-Daten (Nodes + Edges) |
| `GET` | `/api/links/note/{id}` | Links einer Notiz |
| `POST` | `/api/links/note/{id}` | Manuellen Link erstellen |
| `POST` | `/api/links/note/{id}/auto-link` | AI Auto-Linking |
| `DELETE` | `/api/links/{id}` | Link löschen |

### Spaced Repetition
| Methode | Pfad | Beschreibung |
|---------|------|-------------|
| `GET` | `/api/sr/settings` | Lerneinstellungen |
| `PUT` | `/api/sr/settings` | Einstellungen ändern |
| `POST` | `/api/sr/generate/{note_id}` | Lernkarten für Notiz generieren |
| `POST` | `/api/sr/generate-folder/{folder_id}` | Lernkarten für Ordner |
| `GET` | `/api/sr/review` | Fällige Review-Session |
| `POST` | `/api/sr/review` | Karte bewerten (SM-2) |
| `GET` | `/api/sr/cards` | Alle Lernkarten |
| `DELETE` | `/api/sr/cards/{id}` | Lernkarte löschen |

### Dashboard, Export, Zusammenfassung
| Methode | Pfad | Beschreibung |
|---------|------|-------------|
| `GET` | `/api/dashboard` | Dashboard-Statistiken |
| `POST` | `/api/export` | ZIP-Export (Markdown/JSON) |
| `POST` | `/api/summary` | AI-Zusammenfassung (Ordner/Tag/Alle) |

### AI
| Methode | Pfad | Beschreibung |
|---------|------|-------------|
| `POST` | `/api/ai/edit-note` | Notiz per AI-Anweisung bearbeiten |

### Einstellungen
| Methode | Pfad | Beschreibung |
|---------|------|-------------|
| `GET` | `/api/settings` | Custom Prompts laden |
| `PUT` | `/api/settings` | Prompts ändern |
| `POST` | `/api/settings/reset` | Prompts auf Standard zurücksetzen |

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
│   ├── main.py                  # FastAPI App, Lifespan, CORS, 17 Router
│   ├── config.py                # Pydantic Settings
│   ├── database.py              # SQLAlchemy async Engine, Migrationen
│   ├── models.py                # User, Folder, Note, Tag, Image, ChatSession,
│   │                            # ChatMessage, NoteVersion, NoteLink, FlashCard, ...
│   ├── schemas.py               # Pydantic Request/Response Schemas
│   ├── auth.py                  # JWT Auth, Admin-User-Erstellung
│   ├── routes/
│   │   ├── auth_routes.py       # Login, /me
│   │   ├── folder_routes.py     # Ordner CRUD + ensure-path
│   │   ├── note_routes.py       # Notizen CRUD + auto-Embedding + Versionierung
│   │   ├── chat_routes.py       # Chat Sessions + Messages (Notes & Q&A + RAG)
│   │   ├── stream_routes.py     # SSE Streaming Chat
│   │   ├── ai_routes.py         # AI-Edit Endpoint
│   │   ├── tag_routes.py        # Tags CRUD + AI-Suggest
│   │   ├── search_routes.py     # Hybrid Search (Notizen + Bilder)
│   │   ├── version_routes.py    # Notiz-Versionsverlauf
│   │   ├── link_routes.py       # Note Links + Knowledge Graph + Auto-Link
│   │   ├── sr_routes.py         # Spaced Repetition (Flashcards, Review, SM-2)
│   │   ├── dashboard_routes.py  # Dashboard Analytics
│   │   ├── export_routes.py     # ZIP Export
│   │   ├── summary_routes.py    # AI Zusammenfassungen
│   │   ├── settings_routes.py   # Custom Prompts
│   │   ├── image_routes.py      # Bilder CRUD + AI Vision + RAG Embedding
│   │   └── upload_routes.py     # Legacy Uploads (Editor-Kompatibilität)
│   └── services/
│       ├── ai_service.py        # Gemini Prompts (Notiz, RAG, Edit, Tags, Links, Cards, Summary)
│       ├── vector_service.py    # Qdrant + Hybrid Search (RRF) + Image Embeddings
│       ├── vision_service.py    # Gemini Vision (Bildbeschreibung, OCR)
│       └── backup_service.py    # Tägliche Qdrant-Backups
├── uploads/                     # Hochgeladene Dateien (pro User)
├── requirements.txt
├── Dockerfile
└── .env.example

frontend/
├── src/
│   ├── app/
│   │   ├── layout.tsx           # Root Layout, Metadata
│   │   ├── page.tsx             # Redirect → /dashboard
│   │   ├── globals.css          # Markdown Styles, Admonitions, TipTap Styles
│   │   ├── login/page.tsx       # Login Page
│   │   └── dashboard/page.tsx   # Haupt-Dashboard (View-Router)
│   ├── components/
│   │   ├── Sidebar.tsx          # Navigation + Quick Actions (9 Views)
│   │   ├── FolderTree.tsx       # Ordner-Baum mit Inline-Aktionen
│   │   ├── ChatView.tsx         # Dual-Chat-Layout (Notes + Q&A)
│   │   ├── ChatPanel.tsx        # Chat-Messages + Streaming + Aktions-Buttons
│   │   ├── NotesView.tsx        # Notizen-Übersicht
│   │   ├── NoteViewer.tsx       # Einzelne Notiz anzeigen
│   │   ├── RichTextEditor.tsx   # TipTap Rich Text Editor (Word-like)
│   │   ├── ExcalidrawEditor.tsx # Excalidraw Zeichnungs-Editor
│   │   ├── AIEditModal.tsx      # KI-Edit Modal (Original vs. Vorschlag)
│   │   ├── SearchView.tsx       # Semantische Suche
│   │   ├── DashboardView.tsx    # Dashboard mit Statistiken + Heatmap
│   │   ├── KnowledgeGraphView.tsx # Interaktiver Wissens-Graph
│   │   ├── SpacedRepView.tsx    # Lernkarten Review + Verwaltung
│   │   ├── ExportView.tsx       # Export-Ansicht
│   │   ├── SummaryView.tsx      # AI-Zusammenfassungen
│   │   ├── ImageGallery.tsx     # Bilder-Galerie mit AI-Beschreibungen
│   │   ├── SettingsModal.tsx    # Custom Prompt Einstellungen
│   │   └── CreateFolderModal.tsx
│   └── lib/
│       ├── api.ts               # Axios API Client (alle Endpoints)
│       ├── store.ts             # Zustand State Management
│       ├── types.ts             # TypeScript Interfaces
│       └── markdownComponents.tsx # Admonition Renderer
├── public/
├── package.json
├── Dockerfile
└── .env.example
```

---

## Lizenz

Private Nutzung.
