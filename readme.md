# 🌳 VanshaVriksha — Family Tree

A full-featured family tree and dynasty management web app built with **Streamlit** and **PostgreSQL**. Create your family profile, link relatives, share memories through albums, write diary entries, and visualize your lineage — all in one place.

---

## ✨ Features

* **👤 User Profiles** — Register with personal details, profile photo, bio, and privacy controls
* **👨‍👩‍👧‍👦 Family Links** — Connect with registered members or manually add unregistered relatives with custom relations
* **🌳 Interactive Family Tree** — Visual tree generated from your linked family members
* **📖 Family Diary** — Private or shared diary entries with mood tracking, tags, and draft support
* **📸 Family Albums** — Upload photos/media, add captions, tag people, react and comment
* **📅 Family Timeline** — Chronological record of important family events across the dynasty
* **🔍 Dynasty Search** — Find and connect with other members of your dynasty
* **📜 Activity Feed** — See recent activity across your family network
* **⚙️ Settings** — Edit profile, change password, manage privacy preferences

---

## 🛠️ Tech Stack

| Layer            | Technology                       |
| ---------------- | -------------------------------- |
| Frontend         | Streamlit                        |
| Database         | PostgreSQL (Supabase compatible) |
| Auth             | bcrypt password hashing          |
| Image Processing | Pillow (PIL)                     |
| DB Driver        | psycopg2 with connection pooling |

---

## 🚀 Getting Started

### 1. Clone the Repo

```bash
git clone https://github.com/your-username/vanshavriksha.git

cd vanshavriksha
```

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

### 3. Set Up PostgreSQL

You can use a local PostgreSQL instance or a cloud provider like [Supabase](https://supabase.com?utm_source=chatgpt.com) (free tier works great).

Create a database and note the connection URI:

```text
postgresql://user:password@host:port/dbname
```

### 4. Configure Secrets

Create the file `.streamlit/secrets.toml` in your project root:

```toml
POSTGRES_URI = "postgresql://user:password@host:port/dbname"
```

> ⚠️ Never commit `secrets.toml` to version control. Add it to `.gitignore`.

### 5. Run the App

```bash
streamlit run app.py
```

The app auto-creates all required database tables on first boot.

---

## 📁 Project Structure

```text
vanshavriksha/
├── app.py                  # Main application (all logic)
├── requirements.txt        # Python dependencies
├── .streamlit/
│   └── secrets.toml        # DB credentials (not committed)
└── README.md
```

---

## 🗄️ Database Schema

The app auto-initializes the following tables:

| Table             | Purpose                           |
| ----------------- | --------------------------------- |
| `users`           | User accounts and profile data    |
| `family_links`    | Relationships between users       |
| `otp_store`       | OTP tokens for email verification |
| `family_albums`   | Photo album metadata              |
| `album_media`     | Photos/media within albums        |
| `media_reactions` | Emoji reactions on media          |
| `media_comments`  | Comments on media                 |
| `family_diary`    | Personal/shared diary entries     |
| `family_timeline` | Family milestone events           |

---

## ☁️ Deploying to Streamlit Cloud

1. Push your code to a **public or private GitHub repo** (without `secrets.toml`)
2. Go to [Streamlit Community Cloud](https://share.streamlit.io?utm_source=chatgpt.com) and connect your repo
3. Under **Advanced Settings → Secrets**, paste your `secrets.toml` content:

```toml
POSTGRES_URI = "your-connection-string-here"
```

4. Deploy — the app will be live at a public URL

---

## 🔒 Security Notes

* Passwords are hashed using **bcrypt** before storing
* Database credentials are managed securely through Streamlit Secrets
* Sensitive configuration files should never be committed to GitHub
