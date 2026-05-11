# 🌳 VanshaVriksha — Family Tree

A full-featured family tree and dynasty management web app built with **Streamlit** and **PostgreSQL**. Create your family profile, link relatives, share memories through albums, write diary entries, and visualize your lineage — all in one place.

🔗 **Live App:** [familybook-wrzd.onrender.com](https://familybook-wrzd.onrender.com)

---

## ✨ Features

- **👤 User Profiles** — Register with personal details, profile photo, bio, and privacy controls
- **👨‍👩‍👧‍👦 Family Links** — Connect with registered members or manually add unregistered relatives with custom relations
- **🌳 Interactive Family Tree** — Visual tree generated from your linked family members
- **📖 Family Diary** — Private or shared diary entries with mood tracking, tags, and draft support
- **📸 Family Albums** — Upload photos/media, add captions, tag people, react and comment
- **📅 Family Timeline** — Chronological record of important family events across the dynasty
- **🔍 Dynasty Search** — Find and connect with other members of your dynasty
- **📜 Activity Feed** — See recent activity across your family network
- **⚙️ Settings** — Edit profile, change password, manage privacy preferences

---

## 🛠️ Tech Stack

| Layer | Technology |
|---|---|
| Frontend | Streamlit |
| Database | PostgreSQL |
| Auth | bcrypt password hashing |
| Image Processing | Pillow (PIL) |
| DB Driver | psycopg2 with connection pooling |

---

## 🚀 Getting Started

### 1. Clone the repo

```bash
git clone https://github.com/your-username/vanshavriksha.git
cd vanshavriksha
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure your database

Set up your PostgreSQL database and configure the connection string in your environment. The app reads credentials from environment config — set `POSTGRES_URI` accordingly based on your deployment platform.

### 4. Run the app

```bash
streamlit run app.py
```

The app auto-creates all required database tables on first boot.

---

## 📁 Project Structure

```
vanshavriksha/
├── app.py                  # Main application (all logic)
├── requirements.txt        # Python dependencies
└── README.md
```

---

## 🗄️ Database Schema

The app auto-initializes the following tables:

| Table | Purpose |
|---|---|
| `users` | User accounts and profile data |
| `family_links` | Relationships between users |
| `family_albums` | Photo album metadata |
| `album_media` | Photos/media within albums |
| `media_reactions` | Emoji reactions on media |
| `media_comments` | Comments on media |
| `family_diary` | Personal/shared diary entries |
| `family_timeline` | Family milestone events |

---

## 🔒 Security

- Passwords hashed using **bcrypt**
🔗 **Live App:** https://familybook-wrzd.onrender.com/
