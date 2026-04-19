import urllib.parse

content = """# 🧠 Brain - The AI-Powered Second Brain & Interactive Tutor

Ein KI-gestütztes persönliches Wissensmanagement-System kombiniert mit einem interaktiven **Infinite Teacher** und **Buch-Tutor**. Notizen diktieren, automatisch mit Markdown und Meta-Daten strukturieren lassen, Dateien per Vision AI durchsuchen, und sogar interaktive Kurse oder Bücher generieren lassen, die dir jedes Konzept im Detail erklären.

Powered by **Gemini 3 Flash**, **Qdrant Vector DB**, und **PostgreSQL**.

![Tech Stack](https://img.shields.io/badge/FastAPI-009688?style=flat&logo=fastapi&logoColor=white)
![Next.js](https://img.shields.io/badge/Next.js_14-000?style=flat&logo=next.js&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-4169E1?style=flat&logo=postgresql&logoColor=white)
![Qdrant](https://img.shields.io/badge/Qdrant-FF4F64?style=flat&logo=data:image/svg+xml;base64,&logoColor=white)
![Gemini](https://img.shields.io/badge/Gemini_API-4285F4?style=flat&logo=google&logoColor=white)

---

## 📑 Inhaltsverzeichnis

1. [Projektbeschreibung](#projektbeschreibung)
2. [Kernfunktionen im Detail](#kernfunktionen-im-detail)
   - [📝 Zettelkasten & Notizen](#-zettelkasten--notizen)
   - [🎓 Infinite Teacher (Kurse)](#-infinite-teacher-kurse)
   - [📖 Interactive Book Teacher](#-interactive-book-teacher)
   - [🔍 RAG & Hybrid Search](#-rag--hybrid-search)
   - [🖼️ AI Vision Pipeline](#-ai-vision-pipeline)
   - [🕸️ Knowledge Graph & Auto-Linking](#-knowledge-graph--auto-linking)
   - [📚 Spaced Repetition](#-spaced-repetition)
3. [Architektur](#architektur)
4. [Projektstruktur](#projektstruktur)
5. [Tech Stack](#tech-stack)
6. [Lokale Entwicklung](#lokale-entwicklung)
7. [Deployment](#deployment)

---

## Projektbeschreibung

Das **Brain** Repo ist weit mehr als nur eine Notizen-App. Es verbindet **Wissensspeicherung** (Zettelkasten) mit **Wissensaneignung** (AI Tutor).

Du wirfst chaotische Notizen, Bilder oder Gedanken in die App. Die KI formatiert sie sachlich, strukturiert sie mit Listen und Admonitions (Callouts) und platziert sie in der richtigen Ordner-Struktur. Parallel dazu kannst du zu jedem beliebigen Thema einen "Kurs" oder ein "Buch" anlegen. Der KI-Tutor entwirft ein Curriculum und bringt dir die Lektionen bei. Wenn du eine Lektion verstanden hast, erzeugt die KI vollkommen autonom hochstrukturierte "Atomic Notes", die dauerhaft in deinem Zettelkasten verweilen — verbunden über den Knowledge-Graph.

Dies ist das ultimative Lern- und Recherchewerkzeug.

---

## Kernfunktionen im Detail

### 📝 Zettelkasten & Notizen
Das Herzstück des Systems. Hier sammelt sich dein Wissen.
- **KI-Aufbereitung**: Schicke einen chaotischen Gedanken oder Diktat. Das LLM formatiert es neutral, sachlich und scan-bar. Es erstellt Markdown-Elemente, Überschriften und spezifische Callouts (`[!MERKSATZ]`, `[!BEISPIEL]`, `[!DEFINITION]`).
- **Ordner-Organisation**: Das System schlägt automatisch vor, wo die Notiz auf Basis deiner bestehenden Struktur abgelegt werden soll. Es erzeugt auch automatisch fehlende Ordner.
- **TipTap Rich Text Editor**: Bearbeite Notizen wie in Word, aber basierend auf Markdown. Inklusive Syntax-Highlighting für Code-Blöcke und direkter Bild-Integration.
- **Versionsverlauf**: Bei jeder Bearbeitung (manuell oder durch KI) wird eine Version gespeichert, sodass du immer auf alte Stände zurücksetzen kannst.

### 🎓 Infinite Teacher (Kurse)
Der beste Weg, um sich abstraktes Wissen anzueignen.
- **Curriculum-Generierung**: Frag nach "Quantenmechanik". Das System greift auf Google Search API und Gemini zu, um einen strukturierten Lehrplan mit Modulen und messbaren Lernzielen zu erstellen.
- **Interaktiver Chat**: Du chattest mit einem sachlichen, warmherzigen KI-Lehrer (im Du-Format), der dir die Konzepte schrittweise erklärt.
- **Atomic Notes Generierung**: Klickst du in der Lektion auf **"Verstanden"**, analysiert die KI den gesamten Chat-Verlauf und extrahiert daraus saubere, strukturierte Notizen (inklusive einer übergeordneten Lektions-Notiz sowie isolierten Detail-Notizen).
- **Zero-Latency Navigation**: Im Hintergrund (Background Tasks / Threading) wird das nächste Kapitel oder die nächste Lektion bereits initialisiert und gegrüßt, sodass beim Klick auf "Nächstes Kapitel" keine Wartezeit entsteht.

### 📖 Interactive Book Teacher
Bücher lassen sich perfekt als Lehrmedien einsetzen.
- **Buch-Suche & Ingestion**: Suche per Titel/ISBN. Das System zieht sich über Google das Inhaltsverzeichnis (TOC) und legt ein Kurs-Modell pro Kapitel an.
- **Kapitel lernen**: Du besprichst das Kapitel mit dem KI-Tutor. Da der Tutor dank RAG und Google Search Zugriff auf Detailwissen zum Buch hat, fungiert er als interaktiver Sparring-Partner.
- **Buch-Zusammenfassungen**: Beim Beenden eines Kapitels baut die KI im Prizip des Zettelkastens extrem strukturierte Lexikoneinträge in den Ordner `Bücher/[Buch-Titel]/`.

### 🔍 RAG & Hybrid Search
Dein gesammeltes Wissen ist jederzeit verfügbar.
- **Hybrid Search**: Nutzt Vektor-Ähnlichkeit (Qdrant + `gemini-embedding-001`) gemischt mit klassischem Full-Text-Search (PostgreSQL `tsvector`) durch Reciprocal Rank Fusion. Ein extrem starker Suchmechanismus.
- **Chat mit dem "Brain"**: Stell eine Frage wie *"Was habe ich letzte Woche über Rust gelernt?"* – Das RAG-System sucht die Notizen, gibt Zitate aus und formuliert eine intelligente Antwort mit korrekten Quellen (Dateipfaden).

### 🖼️ AI Vision Pipeline
Nie mehr unstrukturierte Screenshots.
- **Auto-Beschreibungen**: Lädst du ein Bild hoch (oder via Ctrl+V Copy/Paste in die Notiz), speichert das Backend es lokal und schickt es sofort in den Hintergrund an Gemini Vision 3 Flash.
- **OCR & RAG Embedding**: Gemini liefert eine detailierte Bildbeschreibung zurück. Diese wird dem Bild als Meta-Daten beigefügt und dann ebenfalls in Qdrant eingebettet! Du kannst nach dem Inhalt von Screenshots suchen.

### 🕸️ Knowledge Graph & Auto-Linking
Informationen stehen nicht für sich allein.
- **KI-Auto-Linker**: Nach jeder neuen Notiz sucht ein Background Task (um den Event-Loop nicht zu blockieren) asynchron nach semantisch extrem verwandten Elementen in Qdrant und lässt Gemini bewerten, ob eine harte Verlinkung Sinn macht.
- **Visualisierung**: Eine 2D/3D Graph-Ansicht zeigt dir visuell, wie die Knotenpunkte in deinem Gehirn zusammenhängen.

### 📚 Spaced Repetition
Inhalte, die man nicht vergisst.
- **Flashcard-Generator**: Lass dir pro Notiz oder sogar gebündelt für einen ganzen "Ordner" 5-20 Lernkarten (Frage / Antwort) via LLM generieren.
- **Revisions-System**: Nutzt den SuperMemo-2 (SM-2) Algorithmus. Deine tägliche Dosis Lernkarten berechnet ideal Intervalle (Easiness-Faktor).

---

## Architektur

Das System trennt strikt zwischen synchronem und asynchronem Verhalten, um ein responsives UX zu sichern:

```text
┌─────────────────────┐     ┌──────────────────────────┐     ┌─────────────────┐
│   Next.js 14        │────▶│    FastAPI                │────▶│  PostgreSQL    │
│   (Frontend)        │     │    (Backend)              │     │  (Notes, Users,│
│   TypeScript        │     │    Python 3.12            │     │   Images, Tags)│
│   Tailwind CSS      │     │                           │     └─────────────────┘
│   Zustand           │     │  ┌──────────────────┐     │     
│   TipTap Editor     │     │  │ Gemini API       │     │     ┌─────────────────┐
│   Excalidraw        │     │  │ - 3 Flash (LLM)  │     │────▶│  Qdrant         │
│   react-force-graph │     │  │ - Vision (Bilder)│     │     │  (Embeddings,   │
│   recharts          │     │  │ - Embedding 001  │     │     │   768d, COSINE) │
└─────────────────────┘     │  └──────────────────┘     │     └─────────────────┘
                            └──────────────────────────┘
```

**Performance-Aspekt**: Damit FastAPI bei schweren Gemini-API Aufrufen oder DB-Transaktionen nicht blockiert, liegen alle synchronen Requests (z.B. AI Generationen ohne Stream) in isolierten `asyncio.to_thread()` Headless-Calls.

---

## Projektstruktur

```bash
Brain/
├── backend/
│   ├── app/
│   │   ├── main.py                  # Entrypoint, FastAPI App, CORS Setup
│   │   ├── config.py                # Environment Variablen (Pydantic Setup)
│   │   ├── database.py              # Asyncpg SQLAlchemy Session
│   │   ├── models.py                # Postgres Relationen (User, Course, Note, Image...)
│   │   ├── schemas.py               # Pydantic Schemas (Request/Response validation)
│   │   ├── routes/                  # API Router (Chat, Folders, Notes, Settings, Images, RAG...)
│   │   └── services/                
│   │       ├── ai_service.py        # Gemini RAG, Notiz-Formatierung, Flashcards
│   │       ├── teacher_service.py   # Infinite Teacher (Chats + Atomic Notes)
│   │       ├── book_service.py      # Buch Import, TOC extraction, Buch Chat
│   │       ├── vector_service.py    # Vektor-Einbettung in Qdrant (RRF Logiken)
│   │       ├── vision_service.py    # Gemini Vision Integration für OCR/Bildanalyse
│   │       └── backup_service.py    # Nightly Snapshotting
│   ├── uploads/                     # Speichermedium für lokale RAG-Bilder
│   ├── requirements.txt             # Python Package Liste
│   └── Dockerfile                   # Railway/Dokku Container Build
├── frontend/
│   ├── src/
│   │   ├── app/                     # Next.js 14 App Router, Layout, CSS
│   │   ├── components/              # Modular UI Components (TeacherPanel, RichTextEditor...)
│   │   └── lib/                   
│   │       ├── api.ts               # Axios Abstraktion
│   │       ├── store.ts             # Globaler State (Zustand)
│   │       └── types.ts             # TS Interfaces passend zu Pydantic
│   ├── public/                      # Static Assets
│   ├── package.json                 # Node Dependencies
│   └── Dockerfile                   # Frontend Deployment Container
└── README.md
```

---

## Tech Stack

| Komponente | Technologie |
|-----------|-------------|
| **Frontend** | React (Next.js 14), Tailwind, Zustand, TipTap, Excalidraw, Recharts, react-markdown |
| **Backend API** | Python, FastAPI, Pydantic, Uvicorn |
| **Datenbank (SQL)** | PostgreSQL via SQLAlchemy (asyncpg) |
| **Vektordatenbank** | Qdrant (Docker) |
| **Künstliche Intelligenz** | Google Gemini (3 Flash, Vision, Text-Embedding-001) |
| **Suchalgorithmus** | Reciprocal Rank Fusion (Hybrid aus Semantik & Full-Text) |
| **Deployment** | Docker via Railway |

---

## Lokale Entwicklung

Voraussetzung: Python 3.12+, Node 20+, Docker (für Qdrant & ggf. Postgres)

**1. Qdrant Starten**
```bash
docker run -p 6333:6333 qdrant/qdrant
```

**2. Backend Setup**
```bash
cd backend
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# .env vorbereiten (GEMINI_API_KEY, DATABASE_URL, etc.)
cp .env.example .env

# Server starten
uvicorn app.main:app --reload
```

**3. Frontend Setup**
```bash
cd frontend
npm install

# .env.local anlegen
echo "NEXT_PUBLIC_API_URL=http://localhost:8000" > .env.local

npm run dev
```

Die App ist nun erreichbar unter `http://localhost:3000`.

---

## Deployment

Die Konfiguration ist perfekt für Plattformen wie **Railway**, **Render** oder **DigitalOcean** abgestimmt.

1. Baue die Postgres-Instanz auf.
2. Baue einen eigenen Service für das Qdrant Docker-Image und binde zwingend einen internen Storage Mount (`/qdrant/storage`) ein, ansonsten verlierst du bei jedem Deployment deine Vektoren.
3. Erzeuge die Environment-Variablen im Backend (Sicherstellen, dass `FRONTEND_URLS` gesetzt ist für CORS).
4. Übergebe beim Bauen des Frontends das Argument `NEXT_PUBLIC_API_URL`.

**Hinweis zum Backup-System:** 
Das System erzeugt über den `backup_service.py` jeden Tag um 03:00 Uhr UTC einen physischen Qdrant-Snapshot in `/qdrant/storage`, der im Falle eines Systemabsturzes extrem einfach importiert werden kann.

---

*Wissen wächst, wenn man es teilt. Viel Spaß beim Lernen und Notieren!*
"""

with open("README.md", "w") as f:
    f.write(content)
print("Generiert!")
