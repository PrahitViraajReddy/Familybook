<div align="center">

# 🌳 VanshaVriksha

**A family tree and family-management application for bringing relatives, memories, and milestones together.**

<p>
  <a href="https://familybook-7ff4.onrender.com/"><img alt="Live App" src="https://img.shields.io/badge/Live%20App-Visit-2ea44f?style=flat-square"></a>
  <img alt="Python" src="https://img.shields.io/badge/Python-3.x-3776AB?style=flat-square&logo=python&logoColor=white">
  <img alt="Streamlit" src="https://img.shields.io/badge/UI-Streamlit-FF4B4B?style=flat-square&logo=streamlit&logoColor=white">
  <img alt="PostgreSQL" src="https://img.shields.io/badge/Database-PostgreSQL-4169E1?style=flat-square&logo=postgresql&logoColor=white">
  <img alt="License" src="https://img.shields.io/badge/License-Not%20specified-lightgrey?style=flat-square">
</p>

[**Open the live app**](https://familybook-7ff4.onrender.com/) · [**View source code**](https://github.com/PrahitViraajReddy/Familybook)

</div>

---

## What is VanshaVriksha?

VanshaVriksha (Familybook) is a database-backed family platform built with **Python, Streamlit, and PostgreSQL**. It brings family relationships and everyday family memories into one place, with tools for managing member profiles, exploring connections, sharing albums, writing diary entries, and recording important events.

Rather than treating a family tree as a static diagram, the application stores family information in a relational database so supported records can be revisited and managed across sessions.

## Features

- **Profiles and authentication** — user registration and login, profile details, profile photos, password hashing with bcrypt, and privacy controls.
- **Family relationships** — connect registered members, record unregistered relatives, define relationship types, and organize members by family or dynasty.
- **Family tree and discovery** — explore family connections and search for members within a family network.
- **Family albums** — organize photos and media with captions, dates, locations, tags, comments, reactions, and privacy settings.
- **Family diary** — create personal or shared entries with dates, tags, mood information, drafts, and visibility options.
- **Family timeline** — preserve important family events and milestones in chronological order.
- **Activity and interaction** — support activity information and social interactions around shared family media.

Feature visibility and access depend on the application's available controls and privacy settings.

## How it works

```text
User
  │
  ▼
Streamlit interface
  │
  ▼
Python application logic
  │
  ▼
psycopg2 + connection pool
  │
  ▼
PostgreSQL database (Supabase)
```

The Streamlit application handles the user interface and application workflows. Python communicates with PostgreSQL through `psycopg2`. A threaded connection pool, connection-liveness checks, and TCP keepalive settings help manage database connections during longer sessions. The application initializes its required tables during startup.

## Technology stack

| Layer | Technology |
|---|---|
| Language | Python |
| Web interface | Streamlit |
| Relational database | PostgreSQL |
| Database hosting | Supabase |
| Database driver | `psycopg2-binary` |
| Connection management | `ThreadedConnectionPool` |
| Password hashing | `bcrypt` |
| Image handling | Pillow |
| Deployment | Render |

## Database overview

The application uses relational tables for the main parts of the family platform.

| Table | Purpose |
|---|---|
| `users` | Accounts, profiles, and privacy settings |
| `family_links` | Relationships between family members |
| `otp_store` | Temporary one-time-password records |
| `family_albums` | Album details and privacy |
| `album_media` | Media records and associated metadata |
| `media_reactions` | Reactions to shared media |
| `media_comments` | Comments on shared media |
| `family_diary` | Diary entries and related metadata |
| `family_timeline` | Family events and milestones |

Foreign keys help maintain relationships between related records. Delete behavior is defined at the database level where applicable.

## Quick start

### 1. Clone the repository

```bash
git clone https://github.com/PrahitViraajReddy/Familybook.git
cd Familybook
```

### 2. Create a virtual environment

```bash
python -m venv .venv
```

Activate it:

**Windows**
```powershell
.venv\Scripts\Activate.ps1
```

**macOS / Linux**
```bash
source .venv/bin/activate
```

### 3. Install dependencies

```bash
python -m pip install --upgrade pip
pip install -r requirements.txt
```

The current requirements include Streamlit, psycopg2-binary, bcrypt, and Pillow.

### 4. Configure the database

Create or select a PostgreSQL database and configure its connection string as `POSTGRES_URI` using Streamlit secrets or your deployment environment.

For local development, create `.streamlit/secrets.toml`:

```toml
POSTGRES_URI = "your-postgresql-connection-string"
```

Use your own database connection string. **Never commit real credentials or secrets to GitHub.** For a hosted database, use the provider's required SSL connection settings.

### 5. Run the app

```bash
streamlit run app.py
```

Streamlit will print a local URL in the terminal. Open that URL in your browser.

## Repository structure

```text
Familybook/
├── .devcontainer/       # Development container configuration
├── .streamlit/          # Streamlit configuration
├── app.py               # Main application
├── requirements.txt     # Python dependencies
└── readme.md             # Project documentation
```

## Security and privacy notes

Family information can be sensitive. The application includes bcrypt password hashing, secrets/environment-based database configuration, SSL database connections, and privacy controls for supported profile, diary, and album content.

For any public deployment:

- Use authorized test data rather than exposing private family information.
- Keep database credentials and authentication secrets out of source control.
- Review access controls, file/media storage, backups, and retention before using the app with real personal data.
- Treat the live deployment as a demonstration unless its current security and operational setup has been independently reviewed.

## Engineering highlights

This project brings together practical application-development concepts:

- Multi-feature web application development with Streamlit
- Relational data modeling and PostgreSQL queries
- User authentication and password hashing
- Foreign-key relationships and database integrity
- Database connection pooling and connection health checks
- Media metadata and privacy-aware workflows
- Configuration through environment variables and application secrets
- Deployment of a Python application connected to a hosted database

## Links

- **Live application:** https://familybook-7ff4.onrender.com/
- **GitHub repository:** https://github.com/PrahitViraajReddy/Familybook

---

<div align="center">

Built with Python, Streamlit, and PostgreSQL.

</div>
