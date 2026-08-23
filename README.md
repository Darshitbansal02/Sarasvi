<div align="center">

# Sarasvi (मेधा / Medhā)
### Deterministic Real-Time AI Whiteboard Teaching Platform with Dynamic Layout & Presentation Compilation

[![Live Demo](https://img.shields.io/badge/Live%20Demo-sarasvi.vercel.app-000000?style=for-the-badge&logo=vercel&logoColor=white)](https://sarasvi.vercel.app/)
[![Python](https://img.shields.io/badge/Python-3.12-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?style=for-the-badge&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![Next.js](https://img.shields.io/badge/Next.js-16.2-000000?style=for-the-badge&logo=nextdotjs&logoColor=white)](https://nextjs.org)
[![React](https://img.shields.io/badge/React-19.2-61DAFB?style=for-the-badge&logo=react&logoColor=black)](https://react.dev)
[![PixiJS](https://img.shields.io/badge/PixiJS-8.7-E72264?style=for-the-badge&logo=pixijs&logoColor=white)](https://pixijs.com)
[![SymPy](https://img.shields.io/badge/SymPy-1.13-3B5526?style=for-the-badge&logo=sympy&logoColor=white)](https://sympy.org)
[![Docker](https://img.shields.io/badge/Docker-Compose-2496ED?style=for-the-badge&logo=docker&logoColor=white)](https://docker.com)
[![License](https://img.shields.io/badge/License-MIT-blue.svg?style=for-the-badge)](LICENSE)

<p align="center">
  <b>Transforming high-level STEM concepts into real-time, mathematically-verified, audio-visually synchronized whiteboard lectures.</b>
  <br />
  <a href="https://sarasvi.vercel.app/"><strong>Explore the Live Whiteboard »</strong></a>
</p>

[🌐 Live Demo](https://sarasvi.vercel.app/) • [Key Features](#-key-features--innovations) • [System Architecture](#-system-architecture) • [Getting Started](#-getting-started) • [API & WebSocket Reference](#-api--websocket-protocol) • [Benchmarks](#-empirical-benchmarks--evaluation)

</div>

---

## 📌 Overview

Traditional AI tutoring tools generally fall into two suboptimal extremes:
1. **Text-Only Conversational Chatbots:** Incapable of conveying spatial geometry, multi-step mathematical derivations, or visual diagrams essential for STEM education.
2. **Pre-rendered Educational Video Generators (e.g., Manim / Video Diffusion):** Suffer from severe rendering latencies ($30\text{s}$–$60\text{s}$), static non-adaptive pacing, and unverified visual hallucinations.

**Sarasvi** resolves this dichotomy through a **neuro-symbolic presentation compilation architecture**. Rather than generating heavy pixel video streams, Sarasvi:
* Formulates a verified instructional plan into a **Teaching Abstract Syntax Tree (TeachingAST)**.
* Compiles AST nodes into deterministic vector stroke primitives (`_charStates`) with stroke-level reveal schedules.
* Dynamically reconciles acoustic speech timings (TTS) with vector pen stroke schedules.
* Streams timed events via WebSockets to a high-performance **PixiJS 2D canvas** that renders natural teacher handwriting, animated diagrams, and synchronized voice narration in **sub-1.2s first paint latency**.

---

## ✨ Key Features & Innovations

### 🧠 3-Call Neuro-Symbolic Teaching Pipeline
* **Call 1 (Pedagogical Planning):** Assesses query depth, concept dependencies, and curriculum banding.
* **Call 2 (Skeleton & Procedural Expansion):** Synthesizes structured segments with visual diagrams and derivations.
* **Call 3 (Formal Verification & AST Generation):** Translates procedural actions into verified `TeachingAST` instructions.
* **Streaming Segment Chunking:** Emits the first verified segment to the client within **$1.2\text{s}$**, streaming downstream segments in parallel.

### 🛡️ Fail-Closed Formal Verification Gateway
* Integrates formal solvers (**SymPy**, dimensional analysis, stoichiometry checkers, algorithm invariant provers) into the LLM synthesis loop.
* Validates algebraic equalities ($\text{lhs} \equiv \text{rhs}$), calculus limits, integration boundaries, and chemical balance before visual compilation.
* Automatically triggers localized repair prompts upon claim rejection or **fails closed** (`PlanRejectedError`) to prevent educational hallucinations.

### 📐 Dynamic Spatial Whiteboard Layout Manager
* **Intelligent Collision Avoidance:** Replaces naive stacking with dynamic spatial region allocation and bounding-box optimization, reducing coordinate overlaps by **85.9%**.
* **Equation Autoscaling (`_fit_equation_font`):** Dynamically scales multi-line equations and complex matrices to prevent viewport overflow.
* **Interactive Doubt Reflow & Page Cascading:** When a student interrupts with a question, Sarasvi calculates remaining page budget, dynamically reflows annotations, answers in place, and cascades downstream content to subsequent pages.

### ✍️ Vector AST Glyph Compiler & Universal Primitives
* Every visual element decomposes cleanly into **four universal primitives**:
  1. `draw_stroke`: Parametric vector paths, pressure attributes, and handwritten equation glyphs.
  2. `annotation`: Typographic callouts and textual labels.
  3. `graph_node`: Positioned network, tree, and state diagram nodes.
  4. `graph_edge`: Dynamic directed connectors and relation arrows.
* Zero character-splitting fallbacks: LaTeX math is compiled directly into handwritten vector stroke paths.

### 🎙️ Audio-Visual Synchronization & Audio Authority Gate
* **Acoustic-Visual Reconciliation:** Pre-measures synthesized TTS audio durations and linearly shifts stroke reveal timings (`_charStates`) so handwriting perfectly tracks voice cadence.
* **Client Audio Authority Gate:** The frontend holds visual ink rendering until the audio timeline clock begins playback, ensuring drift-free synchronization across all connection speeds.

### 🖼️ Multimodal Question Ingestion
* Built-in multimodal image extraction (`POST /api/sessions/extract-image`) extracts problem statements, equations, and diagrams from uploaded photos of homework or textbooks.

### 🎬 Interactive Whiteboard Controls & Session Replay
* Full playback control: Pause, play, scrub timeline, variable playback speed ($0.5\times$ to $2.0\times$), multi-page navigation, and canvas pan/zoom.
* Every session is stored as a persistent, serialized event stream for bookmarking, sharing, and instant offline replay.

---

## 🏗️ System Architecture

Sarasvi strictly enforces architectural layer separation between **backend presentation compilation** (authoritative layout, timing, and verification) and **frontend canvas rendering** (layout-free execution).

```mermaid
flowchart TD
    User([Student / User]) -->|Topic or Doubt Input| API[FastAPI Session Gateway]
    
    subgraph Backend ["Backend Pipeline (Python 3.12 / FastAPI)"]
        API --> ReasoningCore[ReasoningCore: 3-Call LLM Planning]
        ReasoningCore --> Gateway[Verification Gateway\nSymPy / Domain Solvers]
        
        Gateway -->|Verified Claims| TeachingAST[TeachingAST Formulation]
        Gateway -->|Failed Claim| Repair[Auto-Repair Prompt / Fail Closed]
        Repair --> ReasoningCore
        
        TeachingAST --> PresentationCompiler[Presentation Compiler]
        
        subgraph Compilers ["Compilation Engine"]
            PresentationCompiler --> WhiteboardMgr[Whiteboard Layout Manager\nSpatial Regions & Font Fit]
            PresentationCompiler --> GlyphCompiler[AST Glyph Compiler\nVector Stroke Schedules]
            PresentationCompiler --> Choreographer[Teaching Choreographer & Motion Planner]
        end
        
        Compilers --> AudioReconcile[TTS Synthesis & Duration Reconciliation\nLinear _charStates Rescaling]
        AudioReconcile --> EventBus[EventBus & NDJSON Serializer]
    end
    
    EventBus -->|WebSocket Stream /ws/{id}| WSClient[Next.js WebSocket Client]
    
    subgraph Frontend ["Frontend Engine (Next.js 16 / React 19 / PixiJS 8)"]
        WSClient --> RuntimeStore[Zustand Runtime Store & Event Queue]
        RuntimeStore --> AudioGate[Audio Authority Gate]
        AudioGate --> TTSPlayer[TTS Audio Timeline Player]
        AudioGate --> TeacherMotor[Teacher Motor & Construction Runtime]
        TeacherMotor --> PixiCanvas[PixiJS 2D Canvas Renderer]
    end
    
    PixiCanvas -->|Synchronized Whiteboard Lecture| User
```

---

## 📂 Repository Structure

```
.
├── backend/                        # FastAPI Backend Application
│   ├── alembic/                    # Database migration scripts
│   ├── app/
│   │   ├── agents/                 # Domain-specific pedagogical agents
│   │   ├── api/                    # REST route controllers (sessions, auth, users, health)
│   │   ├── config/                 # Pydantic settings & environment configuration
│   │   ├── database/               # Async SQLAlchemy engine & session factories
│   │   ├── domains/                # STEM domain knowledge rules (math, physics, chem, dsa)
│   │   ├── dsl/                    # DSL primitives & type specifications
│   │   ├── events/                 # EventBus, event protocols, NDJSON streaming, store
│   │   ├── human_stroke_engine/    # Human-like drawing dynamics & pen jitter
│   │   ├── layouts/                # WhiteboardManager, spatial regions, document flow
│   │   ├── models/                 # SQLAlchemy ORM models (User, Session, EventStore)
│   │   ├── pedagogy/               # Socratic reasoning, strategy, and misconception models
│   │   ├── reasoning/              # ReasoningCore (3-call pipeline, prompt templates)
│   │   ├── scene_graph/            # Spatial scene graph & collision management
│   │   ├── schemas/                # Pydantic request/response schemas
│   │   ├── services/               # Presentation compiler, glyph compiler, TTS planner
│   │   ├── student_model/          # Cognitive load & mastery tracking models
│   │   ├── teaching_ast/           # Teaching Abstract Syntax Tree definitions
│   │   ├── utils/                  # Resilient LLMClient (Gemini/Groq routing, rate-limiting)
│   │   ├── verification/           # SymPy, physics, chemistry, and algorithm verifiers
│   │   └── websocket/              # Real-time WebSocket gateway & connection manager
│   ├── Dockerfile                  # Backend production Docker container
│   ├── requirements.txt            # Python dependencies
│   ├── test_paper_benchmarks.py    # Automated paper evaluation & benchmark suite
│   └── test_glyph_compiler.py      # LaTeX glyph compilation test suite
│
├── frontend/                       # Next.js 16 + PixiJS 8 Frontend
│   ├── src/
│   │   ├── app/                    # Next.js App Router (dashboard, session, replay, profile)
│   │   ├── components/             # React UI components, PixiCanvas, session controls
│   │   │   ├── canvas/             # PixiJS canvas viewport & sceneRenderer
│   │   │   ├── session/            # Lesson controls, chat/doubt drawer, timeline scrubber
│   │   │   └── ui/                 # Accessible UI design system primitives
│   │   ├── lib/                    # WebSocket client, API fetch client, utilities
│   │   ├── runtime/                # Whiteboard runtime engine & Audio Authority Gate
│   │   │   ├── audio/              # AudioTimeline, TTSPlayer, speech synchronizer
│   │   │   ├── motion/             # ConstructionRuntime, TeacherMotor, gesture dynamics
│   │   │   └── runtimeStore.ts     # Core Zustand event queue & playback state store
│   │   └── types.ts                # TypeScript interfaces & event payloads
│   ├── package.json                # Frontend dependencies & build scripts
│   └── tailwind.config.js          # Tailwind CSS styling configuration
│
├── docker-compose.yml              # Multi-container local orchestration (Postgres + Backend)
├── render.yaml                     # Cloud deployment configuration for Render
├── research_paper_draft.md         # Scientific systems paper & methodology
└── sarasvi_ieee_paper.tex          # IEEE-formatted publication manuscript
```

---

## 🛠️ Technology Stack

| Layer | Technologies |
| :--- | :--- |
| **Backend Framework** | [FastAPI](https://fastapi.tiangolo.com/), [Uvicorn](https://www.uvicorn.org/), [Pydantic v2](https://docs.pydantic.dev/) |
| **Frontend Framework** | [Next.js 16 (App Router)](https://nextjs.org/), [React 19](https://react.dev/), [TypeScript](https://www.typescriptlang.org/) |
| **Whiteboard Graphics Engine** | [PixiJS 8](https://pixijs.com/) (WebGL / WebGPU 2D Acceleration), [Framer Motion](https://www.framer.com/motion/) |
| **State & Playback Management**| [Zustand 5](https://zustand-demo.pmnd.rs/), Custom Event Queue with Audio Authority Gate |
| **Formal Verification & Math** | [SymPy](https://www.sympy.org/), [Lark Parser](https://github.com/lark-parser/lark), [NumPy](https://numpy.org/), [SciPy](https://scipy.org/), [Shapely](https://shapely.readthedocs.io/) |
| **Voice & Narration (TTS)**   | [Edge-TTS](https://github.com/rany2/edge-tts) (`en-IN-NeerjaNeural` / multi-voice support) |
| **AI & LLM Orchestration**     | Google Gemini API (`gemini-2.5-flash`), Groq (`llama-3.3-70b-versatile`), Custom rate-limited `LLMClient` |
| **Database & Persistence**     | [PostgreSQL 16](https://www.postgresql.org/) with [pgvector](https://github.com/pgvector/pgvector), [SQLAlchemy 2.0 Asyncio](https://www.sqlalchemy.org/), [Alembic](https://alembic.sqlalchemy.org/) (SQLite for local dev) |
| **Real-Time Streaming**        | Native WebSockets, NDJSON streaming protocol, In-memory / Redis PubSub |
| **Observability & Logging**    | [Structlog](https://www.structlog.org/), [Prometheus](https://prometheus.io/), [OpenTelemetry](https://opentelemetry.io/) |
| **Containerization & Cloud**   | [Docker](https://www.docker.com/), [Docker Compose](https://docs.docker.com/compose/), [Render](https://render.com/) |

---

## 🚀 Getting Started

### Prerequisites
* **Python:** 3.12+
* **Node.js:** 18.x or 20.x+
* **Package Managers:** `pip` and `npm`
* **Docker & Docker Compose** (Optional for containerized run)
* **API Keys:** Google Gemini API Key or Groq API Key (Optional: works with `stub` mode for offline testing)

---

### Option A: Local Development Setup

#### 1. Clone the Repository
```bash
git clone https://github.com/Darshitbansal02/Sarasvi.git
cd Sarasvi
```

#### 2. Backend Setup
```bash
cd backend

# Create and activate Python virtual environment
python -m venv .venv

# On Windows (PowerShell):
.venv\Scripts\Activate.ps1
# On Linux/macOS:
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Configure environment variables
cp .env.example .env
```

Edit `backend/.env` with your preferred settings and API keys:
```ini
ENVIRONMENT=development
LOG_LEVEL=DEBUG
GEMINI_API_KEY=your_gemini_api_key_here
GROQ_API_KEY=your_groq_api_key_here
CORS_ORIGINS=["http://localhost:3000"]
```

Run the backend development server (SQLite database will initialize automatically):
```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```
* Backend Swagger Docs: [http://localhost:8000/docs](http://localhost:8000/docs)
* Health Check: [http://localhost:8000/api/health](http://localhost:8000/api/health)

#### 3. Frontend Setup
Open a new terminal window:
```bash
cd frontend

# Install Node modules
npm install

# Run frontend development server
npm run dev
```
Open [http://localhost:3000](http://localhost:3000) in your browser to launch the whiteboard interface.

---

### Option B: Docker Compose Full Stack

To start PostgreSQL and the backend service simultaneously:
```bash
docker-compose up --build
```
Then start the frontend:
```bash
cd frontend && npm install && npm run dev
```

---

## ⚙️ Environment Variables Reference

### Backend (`backend/.env`)

| Variable | Default | Description |
| :--- | :--- | :--- |
| `ENVIRONMENT` | `development` | Environment mode (`development` or `production`). |
| `LOG_LEVEL` | `INFO` | Logging verbosity (`DEBUG`, `INFO`, `WARNING`, `ERROR`). |
| `DATABASE_URL` | `sqlite+aiosqlite:///./Sarasvi.db` | Async SQLAlchemy database URI (PostgreSQL in production). |
| `DATABASE_URL_SYNC` | `sqlite:///./Sarasvi.db` | Sync database URI for Alembic migrations. |
| `GEMINI_API_KEY` | `stub` | Google Gemini API key for `ReasoningCore`. |
| `GEMINI_MODEL` | `gemini-2.5-flash` | Gemini model identifier. |
| `GROQ_API_KEY` | `stub` | Groq API key for high-speed fallback synthesis. |
| `GROQ_MODEL_STRONG`| `llama-3.3-70b-versatile` | Primary Groq model. |
| `CORS_ORIGINS` | `["http://localhost:3000"]` | Allowed CORS origins (JSON array). |
| `JWT_SECRET_KEY` | `dev-insecure-...` | Secret key for JWT session tokens (Change in prod!). |
| `TTS_VOICE` | `en-IN-NeerjaNeural` | Edge-TTS voice identifier. |
| `PUBSUB_BACKEND` | `memory` | Pub/Sub backend (`memory` for single-instance, `redis` for cluster). |
| `REDIS_URL` | `redis://localhost:6379/0`| Redis connection URI when `PUBSUB_BACKEND=redis`. |

### Frontend (`frontend/.env.local`)

| Variable | Default | Description |
| :--- | :--- | :--- |
| `NEXT_PUBLIC_API_URL` | `http://localhost:8000/api` | Base HTTP endpoint for the FastAPI backend. |
| `NEXT_PUBLIC_API_WS_URL` | `ws://localhost:8000` | Base WebSocket endpoint for event streaming. |

---

## 📡 API & WebSocket Protocol

### REST API Endpoints

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `GET` | `/api/health` | Service health status and database connectivity. |
| `GET` | `/api/sessions/topics` | List suggested curated STEM topics. |
| `GET` | `/api/sessions` | List teaching sessions for current user. |
| `POST` | `/api/sessions` | Create a new teaching session. |
| `GET` | `/api/sessions/{id}` | Fetch session metadata and status. |
| `POST` | `/api/sessions/{id}/teach` | Trigger AI lesson generation and streaming for a topic. |
| `POST` | `/api/sessions/{id}/interrupt` | Ask a doubt/question mid-lesson; triggers dynamic whiteboard reflow. |
| `POST` | `/api/sessions/extract-image` | Multimodal OCR/Vision extraction from uploaded problem image. |
| `GET` | `/api/sessions/{id}/events` | Retrieve complete serialized event stream for session playback. |
| `GET` | `/api/sessions/{id}/page-status`| Get current spatial page layout budget and pagination state. |

### WebSocket Protocol (`/ws/{session_id}`)

Clients connect to `/ws/{session_id}` to receive real-time NDJSON event frames:

```json
{
  "event_id": "01JMB8...",
  "session_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "type": "equation_write",
  "start_ms": 3200,
  "duration_ms": 1800,
  "page_number": 1,
  "payload": {
    "latex": "\\int_{0}^{\\infty} e^{-x^2} dx = \\frac{\\sqrt{\\pi}}{2}",
    "x": 120.0,
    "y": 240.0,
    "font_size": 24.0,
    "_charStates": [
      { "char": "\\int", "start_offset_ms": 0, "duration_ms": 300 },
      { "char": "e^{-x^2}", "start_offset_ms": 300, "duration_ms": 500 },
      { "char": "dx", "start_offset_ms": 800, "duration_ms": 200 },
      { "char": "=", "start_offset_ms": 1000, "duration_ms": 150 },
      { "char": "\\frac{\\sqrt{\\pi}}{2}", "start_offset_ms": 1150, "duration_ms": 650 }
    ]
  }
}
```

#### Event Lifecycle
1. `generation_start`: Dispatches compiled scene metadata, audio stream, and initial layout assets.
2. `speech`: Audio narration segment accompanied by timing marks.
3. `equation_write` / `draw_stroke`: Vector ink primitives executed by the Teacher Motor.
4. `graph_node` / `graph_edge`: Topological diagram constructions.
5. `page_break`: Automatic pagination and canvas transition.
6. `generation_end`: Signals completion of the lesson segment.

---

## 📊 Empirical Benchmarks & Evaluation

Sarasvi includes an automated scientific benchmark suite (`test_paper_benchmarks.py`) evaluated across synthetic workloads ($n=250$) and live multi-domain STEM prompts (Algebra, Calculus, Physics, Algorithms, Chemistry):

| Metric / Evaluation Attribute | Measured Result | Benchmark Baseline |
| :--- | :---: | :---: |
| **AST Compilation Latency** | **$117.84\text{ ms}$** median ($\mu=119.27\text{ ms}$) | $< 500\text{ ms}$ real-time threshold |
| **Numerical Coordinate Stability** | **$0.00\%$** `NaN` / `Inf` failures | $100\%$ valid geometric points |
| **Compilation Determinism** | **$100.00\%$** SHA-256 Hash Match ($n=100$) | Cryptographically reproducible |
| **Spatial Bounding-Box Overlap** | **$85.9\%$** Overlap Reduction | Compared to naive vertical stacking |
| **Progressive First Visual Paint** | **$< 1.20\text{ s}$** via segment chunking | vs. $30\text{s}$–$60\text{s}$ video synthesis |
| **Peak Heap Memory Allocation** | **$2.41\text{ MB}$** per compilation cycle | Zero unbounded memory leaks |

### Running the Evaluation Suite
```bash
cd backend
python test_paper_benchmarks.py
python test_glyph_compiler.py
```

---

## 🧪 Testing & Verification

```bash
# Run unit and sanity tests
cd backend
python test_glyph_compiler.py       # LaTeX -> vector glyph layout sanity
python test_doubt_layout.py         # Mid-lesson interruption layout solver
python test_doubt_reflow.py         # Multi-page reflow & pagination test
python test_pipeline_stress.py      # Stress testing under concurrent payloads

# Run frontend test & linter
cd frontend
npm run lint
npm run build
```

---

## 🚢 Deployment

### Production Docker Deployment
```bash
docker build -t sarasvi-backend:latest ./backend
```

### Render Deployment (Backend)
The repository includes a ready-to-use [`render.yaml`](render.yaml) blueprint:
1. Connect your GitHub repository to Render.
2. Deploy the `sarasvi-backend` web service.
3. Set the required secret environment variables: `DATABASE_URL` (Supabase/PostgreSQL with pgBouncer), `GEMINI_API_KEY`, `JWT_SECRET_KEY`, and `CORS_ORIGINS`.

### Vercel Deployment (Frontend)
The Next.js frontend is deployed live at [sarasvi.vercel.app](https://sarasvi.vercel.app/):
1. Import the `frontend/` directory into [Vercel](https://vercel.com).
2. Configure Environment Variables:
   - `NEXT_PUBLIC_API_URL`: Your production backend HTTP URL (e.g. `https://sarasvi-backend.onrender.com/api`)
   - `NEXT_PUBLIC_API_WS_URL`: Your production backend WebSocket URL (e.g. `wss://sarasvi-backend.onrender.com`)
3. Deploy!

---

## 🤝 Contributing

Contributions, issues, and feature requests are welcome!
1. Fork the repository.
2. Create your feature branch (`git checkout -b feature/AmazingFeature`).
3. Commit your changes (`git commit -m 'feat: Add some AmazingFeature'`).
4. Push to the branch (`git push origin feature/AmazingFeature`).
5. Open a Pull Request.

---

## 📜 License

Distributed under the MIT License. See `LICENSE` for more information.

---

<div align="center">
  <sub>Engineered with precision for real-time interactive STEM education.</sub>
</div>
