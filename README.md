# ⚡ Mendix Gemini Copilot

An enterprise-grade, local AI-powered developer assistant designed for **Mendix Solution Architects & Engineers**. Powered by **Google Gemini 3.7 / 2.5 Flash**, it provides real-time microflow logic auditing, Segregation of Duties (SOD) validation, automated SCSS & UI design generation with live preview, and in-memory `.mpk` package extraction.

---

## 🌟 Key Features

* **🛡️ Architecture & Security Auditing:** Automatically audits microflows for Segregation of Duties (SOD), self-approval prevention, dirty object states, and single-commit transaction patterns.
* **📦 In-Memory `.mpk` Decompression:** Seamlessly extracts and parses Mendix Document and Module packages (`.mpk`) in RAM without polluting your disk.
* **🎨 UI/UX Styling with Live Preview:** Generates tailored SCSS code and Atlas UI class names, complete with an **in-chat interactive live visual rendering** of cards, badges, and layout containers.
* **🔍 Multi-Scope Inspection:**
  * **Single Microflow Focus:** Deep analysis of isolated microflows and expressions.
  * **Workflow Chain Check:** Transactional chain auditing from trigger (`ACT_`) to sub-microflows (`SUB_`) and notifications.
  * **Full Project Audit:** Local read-only directory scanning for comprehensive architectural reviews.
* **💬 Multi-Session Chat & Branching:** Persistent SQLite chat history with support for conversation tree branching (`Branch from here`), individual message deletion, and Markdown export.
* **🔒 100% Read-Only Safety:** Operates strictly with non-mutating file handlers, guaranteeing zero risk of `.mpr` project file corruption.

---

## 🏗️ System Architecture

```text
┌────────────────────────────────────────────────────────────────────────┐
│                       PRESENTATION LAYER (STREAMLIT)                   │
│  ┌─────────────────────────┐  ┌─────────────────────────────────────┐  │
│  │   Sidebar Controls      │  │      Main Chat & Ingestion Area     │  │
│  │ • Session Manager       │  │ • Multi-Scope Selector (1/Chain/All)│  │
│  │ • Gemini Model Selector │  │ • Multi-File Ingestion (.mpk/png)   │  │
│  │ • Prompt Presets        │  │ • Live HTML/UI Component Preview    │  │
│  │ • Local Path Config     │  │ • Streaming Markdown Response       │  │
│  └─────────────────────────┘  └─────────────────────────────────────┘  │
└────────────────────────────────────┬───────────────────────────────────┘
                                     │
┌────────────────────────────────────▼───────────────────────────────────┐
│                           APPLICATION ENGINE                           │
│  ┌───────────────────────┐  ┌───────────────────────┐  ┌─────────────┐ │
│  │ Mendix Parser         │  │ Gemini Client         │  │ SQLite DB   │ │
│  │ • In-Memory .mpk zip  │  │ • Google GenAI SDK    │  │ (chats.db)  │ │
│  │ • Multimodal Vision   │  │ • Dynamic System Prom │  │ • Sessions  │ │
│  │ • Local SCSS Reader   │  │ • Token Streamer      │  │ • Messages  │ │
│  └───────────────────────┘  └───────────────────────┘  └─────────────┘ │
└────────────────────────────────────────────────────────────────────────┘