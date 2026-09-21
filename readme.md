# 🌳 VanshaVriksha — Family Tree & Family Management App

A full-featured family management web application built with **Python, Streamlit, and PostgreSQL**. VanshaVriksha combines family relationships, profiles, albums, diary entries, and family events into one interactive application.

🔗 **Live App:** https://familybook-7ff4.onrender.com/

---

## 🎯 Project Overview

VanshaVriksha is designed as a persistent, multi-user family platform rather than a static family-tree visualizer.

The application supports:

- User registration and profile management
- Family relationship management
- Interactive family-tree views
- Family albums and media
- Private/shared diary entries
- Family timelines and events
- Dynasty/member discovery
- Activity and social interactions
- Privacy controls

The application stores user and family data in PostgreSQL and uses Streamlit for the web interface.

---

## ✨ Core Features

### 👤 Profiles & Authentication
- User registration and login
- Profile information and biography
- Profile photo support
- bcrypt password hashing
- Email-based OTP storage
- Privacy controls for selected profile information

### 👨‍👩‍👧‍👦 Family Relationships
- Connect registered family members
- Add unregistered relatives
- Store custom relationship types
- Organize members under a dynasty/family name
- Generate family relationship views

### 🌳 Family Tree
- Interactive representation of linked family members
- Relationship-aware family navigation
- Family information displayed from persistent database records

### 📸 Family Albums
- Create family albums
- Upload photo/media content
- Captions, locations, tags, and dates
- Album privacy settings
- Reactions and comments

### 📖 Family Diary
- Create personal or shared diary entries
- Tags and mood tracking
- Draft support
- Entry dates and timestamps
- Privacy options

### 📅 Family Timeline
- Record important family events
- Event types, dates, locations, and tags
- Chronological family history

### 🔍 Family Discovery & Activity
- Search for members within a dynasty
- Activity information across the family network
- Social interactions around shared media

---

## 🏗️ Application Architecture

The project follows a Streamlit + PostgreSQL application architecture:

**Streamlit UI → Application Logic → PostgreSQL Connection Pool → PostgreSQL Database**

The application uses a threaded PostgreSQL connection pool with connection liveness checks and TCP keepalive settings to handle long-running Streamlit sessions more reliably.

Database credentials are read from Streamlit secrets or the deployment environment rather than being hard-coded into the application.

---

## 🗄️ Database Design

The application initializes its database tables when the application starts.

| Table | Purpose |
|---|---|
| `users` | User accounts, profiles, privacy settings |
| `family_links` | Relationships between family members |
| `otp_store` | Temporary OTP records |
| `family_albums` | Album metadata and privacy |
| `album_media` | Photos/media and metadata |
| `media_reactions` | Reactions on uploaded media |
| `media_comments` | Comments on media |
| `family_diary` | Diary entries, tags, mood and privacy |
| `family_timeline` | Family events and milestones |

Relationships use PostgreSQL foreign keys with cascading or nullifying delete behavior where appropriate.

---

## 🛠️ Tech Stack

| Area | Technology |
|---|---|
| Language | Python |
| Web UI | Streamlit |
| Database | PostgreSQL |
| Database Driver | psycopg2 |
| Connection Management | ThreadedConnectionPool |
| Authentication | bcrypt |
| Image Processing | Pillow |
| Data Handling | Python standard library + PostgreSQL queries |
| Deployment | Render |
| Database Hosting | PostgreSQL-compatible hosted database / Supabase connection pooler |

---

## 🔐 Security & Privacy

The project includes several application-level security measures:

- Passwords are hashed using **bcrypt**
- Database credentials are loaded from secrets/environment configuration
- PostgreSQL connections use SSL
- Database connections use liveness checks and keepalives
- Profile fields have individual privacy controls
- Diary entries support private/shared visibility
- Album privacy settings control family media visibility
- HTML-sensitive user content is escaped before rendering in relevant UI paths

> **Important:** This project handles potentially sensitive family and personal information. A public deployment should use authorized test data and appropriate production privacy, access-control, storage, and retention practices.

---

## 🚀 Run Locally

### 1. Clone the repository

```bash
git clone https://github.com/PrahitViraajReddy/Familybook.git
cd Familybook
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure PostgreSQL

Set the database connection string as `POSTGRES_URI`.

For local development, configure it through Streamlit secrets:

```toml
POSTGRES_URI = "your-postgresql-connection-string"
```

Do not commit real credentials to GitHub.

### 4. Start the application

```bash
streamlit run app.py
```

The application creates the required database tables during initialization.

---

## 📁 Project Structure

```text
Familybook/
├── .devcontainer/       # Development container configuration
├── .streamlit/          # Streamlit configuration/secrets setup
├── app.py               # Main Streamlit application
├── requirements.txt     # Python dependencies
└── readme.md            # Project documentation
```

---

## 📌 Engineering Highlights

This project demonstrates practical experience with:

- Building a multi-feature Streamlit application
- Relational database design with PostgreSQL
- Foreign-key relationships and cascading deletes
- Database connection pooling
- Connection health checks and keepalive configuration
- Authentication and password hashing
- Image/media handling
- Privacy-aware application features
- Stateful CRUD-style workflows
- Deployment configuration using environment variables/secrets

---

## 🔗 Links

- **Live App:** https://familybook-7ff4.onrender.com/
- **GitHub:** https://github.com/PrahitViraajReddy/Familybook

---

## 👨‍💻 Author

**Prahit Viraaj Reddy**

- LinkedIn: https://linkedin.com/in/prahit-viraaj-reddy-madupu-5169332ba
- GitHub: https://github.com/PrahitViraajReddy
