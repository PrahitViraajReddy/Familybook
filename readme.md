\# 🌳 VanshaVriksha — Family Tree



A full-featured family tree and dynasty management web app built with \*\*Streamlit\*\* and \*\*PostgreSQL\*\*. Create your family profile, link relatives, share memories through albums, write diary entries, and visualize your lineage — all in one place.



\---



\## ✨ Features



\- \*\*👤 User Profiles\*\* — Register with personal details, profile photo, bio, and privacy controls

\- \*\*👨‍👩‍👧‍👦 Family Links\*\* — Connect with registered members or manually add unregistered relatives with custom relations

\- \*\*🌳 Interactive Family Tree\*\* — Visual tree generated from your linked family members

\- \*\*📖 Family Diary\*\* — Private or shared diary entries with mood tracking, tags, and draft support

\- \*\*📸 Family Albums\*\* — Upload photos/media, add captions, tag people, react and comment

\- \*\*📅 Family Timeline\*\* — Chronological record of important family events across the dynasty

\- \*\*🔍 Dynasty Search\*\* — Find and connect with other members of your dynasty

\- \*\*📜 Activity Feed\*\* — See recent activity across your family network

\- \*\*⚙️ Settings\*\* — Edit profile, change password, manage privacy preferences



\---



\## 🛠️ Tech Stack



| Layer | Technology |

|---|---|

| Frontend | Streamlit |

| Database | PostgreSQL (Supabase compatible) |

| Auth | bcrypt password hashing |

| Image Processing | Pillow (PIL) |

| DB Driver | psycopg2 with connection pooling |



\---



\## 🚀 Getting Started



\### 1. Clone the repo



```bash

git clone https://github.com/your-username/vanshavriksha.git

cd vanshavriksha

```



\### 2. Install dependencies



```bash

pip install -r requirements.txt

```



\### 3. Set up PostgreSQL



You can use a local PostgreSQL instance or a cloud provider like \[Supabase](https://supabase.com) (free tier works great).



Create a database and note the connection URI:

```

postgresql://user:password@host:port/dbname

```



\### 4. Configure secrets



Create the file `.streamlit/secrets.toml` in your project root:



```toml

POSTGRES\_URI = "postgresql://user:password@host:port/dbname"

```



> ⚠️ Never commit `secrets.toml` to version control. Add it to `.gitignore`.



\### 5. Run the app



```bash

streamlit run app.py

```



The app auto-creates all required database tables on first boot.



\---



\## 📁 Project Structure



```

vanshavriksha/

├── app.py                  # Main application (all logic)

├── requirements.txt        # Python dependencies

├── .streamlit/

│   └── secrets.toml        # DB credentials (not committed)

└── README.md

```



\---



\## 🗄️ Database Schema



The app auto-initializes the following tables:



| Table | Purpose |

|---|---|

| `users` | User accounts and profile data |

| `family\_links` | Relationships between users |

| `otp\_store` | OTP tokens for email verification |

| `family\_albums` | Photo album metadata |

| `album\_media` | Photos/media within albums |

| `media\_reactions` | Emoji reactions on media |

| `media\_comments` | Comments on media |

| `family\_diary` | Personal/shared diary entries |

| `family\_timeline` | Family milestone events |



\---



\## ☁️ Deploying to Streamlit Cloud



1\. Push your code to a \*\*public or private GitHub repo\*\* (without `secrets.toml`)

2\. Go to \[share.streamlit.io](https://share.streamlit.io) and connect your repo

3\. Under \*\*Advanced settings → Secrets\*\*, paste your `secrets.toml` content:

&#x20;  ```toml

&#x20;  POSTGRES\_URI = "your-connection-string-here"

&#x20;  ```

4\. Deploy — the app will be live at a public URL



\---



\## 🔒 Security Notes



\- Passwords are hashed using \*\*bcrypt\*\* before storing

\- Privacy toggles let users control visibility of DOB, email, city, and occupation

\- TCP keepalives are configured to handle Supabase idle connection timeouts gracefully



\---



\## 📄 License



MIT License — free to use, modify, and distribute.

