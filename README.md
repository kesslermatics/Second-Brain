# Brain - Second Brain Application

A personal knowledge management system with AI-powered note creation and RAG-based Q&A.

## Architecture

- **Backend**: FastAPI (Python) + PostgreSQL + Qdrant Vector DB
- **Frontend**: Next.js 14 (TypeScript) + Tailwind CSS
- **AI**: Google Gemini API for embeddings and LLM

## Features

- 🧠 **Smart Note Creation**: Tell the AI your notes, it structures and stores them
- 🔍 **RAG Q&A**: Ask questions and get answers from your knowledge base
- 📁 **Folder Structure**: Organize notes in a hierarchical folder system
- ✏️ **AI-Powered Editing**: Let AI edit your notes based on instructions
- 💬 **Chat History**: Manage multiple chat sessions
- 🔐 **Authentication**: Secure login system

## Setup

### Backend

```bash
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

## Environment Variables

See `.env` files in `backend/` and `frontend/` directories.
