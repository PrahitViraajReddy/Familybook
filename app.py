import streamlit as st
import psycopg2
from psycopg2.extras import RealDictCursor
import bcrypt
import re
import random
import string
from datetime import datetime, date, timedelta
import base64
from PIL import Image
import io
import json
import html as _html

def _esc(s):
    return _html.escape(str(s or ""))


# ── Page config ─────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="VanshaVriksha — Family Tree",
    page_icon="🌳",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ── PostgreSQL connection pool ───────────────────────────────────────────────
# Credentials: keep in .streamlit/secrets.toml in production.
# On Render: set POSTGRES_URI as an environment variable.
import psycopg2.pool as _pg_pool
from contextlib import contextmanager
import os

# Try st.secrets first (local / Streamlit Cloud), fallback to env var (Render)
POSTGRES_URI = st.secrets.get("POSTGRES_URI") or os.environ.get("POSTGRES_URI")

if not POSTGRES_URI:
    st.error("❌ POSTGRES_URI not set. Add it to .streamlit/secrets.toml or as an environment variable.")
    st.stop()

# ── TCP keepalives stop Supabase from silently killing idle connections ───────
# keepalives=1          → enable TCP keepalive probes
# keepalives_idle=30    → send first probe after 30 s of silence
# keepalives_interval=5 → re-probe every 5 s
# keepalives_count=3    → drop connection after 3 failed probes
# sslmode=require       → required by Supabase connection pooler
_KEEPALIVE_KWARGS = dict(
    keepalives=1,
    keepalives_idle=30,
    keepalives_interval=5,
    keepalives_count=3,
    connect_timeout=10,
    sslmode="require",
)

def _new_connection():
    """Open a single fresh connection with keepalives enabled."""
    return psycopg2.connect(
        POSTGRES_URI,
        cursor_factory=RealDictCursor,
        **_KEEPALIVE_KWARGS,
    )

@st.cache_resource
def _get_pool():
    """
    One ThreadedConnectionPool shared across all Streamlit reruns.
    minconn=2  → always keep 2 warm connections ready
    maxconn=10 → never exceed 10 (Supabase free tier limit is ~50)
    """
    return _pg_pool.ThreadedConnectionPool(
        minconn=2,
        maxconn=10,
        dsn=POSTGRES_URI,
        cursor_factory=RealDictCursor,
        **_KEEPALIVE_KWARGS,
    )

@contextmanager
def _get_conn():
    """
    Borrow a connection from the pool.
    - Runs a cheap liveness ping; if the connection is dead (Supabase killed it
      after idle timeout), discards it and opens a fresh one.
    - Always returns the connection to the pool on exit.
    """
    pool = _get_pool()
    conn = pool.getconn()
    try:
        # Liveness check — catches connections killed by Supabase idle timeout
        try:
            with conn.cursor() as _cur:
                _cur.execute("SELECT 1")
        except Exception:
            # Connection is dead — replace it with a fresh one
            try:
                pool.putconn(conn, close=True)
            except Exception:
                pass
            conn = _new_connection()
        yield conn
    except Exception:
        # Return broken connection so the pool can discard it
        try:
            pool.putconn(conn, close=True)
        except Exception:
            pass
        raise
    else:
        pool.putconn(conn)


def _init_db():
    """Create all tables and indexes once on first boot."""
    with _get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id            SERIAL PRIMARY KEY,
                full_name     TEXT        NOT NULL,
                email         TEXT        NOT NULL UNIQUE,
                password      TEXT        NOT NULL,
                dob           DATE        NOT NULL,
                dynasty_name  TEXT        NOT NULL,
                gender        TEXT        DEFAULT '',
                birth_city    TEXT        DEFAULT '',
                current_city  TEXT        DEFAULT '',
                occupation    TEXT        DEFAULT '',
                religion      TEXT        DEFAULT '',
                caste         TEXT        DEFAULT '',
                gotram        TEXT        DEFAULT '',
                profile_photo TEXT        DEFAULT '',
                bio           TEXT        DEFAULT '',
                privacy_dob   BOOLEAN     DEFAULT TRUE,
                privacy_email BOOLEAN     DEFAULT FALSE,
                privacy_city  BOOLEAN     DEFAULT TRUE,
                privacy_occ   BOOLEAN     DEFAULT TRUE,
                verified      BOOLEAN     DEFAULT FALSE,
                created_at    TIMESTAMPTZ DEFAULT NOW()
            );

            CREATE TABLE IF NOT EXISTS family_links (
                id          SERIAL PRIMARY KEY,
                user_id     INTEGER     NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                member_id   INTEGER     REFERENCES users(id) ON DELETE SET NULL,
                member_name TEXT        NOT NULL,
                relation    TEXT        NOT NULL,
                created_at  TIMESTAMPTZ DEFAULT NOW()
            );

            CREATE TABLE IF NOT EXISTS otp_store (
                email       TEXT PRIMARY KEY,
                otp         TEXT        NOT NULL,
                expires_at  TIMESTAMPTZ NOT NULL
            );

            CREATE TABLE IF NOT EXISTS family_albums (
                id           SERIAL PRIMARY KEY,
                user_id      INTEGER     NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                dynasty_name TEXT        NOT NULL,
                title        TEXT        NOT NULL,
                description  TEXT        DEFAULT '',
                cover_photo  TEXT        DEFAULT '',
                privacy      TEXT        DEFAULT 'dynasty',
                created_at   TIMESTAMPTZ DEFAULT NOW()
            );

            CREATE TABLE IF NOT EXISTS album_media (
                id          SERIAL PRIMARY KEY,
                album_id    INTEGER     NOT NULL REFERENCES family_albums(id) ON DELETE CASCADE,
                user_id     INTEGER     NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                media_type  TEXT        NOT NULL DEFAULT 'photo',
                media_data  TEXT        NOT NULL,
                caption     TEXT        DEFAULT '',
                location    TEXT        DEFAULT '',
                tags        TEXT        DEFAULT '',
                taken_on    DATE,
                created_at  TIMESTAMPTZ DEFAULT NOW()
            );

            CREATE TABLE IF NOT EXISTS media_reactions (
                id          SERIAL PRIMARY KEY,
                media_id    INTEGER     NOT NULL REFERENCES album_media(id) ON DELETE CASCADE,
                user_id     INTEGER     NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                reaction    TEXT        NOT NULL,
                UNIQUE(media_id, user_id)
            );

            CREATE TABLE IF NOT EXISTS media_comments (
                id          SERIAL PRIMARY KEY,
                media_id    INTEGER     NOT NULL REFERENCES album_media(id) ON DELETE CASCADE,
                user_id     INTEGER     NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                comment     TEXT        NOT NULL,
                created_at  TIMESTAMPTZ DEFAULT NOW()
            );

            CREATE TABLE IF NOT EXISTS family_diary (
                id          SERIAL PRIMARY KEY,
                user_id     INTEGER     NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                title       TEXT        NOT NULL,
                content     TEXT        NOT NULL,
                tags        TEXT        DEFAULT '',
                mood        TEXT        DEFAULT '',
                privacy     TEXT        DEFAULT 'private',
                is_draft    BOOLEAN     DEFAULT FALSE,
                entry_date  DATE        NOT NULL,
                created_at  TIMESTAMPTZ DEFAULT NOW(),
                updated_at  TIMESTAMPTZ DEFAULT NOW()
            );

            CREATE TABLE IF NOT EXISTS family_timeline (
                id           SERIAL PRIMARY KEY,
                user_id      INTEGER     NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                dynasty_name TEXT        NOT NULL,
                event_type   TEXT        NOT NULL,
                title        TEXT        NOT NULL,
                description  TEXT        DEFAULT '',
                event_date   DATE        NOT NULL,
                location     TEXT        DEFAULT '',
                tags         TEXT        DEFAULT '',
                media_data   TEXT        DEFAULT '',
                privacy      TEXT        DEFAULT 'dynasty',
                created_at   TIMESTAMPTZ DEFAULT NOW()
            );

            ALTER TABLE users ADD COLUMN IF NOT EXISTS bio TEXT DEFAULT '';
            ALTER TABLE users ADD COLUMN IF NOT EXISTS privacy_dob BOOLEAN DEFAULT TRUE;
            ALTER TABLE users ADD COLUMN IF NOT EXISTS privacy_email BOOLEAN DEFAULT FALSE;
            ALTER TABLE users ADD COLUMN IF NOT EXISTS religion TEXT DEFAULT '';
            ALTER TABLE users ADD COLUMN IF NOT EXISTS caste TEXT DEFAULT '';
            ALTER TABLE users ADD COLUMN IF NOT EXISTS gotram TEXT DEFAULT '';
            ALTER TABLE users ADD COLUMN IF NOT EXISTS privacy_city BOOLEAN DEFAULT TRUE;
            ALTER TABLE users ADD COLUMN IF NOT EXISTS privacy_occ BOOLEAN DEFAULT TRUE;

            CREATE INDEX IF NOT EXISTS idx_users_dynasty
            ON users(dynasty_name);

            CREATE INDEX IF NOT EXISTS idx_links_user
            ON family_links(user_id);

            CREATE INDEX IF NOT EXISTS idx_albums_dynasty
            ON family_albums(dynasty_name);

            CREATE INDEX IF NOT EXISTS idx_media_album
            ON album_media(album_id);

            CREATE INDEX IF NOT EXISTS idx_diary_user
            ON family_diary(user_id);

            CREATE INDEX IF NOT EXISTS idx_timeline_dynasty
            ON family_timeline(dynasty_name);

            -- Prevent the same registered member from being linked twice under
            -- different relation names. The constraint is partial (WHERE member_id
            -- IS NOT NULL) so unregistered name-only entries are unaffected.
            DO $$ BEGIN
              IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'uq_family_links_user_member'
              ) THEN
                ALTER TABLE family_links
                  ADD CONSTRAINT uq_family_links_user_member
                  UNIQUE (user_id, member_id);
              END IF;
            END $$;
            """)
        conn.commit()


try:
    _init_db()
    _db_error = None
except Exception as e:
    _db_error = str(e)


def _migrate_relation_aliases():
    """
    One-time data migration: rewrite any stored variant/alias relation names
    in family_links to their canonical form.
    E.g.  "Brother-in-law (Jija)" → "Brother-in-law"
    Safe to run on every boot — only updates rows that need it.
    """
    try:
        rows = q_all("SELECT id, relation FROM family_links")
        for row in rows:
            canonical = normalize_relation(row["relation"])
            if canonical != row["relation"]:
                q_exec(
                    "UPDATE family_links SET relation=%s WHERE id=%s",
                    (canonical, row["id"])
                )
    except Exception:
        pass   # non-fatal — tree normalization still handles display


def db_ok():
    """Quick liveness check — borrows and immediately returns a connection."""
    try:
        with _get_conn():
            return True
    except Exception:
        return False


# ── Helpers ──────────────────────────────────────────────────────────────────

def hash_pw(p):
    return bcrypt.hashpw(p.encode(), bcrypt.gensalt()).decode()


def check_pw(p, h):
    return bcrypt.checkpw(p.encode(), h.encode())


def gen_otp():
    return "".join(random.choices(string.digits, k=6))


def valid_email(e):
    return bool(re.match(r"[^@]+@[^@]+\.[^@]+", e))


def calc_age(dob):
    t = date.today()
    return t.year - dob.year - ((t.month, t.day) < (dob.month, dob.day))


def q_one(sql, params=()):
    with _get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchone()


def q_all(sql, params=()):
    with _get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchall()


def q_exec(sql, params=()):
    with _get_conn() as conn:
        try:
            with conn.cursor() as cur:
                cur.execute(sql, params)
            conn.commit()
        except Exception:
            conn.rollback()
            raise


def q_exec_return(sql, params=()):
    with _get_conn() as conn:
        try:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                row = cur.fetchone()
            conn.commit()
            return row
        except Exception:
            conn.rollback()
            raise


@st.cache_data(ttl=30, show_spinner=False)
def get_user(uid):
    return q_one(
        "SELECT * FROM users WHERE id=%s",
        (uid,)
    )


@st.cache_data(ttl=30, show_spinner=False)
def get_user_email(email):
    return q_one(
        "SELECT * FROM users WHERE email=%s",
        (email.lower().strip(),)
    )


@st.cache_data(ttl=30, show_spinner=False)
def get_links(uid):
    return q_all("""
        SELECT fl.*, 
               u.full_name as linked_name,
               u.dynasty_name as linked_dynasty,
               u.profile_photo as linked_photo,
               u.dob as linked_dob,
               u.gender as linked_gender,
               u.current_city as linked_city,
               u.occupation as linked_occ
        FROM family_links fl
        LEFT JOIN users u ON u.id = fl.member_id
        WHERE fl.user_id = %s
        ORDER BY fl.relation, fl.member_name
    """, (uid,))

# ── Relations ────────────────────────────────────────────────────────────────
RELATION_GROUPS = {
    "👨‍👩‍👦 Parents":         ["Father","Mother","Stepfather","Stepmother"],
    "👫 Siblings":            ["Brother","Sister","Stepbrother","Stepsister"],
    "💍 Spouse / Partner":    ["Husband","Wife","Partner"],
    "👶 Children":            ["Son","Daughter","Stepson","Stepdaughter"],
    "👴 Grandparents":        ["Paternal Grandfather","Paternal Grandmother",
                               "Maternal Grandfather","Maternal Grandmother"],
    "🧒 Grandchildren":       ["Grandson","Granddaughter"],
    "🫂 Aunts & Uncles":      ["Paternal Uncle","Elder Paternal Uncle",
                               "Paternal Aunt","Maternal Uncle","Maternal Aunt",
                               "Maternal Uncle's Wife","Paternal Aunt's Husband"],
    "🏠 In-laws":             ["Father-in-law","Mother-in-law",
                               "Brother-in-law","Husband's Brother","Wife's Sister's Husband",
                               "Husband's Sister","Brother's Wife","Wife's Sister",
                               "Son-in-law","Daughter-in-law",
                               "Sister's Father-in-law","Sister's Mother-in-law",
                               "Brother's Father-in-law","Brother's Mother-in-law"],
    "🧑‍🤝‍🧑 Cousins":          ["Cousin (Male)","Cousin (Female)","First Cousin","Second Cousin"],
    "👦 Nephews & Nieces":    ["Nephew","Niece",
                               "Nephew's Wife","Niece's Husband",
                               "Grand Nephew","Grand Niece"],
    "🧓 Great-grandparents":  ["Great-grandfather","Great-grandmother",
                               "Paternal Great-grandfather","Paternal Great-grandmother",
                               "Maternal Great-grandfather","Maternal Great-grandmother"],
    "👼 Great-grandchildren": ["Great-grandson","Great-granddaughter"],
    "🌐 Others":              ["Family Friend","Guardian","Ward","Other"],
}

ALL_RELATIONS = [r for rels in RELATION_GROUPS.values() for r in rels]

# ── Relation Alias Normalization ──────────────────────────────────────────────
# Maps non-standard / regional variant names → canonical relation strings.
# This handles data entered before strict validation, regional nicknames, etc.
RELATION_ALIASES: dict[str, str] = {
    # Brother-in-law variants (Jija = Hindi/Telugu for sister's husband)
    "brother-in-law (jija)":        "Brother-in-law",
    "jija":                         "Brother-in-law",
    "jijaji":                       "Brother-in-law",
    "sala":                         "Brother-in-law",
    "saala":                        "Brother-in-law",
    # Sister-in-law variants
    "sister-in-law (bhabhi)":       "Husband's Sister",
    "bhabhi":                       "Brother's Wife",
    "bhabi":                        "Brother's Wife",
    "nanad":                        "Husband's Sister",
    # Father variants
    "nanna":                        "Father",
    "nana":                         "Father",
    "daddy":                        "Father",
    "dad":                          "Father",
    "appa":                         "Father",
    # Mother variants
    "amma":                         "Mother",
    "mom":                          "Mother",
    "mummy":                        "Mother",
    "maa":                          "Mother",
    # Grandfather / Grandmother variants
    "thatha":                       "Paternal Grandfather",
    "tata":                         "Paternal Grandfather",
    "avva":                         "Paternal Grandmother",
    "ajji":                         "Paternal Grandmother",
    "nanna tata":                   "Paternal Grandfather",
    "ammamma":                      "Maternal Grandmother",
    "amma nanna":                   "Maternal Grandfather",
    # Great-grandparent variants
    "great grandmother":            "Great-grandmother",
    "great grandfather":            "Great-grandfather",
    "peddamma":                     "Paternal Aunt",
    "pedananna":                    "Paternal Uncle",
    # Spouse variants
    "hubby":                        "Husband",
    "wife (spouse)":                "Wife",
    "husband (spouse)":             "Husband",
    # Niece/Nephew variants
    "bhatija":                      "Nephew",
    "bhanji":                       "Niece",
}

RELATION_GEN = {
    "Great-grandfather": -3, "Great-grandmother": -3,
    "Paternal Grandfather": -2, "Paternal Grandmother": -2,
    "Maternal Grandfather": -2, "Maternal Grandmother": -2,
    "Father": -1, "Mother": -1, "Stepfather": -1, "Stepmother": -1,
    "Father-in-law": -1, "Mother-in-law": -1,
    "Paternal Uncle": -1, "Elder Paternal Uncle": -1,
    "Paternal Aunt": -1,
    "Maternal Uncle": -1, "Maternal Aunt": -1,
    "Brother": 0, "Sister": 0, "Stepbrother": 0, "Stepsister": 0,
    "Husband": 0, "Wife": 0, "Partner": 0,
    "Cousin (Male)": 0, "Cousin (Female)": 0,
    "First Cousin": 0, "Second Cousin": 0,
    "Brother-in-law": 0, "Husband's Brother": 0,
    "Wife's Sister's Husband": 0,
    "Husband's Sister": 0, "Brother's Wife": 0, "Wife's Sister": 0,
    "Son": 1, "Daughter": 1, "Stepson": 1, "Stepdaughter": 1,
    "Nephew": 1, "Niece": 1,
    "Son-in-law": 1, "Daughter-in-law": 1,
    "Grandson": 2, "Granddaughter": 2,
    "Great-grandson": 3, "Great-granddaughter": 3,
    "Family Friend": 0, "Guardian": -1, "Ward": 1, "Other": 0,
    # Extended in-laws (gen -1 — parents row, sister/brother side)
    "Sister's Father-in-law": -1, "Sister's Mother-in-law": -1,
    "Brother's Father-in-law": -1, "Brother's Mother-in-law": -1,
    # Aunts & Uncles extended
    "Maternal Uncle's Wife": -1, "Paternal Aunt's Husband": -1,
    # Nephews & Nieces extended
    "Nephew's Wife": 1, "Niece's Husband": 1,
    "Grand Nephew": 2, "Grand Niece": 2,
    # Great-grandparents extended
    "Paternal Great-grandfather": -3, "Paternal Great-grandmother": -3,
    "Maternal Great-grandfather": -3, "Maternal Great-grandmother": -3,
}

GEN_COLORS = {
    -3: "#7C3AED", -2: "#4F46E5", -1: "#2563EB",
     0: "#C9A84C",
     1: "#059669",  2: "#D97706",  3: "#DC2626",
}


def normalize_relation(rel: str) -> str:
    """
    Return the canonical relation string for a given input.
    Handles variants like "Brother-in-law (Jija)" -> "Brother-in-law".
    Steps: exact match -> alias map -> prefix match -> original.
    """
    if not rel:
        return rel
    rel_stripped = rel.strip()
    if rel_stripped in RELATION_GEN:
        return rel_stripped
    lower = rel_stripped.lower()
    if lower in RELATION_ALIASES:
        return RELATION_ALIASES[lower]
    # Prefix match catches "(Jija)", "(Bhabhi)" etc. appended to canonical
    for canonical in RELATION_GEN:
        if lower.startswith(canonical.lower()):
            return canonical
    return rel_stripped


# Run alias migration now that all maps are defined
try:
    _migrate_relation_aliases()
except Exception:
    pass

MOODS = ["😊 Happy", "😢 Sad", "🥹 Nostalgic", "🎉 Celebratory", "😌 Peaceful", "😤 Frustrated", "🥰 Grateful", "😮 Surprised"]
EVENT_TYPES = ["🎂 Birth", "💍 Marriage", "⚰️ Death", "🏠 Migration", "🎓 Education", "💼 Career", "🏆 Achievement", "🌏 Travel", "🙏 Religious", "👨‍👩‍👧 Family Reunion", "📅 Other"]

# ── Inverse Relation Map (PATCH: Bidirectional Links) ────────────────────────
INVERSE_RELATION = {
    # Parents ↔ Children  (gender refined by get_inverse_relation)
    "Father":           "Son",
    "Mother":           "Son",
    "Stepfather":       "Stepson",
    "Stepmother":       "Stepson",
    # Siblings ↔ Siblings  (gender-refined by get_inverse_relation)
    "Brother":          "Brother",   # refined to "Sister" if target is female
    "Sister":           "Sister",    # refined to "Brother" if target is male
    "Stepbrother":      "Stepbrother",
    "Stepsister":       "Stepsister",
    # Spouse ↔ Spouse
    "Husband":          "Wife",
    "Wife":             "Husband",
    "Partner":          "Partner",
    # Children ↔ Parents
    "Son":              "Father",
    "Daughter":         "Father",
    "Stepson":          "Stepfather",
    "Stepdaughter":     "Stepfather",
    # Grandparents ↔ Grandchildren
    "Paternal Grandfather": "Grandson",
    "Paternal Grandmother": "Grandson",
    "Maternal Grandfather": "Grandson",
    "Maternal Grandmother": "Grandson",
    "Grandson":         "Paternal Grandfather",
    "Granddaughter":    "Paternal Grandfather",
    # Great-grandparents ↔ Great-grandchildren
    "Great-grandfather":   "Great-grandson",
    "Great-grandmother":   "Great-grandson",
    "Great-grandson":      "Great-grandfather",
    "Great-granddaughter": "Great-grandfather",
    # Aunts & Uncles ↔ Nephews & Nieces
    "Paternal Uncle": "Nephew",
    "Elder Paternal Uncle":    "Nephew",
    "Paternal Aunt":     "Nephew",
    "Maternal Uncle":   "Nephew",
    "Maternal Aunt":   "Nephew",
    "Nephew":           "Paternal Uncle",
    "Niece":            "Paternal Uncle",
    # In-laws
    "Father-in-law":    "Son-in-law",
    "Mother-in-law":    "Son-in-law",
    "Son-in-law":       "Father-in-law",
    "Daughter-in-law":  "Father-in-law",
    "Brother-in-law":            "Husband's Sister",
    "Husband's Brother":           "Brother's Wife",
    "Wife's Sister's Husband": "Husband's Sister",
    "Husband's Sister":            "Brother-in-law",
    "Brother's Wife":           "Husband's Brother",
    "Wife's Sister":             "Brother-in-law",
    # Cousins ↔ Cousins
    "Cousin (Male)":    "Cousin (Male)",
    "Cousin (Female)":  "Cousin (Female)",
    "First Cousin":     "First Cousin",
    "Second Cousin":    "Second Cousin",
    # Others
    "Family Friend":    "Family Friend",
    "Guardian":         "Ward",
    "Ward":             "Guardian",
    "Other":            "Other",
    # Extended in-laws
    "Sister's Father-in-law":  "Son-in-law",
    "Sister's Mother-in-law":  "Son-in-law",
    "Brother's Father-in-law": "Son-in-law",
    "Brother's Mother-in-law": "Son-in-law",
    # Aunts & Uncles extended
    "Maternal Uncle's Wife":    "Nephew",
    "Paternal Aunt's Husband": "Nephew",
    # Nephews & Nieces extended
    "Nephew's Wife":   "Paternal Uncle",
    "Niece's Husband": "Paternal Uncle",
    "Grand Nephew":     "Paternal Grandfather",
    "Grand Niece":      "Paternal Grandfather",
    # Great-grandparents extended
    "Paternal Great-grandfather": "Great-grandson",
    "Paternal Great-grandmother": "Great-grandson",
    "Maternal Great-grandfather": "Great-grandson",
    "Maternal Great-grandmother": "Great-grandson",
}


def get_inverse_relation(relation: str, target_gender: str = "") -> str:
    """
    Return the correct inverse relation label.
    Uses gender of target user to refine generic inverses like Son/Daughter.
    """
    inv = INVERSE_RELATION.get(relation, "Other")
    gender = (target_gender or "").lower()

    GENDER_REFINE = {
        "Son":              {"female": "Daughter",        "f": "Daughter"},
        "Stepson":          {"female": "Stepdaughter",    "f": "Stepdaughter"},
        "Grandson":         {"female": "Granddaughter",   "f": "Granddaughter"},
        "Great-grandson":   {"female": "Great-granddaughter", "f": "Great-granddaughter"},
        "Nephew":           {"female": "Niece",           "f": "Niece"},
        "Son-in-law":       {"female": "Daughter-in-law", "f": "Daughter-in-law"},
        "Father":           {"female": "Mother",          "f": "Mother"},
        "Stepfather":       {"female": "Stepmother",      "f": "Stepmother"},
        "Paternal Grandfather": {"female": "Paternal Grandmother", "f": "Paternal Grandmother"},
        "Maternal Grandfather": {"female": "Maternal Grandmother", "f": "Maternal Grandmother"},
        "Great-grandfather":{"female": "Great-grandmother","f": "Great-grandmother"},
        "Husband":          {"female": "Wife",            "f": "Wife"},
        "Wife":             {"male":   "Husband",         "m": "Husband"},
        "Brother":          {"female": "Sister",          "f": "Sister"},
        "Sister":           {"male":   "Brother",         "m": "Brother"},
        "Cousin (Male)":    {"female": "Cousin (Female)", "f": "Cousin (Female)"},
        "Cousin (Female)":  {"male":   "Cousin (Male)",   "m": "Cousin (Male)"},
    }

    if inv in GENDER_REFINE:
        for key, refined in GENDER_REFINE[inv].items():
            if key in gender:
                return refined

    return inv


# ── Bidirectional link helpers (PATCH) ───────────────────────────────────────
def _insert_link(user_id, member_id, member_name, relation):
    """Insert a family link only if it doesn't already exist."""
    existing = q_one(
        "SELECT id FROM family_links WHERE user_id=%s AND member_id=%s AND relation=%s",
        (user_id, member_id, relation)
    )
    if not existing:
        q_exec(
            "INSERT INTO family_links(user_id, member_id, member_name, relation) "
            "VALUES (%s, %s, %s, %s)",
            (user_id, member_id, member_name, relation)
        )


def _delete_reciprocal(link_id, current_uid):
    """
    When user deletes link_id, also remove the matching reciprocal row from
    the linked user's profile.
    """
    lk = q_one("SELECT * FROM family_links WHERE id=%s", (link_id,))
    if not lk:
        return
    if lk.get("member_id"):
        q_exec(
            "DELETE FROM family_links WHERE user_id=%s AND member_id=%s",
            (lk["member_id"], current_uid)
        )


def _link_button_handler(uid, res, rel_type):
    """
    Creates BOTH directions of the link simultaneously.
    Call this inside the "Link" button block.
    """
    existing = q_one(
        "SELECT id FROM family_links WHERE user_id=%s AND member_id=%s",
        (uid, res["id"])
    )
    if existing:
        set_msg("Already linked.", "error")
        return

    # A → B (what user A chose)
    _insert_link(
        user_id=uid,
        member_id=res["id"],
        member_name=res["full_name"],
        relation=rel_type,
    )

    # B → A (automatic inverse)
    current_user = q_one("SELECT full_name, gender FROM users WHERE id=%s", (uid,))
    inv_relation = get_inverse_relation(rel_type, current_user["gender"] if current_user else "")

    _insert_link(
        user_id=res["id"],
        member_id=uid,
        member_name=current_user["full_name"] if current_user else "Family Member",
        relation=inv_relation,
    )

    set_msg(
        f"Linked! {res['full_name']} added as your {rel_type}. "
        f"You appear as their {inv_relation}. 🔗",
        "success"
    )


def _remove_link_handler(lk, uid, name):
    """Deletes the link AND its reciprocal from the other user's profile."""
    _delete_reciprocal(lk["id"], uid)
    q_exec("DELETE FROM family_links WHERE id=%s AND user_id=%s", (lk["id"], uid))
    set_msg(f"Removed {name} and their reciprocal link. ✓", "info")


def relation_selectbox(label: str, key: str, default: str = "Son") -> str:
    default_group = next(
        (g for g, rels in RELATION_GROUPS.items() if default in rels),
        list(RELATION_GROUPS.keys())[0]
    )
    group_key    = f"{key}_group"
    relation_key = f"{key}_rel"
    group_names  = list(RELATION_GROUPS.keys())

    if group_key not in st.session_state:
        st.session_state[group_key] = default_group

    col_a, col_b = st.columns(2)
    with col_a:
        chosen_group = st.selectbox(
            "Category",
            options=group_names,
            key=group_key,
        )
    rels_in_group = RELATION_GROUPS[chosen_group]
    current_rel   = st.session_state.get(relation_key, default)
    rel_idx       = rels_in_group.index(current_rel) if current_rel in rels_in_group else 0
    with col_b:
        chosen_rel = st.selectbox(
            "Relation",
            options=rels_in_group,
            index=rel_idx,
            key=relation_key,
        )
    return chosen_rel

# ── Photo helpers ─────────────────────────────────────────────────────────────
MAX_PHOTO_KB = 800

def process_photo(uploaded_file, size=150) -> tuple:
    try:
        file_bytes = uploaded_file.read()
        if len(file_bytes) > MAX_PHOTO_KB * 1024:
            return None, f"File too large (max {MAX_PHOTO_KB} KB)."
        img = Image.open(io.BytesIO(file_bytes)).convert("RGB")
        w, h = img.size
        mn = min(w, h)
        img = img.crop(((w-mn)//2, (h-mn)//2, (w-mn)//2+mn, (h-mn)//2+mn))
        img = img.resize((size, size), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=78, optimize=True)
        b64 = base64.b64encode(buf.getvalue()).decode()
        return f"data:image/jpeg;base64,{b64}", None
    except Exception as e:
        return None, "Could not process image. Please try a different file."

def process_photo_rect(uploaded_file, max_w=800, max_h=600) -> tuple:
    """For album photos — keep aspect ratio, just resize large images."""
    try:
        file_bytes = uploaded_file.read()
        if len(file_bytes) > 4 * 1024 * 1024:
            return None, "File too large (max 4 MB)."
        img = Image.open(io.BytesIO(file_bytes)).convert("RGB")
        img.thumbnail((max_w, max_h), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=80, optimize=True)
        b64 = base64.b64encode(buf.getvalue()).decode()
        return f"data:image/jpeg;base64,{b64}", None
    except Exception as e:
        return None, "Could not process image. Please try a different file."

def avatar_html(photo_data, initials, size=72):
    if photo_data:
        return (
            f'<img src="{photo_data}" '
            f'style="width:{size}px;height:{size}px;border-radius:50%;'
            f'object-fit:cover;border:2.5px solid var(--gold);flex-shrink:0;" />'
        )
    font = max(12, size // 2 - 4)
    return (
        f'<span style="width:{size}px;height:{size}px;border-radius:50%;'
        f'background:linear-gradient(135deg,var(--bark),var(--moss));'
        f'display:inline-flex;align-items:center;justify-content:center;'
        f'font-family:\'Cormorant Garamond\',serif;font-size:{font}px;'
        f'color:var(--gold);flex-shrink:0;border:2.5px solid var(--gold);">'
        f'{initials}</span>'
    )

# ── CSS ────────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Cormorant+Garamond:ital,wght@0,400;0,600;0,700;1,400&family=DM+Sans:wght@300;400;500;600&display=swap');

:root{
  --cream:#FAF7F2; --parchment:#F0EBE1; --bark:#5C3D2E; --moss:#3B5249;
  --gold:#C9A84C; --rust:#A0522D; --ink:#1C1C1C; --mist:#8C9E8E;
  --shadow:rgba(28,28,28,0.10); --card-bg:#FFFFFF;
}

html,body,[data-testid="stAppViewContainer"]{
  background:var(--cream)!important;
  font-family:'DM Sans',sans-serif!important;
  color:var(--ink)!important;
}
#MainMenu,footer,[data-testid="stToolbar"],[data-testid="stDecoration"],[data-testid="stStatusWidget"]{display:none!important;}
header[data-testid="stHeader"]{background:transparent!important;}
[data-testid="block-container"]{max-width:1060px;margin:0 auto;padding:1.5rem 1.5rem 4rem!important;}

/* Hero */
.hero{background:linear-gradient(135deg,var(--bark) 0%,var(--moss) 100%);border-radius:20px;padding:2.5rem 2rem 2rem;text-align:center;margin-bottom:2rem;position:relative;overflow:hidden;}
.hero::before{content:'';position:absolute;inset:0;background:url("data:image/svg+xml,%3Csvg width='60' height='60' viewBox='0 0 60 60' xmlns='http://www.w3.org/2000/svg'%3E%3Cg fill='none'%3E%3Cg fill='%23ffffff' fill-opacity='0.04'%3E%3Cpath d='M36 34v-4h-2v4h-4v2h4v4h2v-4h4v-2h-4zm0-30V0h-2v4h-4v2h4v4h2V6h4V4h-4zM6 34v-4H4v4H0v2h4v4h2v-4h4v-2H6zM6 4V0H4v4H0v2h4v4h2V6h4V4H6z'/%3E%3C/g%3E%3C/g%3E%3C/svg%3E");}
.hero-title{font-family:'Cormorant Garamond',serif;font-size:2.8rem;font-weight:700;color:var(--gold);letter-spacing:2px;margin:0 0 .3rem;position:relative;}
.hero-sub{font-size:.93rem;color:rgba(255,255,255,.75);letter-spacing:.4px;position:relative;}

/* Cards */
.card{background:var(--card-bg);border-radius:14px;padding:1.8rem;box-shadow:0 2px 18px var(--shadow);border:1px solid var(--parchment);margin-bottom:1.2rem;}
.card-title{font-family:'Cormorant Garamond',serif;font-size:1.45rem;font-weight:600;color:var(--bark);margin-bottom:1rem;padding-bottom:.5rem;border-bottom:2px solid var(--parchment);}

/* Badges */
.badge{display:inline-block;padding:.2rem .65rem;border-radius:20px;font-size:.73rem;font-weight:500;margin:.2rem;}
.badge-gold{background:#FDF3DC;color:var(--rust);border:1px solid var(--gold);}
.badge-green{background:#EAF4EE;color:var(--moss);border:1px solid var(--moss);}
.badge-blue{background:#EAF0FB;color:#1A3A6E;border:1px solid #3B6ECA;}
.badge-purple{background:#F3EEFF;color:#5B21B6;border:1px solid #7C3AED;}
.badge-red{background:#FEF2F2;color:#991B1B;border:1px solid #DC2626;}

/* Messages */
.msg-success{background:#EAF7EE;border-left:4px solid var(--moss);border-radius:8px;padding:.85rem 1rem;margin:.7rem 0;color:#1E4D2B;font-size:.88rem;}
.msg-error  {background:#FDECEA;border-left:4px solid #C0392B;border-radius:8px;padding:.85rem 1rem;margin:.7rem 0;color:#922B21;font-size:.88rem;}
.msg-info   {background:#EAF0FB;border-left:4px solid #3B6ECA;border-radius:8px;padding:.85rem 1rem;margin:.7rem 0;color:#1A3A6E;font-size:.88rem;}


.fancy-divider{border:none;height:1px;background:linear-gradient(to right,transparent,var(--parchment),transparent);margin:1.2rem 0;}

/* Rel chips */
.rel-chip{display:flex;align-items:center;gap:.6rem;background:var(--parchment);border-radius:10px;padding:.55rem .9rem;margin-bottom:.4rem;font-size:.86rem;}
.rel-type{font-weight:600;color:var(--bark);min-width:110px;}

/* Buttons */
[data-testid="stButton"]>button{border-radius:8px!important;font-family:'DM Sans',sans-serif!important;font-weight:500!important;font-size:.86rem!important;background:#ffffff!important;color:#1C1C1C!important;border:1.5px solid #E8E0D4!important;}
[data-testid="stButton"]>button[kind="primary"]{background:linear-gradient(135deg,#5C3D2E,#3B5249)!important;border:none!important;color:#ffffff!important;}

/* Dashboard banner */
.namaste-banner{background:linear-gradient(120deg,var(--bark) 0%,#7A4F35 40%,var(--moss) 100%);border-radius:16px;padding:1.6rem 1.8rem;display:flex;align-items:center;gap:1.4rem;margin-bottom:1.2rem;position:relative;overflow:hidden;}
.namaste-banner::after{content:'🌿';position:absolute;right:2rem;top:50%;transform:translateY(-50%);font-size:3.5rem;opacity:.15;}
.namaste-title{font-family:'Cormorant Garamond',serif;font-size:1.75rem;font-weight:700;color:var(--gold);line-height:1.1;}
.namaste-sub{font-size:.82rem;color:rgba(255,255,255,.72);margin-top:.2rem;}

/* Stat grid */
.stat-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:.8rem;margin-bottom:1.2rem;}
.stat-card{background:white;border-radius:13px;padding:1.1rem 1rem;box-shadow:0 2px 14px var(--shadow);border:1px solid var(--parchment);text-align:center;transition:transform .15s;}
.stat-card:hover{transform:translateY(-2px);}
.stat-icon{font-size:1.5rem;margin-bottom:.25rem;}
.stat-num{font-family:'Cormorant Garamond',serif;font-size:2rem;font-weight:700;color:var(--bark);line-height:1;}
.stat-label{font-size:.68rem;text-transform:uppercase;letter-spacing:1.2px;color:var(--mist);margin-top:.2rem;}

/* Activity feed */
.feed-card{background:white;border-radius:14px;padding:1.3rem 1.5rem;box-shadow:0 2px 14px var(--shadow);border:1px solid var(--parchment);margin-bottom:1.2rem;}
.feed-title{font-family:'Cormorant Garamond',serif;font-size:1.2rem;font-weight:600;color:var(--bark);margin-bottom:.9rem;display:flex;align-items:center;gap:.45rem;}
.feed-item{display:flex;align-items:flex-start;gap:.85rem;padding:.65rem 0;border-bottom:1px solid var(--parchment);}
.feed-item:last-child{border-bottom:none;padding-bottom:0;}
.feed-dot{width:9px;height:9px;border-radius:50%;background:var(--gold);flex-shrink:0;margin-top:.35rem;}
.feed-dot.green{background:var(--moss);}
.feed-dot.rust{background:var(--rust);}
.feed-dot.purple{background:#7C3AED;}
.feed-text{font-size:.85rem;color:var(--ink);line-height:1.45;}
.feed-time{font-size:.72rem;color:var(--mist);margin-top:.12rem;}
.feed-empty{color:var(--mist);font-size:.86rem;text-align:center;padding:1.5rem 0;}

/* Search */
.search-hero{background:linear-gradient(135deg,var(--bark),var(--moss));border-radius:14px;padding:1.8rem;margin-bottom:1.2rem;}
.search-hero-title{font-family:'Cormorant Garamond',serif;font-size:1.5rem;font-weight:700;color:var(--gold);margin-bottom:.7rem;}
.filter-strip{background:white;border-radius:12px;padding:1.1rem 1.3rem;box-shadow:0 2px 10px var(--shadow);border:1px solid var(--parchment);margin-bottom:1rem;}
.member-card{background:white;border-radius:14px;padding:1.2rem 1rem;text-align:center;box-shadow:0 2px 12px var(--shadow);border:1.5px solid var(--parchment);transition:all .18s;}
.member-card:hover{border-color:var(--gold);transform:translateY(-3px);box-shadow:0 6px 20px rgba(92,61,46,.14);}
.member-card-name{font-family:'Cormorant Garamond',serif;font-size:1rem;font-weight:700;color:var(--bark);margin-top:.5rem;margin-bottom:.15rem;}
.member-card-dynasty{font-size:.73rem;color:var(--mist);}
.member-list-row{display:flex;align-items:center;gap:.9rem;background:white;border-radius:12px;padding:.8rem 1rem;margin-bottom:.4rem;box-shadow:0 1px 7px var(--shadow);border:1px solid var(--parchment);transition:all .14s;}
.member-list-row:hover{border-color:var(--gold);background:#FFFBF2;}
.member-list-name{font-family:'Cormorant Garamond',serif;font-weight:700;font-size:.95rem;color:var(--bark);}
.member-list-meta{font-size:.76rem;color:var(--mist);}

/* Detailed profile */
.dp-hero{background:linear-gradient(135deg,var(--bark),var(--moss));border-radius:18px;padding:2.2rem 2rem;margin-bottom:1.2rem;position:relative;overflow:hidden;}
.dp-hero::after{content:'🌳';position:absolute;right:2rem;bottom:-10px;font-size:5.5rem;opacity:.1;}
.dp-hero-name{font-family:'Cormorant Garamond',serif;font-size:2rem;font-weight:700;color:var(--gold);}
.dp-hero-meta{font-size:.85rem;color:rgba(255,255,255,.74);margin-top:.35rem;}
.dp-section{background:white;border-radius:14px;padding:1.4rem;box-shadow:0 2px 14px var(--shadow);border:1px solid var(--parchment);margin-bottom:1rem;}
.dp-section-title{font-family:'Cormorant Garamond',serif;font-size:1.15rem;font-weight:600;color:var(--bark);margin-bottom:.9rem;display:flex;align-items:center;gap:.45rem;}
.dp-stat{text-align:center;padding:.7rem;}
.dp-stat-num{font-family:'Cormorant Garamond',serif;font-size:1.7rem;font-weight:700;color:var(--bark);}
.dp-stat-lbl{font-size:.68rem;text-transform:uppercase;letter-spacing:1px;color:var(--mist);}
.dp-bio{font-size:.9rem;line-height:1.7;color:var(--ink);font-style:italic;border-left:3px solid var(--gold);padding-left:1rem;}
.dp-rel-card{background:var(--parchment);border-radius:10px;padding:.65rem .9rem;display:flex;align-items:center;gap:.65rem;margin-bottom:.4rem;}
.dp-rel-name{font-weight:600;font-size:.86rem;color:var(--bark);}
.dp-rel-type{font-size:.73rem;color:var(--mist);}
.privacy-label{font-size:.86rem;color:var(--ink);}
.privacy-hint{font-size:.73rem;color:var(--mist);}

/* Tree */
.tree-container{background:white;border-radius:16px;overflow:hidden;box-shadow:0 4px 28px var(--shadow);border:1px solid var(--parchment);margin-bottom:1.2rem;}

/* Profile modal */
.profile-modal{background:white;border-radius:16px;padding:1.8rem;box-shadow:0 4px 28px rgba(28,28,28,.15);border:1.5px solid var(--parchment);margin-bottom:1.2rem;}
.profile-detail-key{color:var(--mist);font-size:.7rem;text-transform:uppercase;letter-spacing:1px;}

/* === MEMORY PRESERVATION === */

/* Album grid */
.album-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(210px,1fr));gap:1rem;margin-top:.8rem;}
.album-card{background:white;border-radius:14px;overflow:hidden;box-shadow:0 2px 14px var(--shadow);border:1.5px solid var(--parchment);cursor:pointer;transition:all .18s;}
.album-card:hover{border-color:var(--gold);transform:translateY(-3px);box-shadow:0 6px 20px rgba(92,61,46,.14);}
.album-cover{width:100%;height:140px;object-fit:cover;background:linear-gradient(135deg,var(--bark),var(--moss));}
.album-cover-placeholder{width:100%;height:140px;display:flex;align-items:center;justify-content:center;font-size:3rem;background:linear-gradient(135deg,#F0EBE1,#E8DDD0);}
.album-info{padding:.9rem;}
.album-title{font-family:'Cormorant Garamond',serif;font-size:1rem;font-weight:700;color:var(--bark);}
.album-meta{font-size:.73rem;color:var(--mist);margin-top:.2rem;}

/* Media grid */
.media-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));gap:.7rem;}
.media-thumb{border-radius:10px;overflow:hidden;cursor:pointer;position:relative;aspect-ratio:1;transition:all .15s;}
.media-thumb:hover .media-overlay{opacity:1;}
.media-thumb img{width:100%;height:100%;object-fit:cover;}
.media-overlay{position:absolute;inset:0;background:rgba(0,0,0,.45);opacity:0;transition:opacity .15s;display:flex;align-items:flex-end;padding:.5rem;}
.media-caption{color:white;font-size:.73rem;line-height:1.3;}

/* Diary */
.diary-entry{background:white;border-radius:14px;padding:1.4rem;box-shadow:0 2px 14px var(--shadow);border:1.5px solid var(--parchment);margin-bottom:.9rem;transition:all .15s;cursor:pointer;}
.diary-entry:hover{border-color:var(--gold);}
.diary-date{font-size:.72rem;text-transform:uppercase;letter-spacing:1.2px;color:var(--mist);margin-bottom:.3rem;}
.diary-title{font-family:'Cormorant Garamond',serif;font-size:1.2rem;font-weight:700;color:var(--bark);margin-bottom:.4rem;}
.diary-preview{font-size:.86rem;color:var(--mist);line-height:1.55;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;}
.diary-mood{font-size:1.2rem;float:right;margin-left:.5rem;}
.diary-full-content{font-size:.92rem;line-height:1.75;color:var(--ink);white-space:pre-wrap;}

/* Timeline */
.timeline-wrap{position:relative;padding-left:2rem;margin-top:.5rem;}
.timeline-wrap::before{content:'';position:absolute;left:.5rem;top:0;bottom:0;width:2px;background:linear-gradient(to bottom,var(--gold),var(--moss));}
.tl-event{position:relative;margin-bottom:1.4rem;}
.tl-dot{position:absolute;left:-1.65rem;top:.3rem;width:14px;height:14px;border-radius:50%;background:var(--gold);border:2.5px solid white;box-shadow:0 0 0 2px var(--gold);}
.tl-card{background:white;border-radius:13px;padding:1.1rem 1.3rem;box-shadow:0 2px 12px var(--shadow);border:1.5px solid var(--parchment);transition:all .15s;}
.tl-card:hover{border-color:var(--gold);}
.tl-event-type{font-size:.7rem;text-transform:uppercase;letter-spacing:1.2px;color:var(--mist);margin-bottom:.2rem;}
.tl-title{font-family:'Cormorant Garamond',serif;font-size:1.1rem;font-weight:700;color:var(--bark);}
.tl-date{font-size:.78rem;color:var(--mist);}
.tl-desc{font-size:.84rem;color:var(--mist);margin-top:.4rem;line-height:1.5;}
.tl-loc{font-size:.76rem;color:var(--mist);margin-top:.3rem;}

/* Photo upload zone */
.photo-upload-zone{border:2px dashed var(--gold);border-radius:12px;padding:1.1rem;text-align:center;background:#FFFBF2;margin-bottom:.9rem;}
.photo-preview-wrap{display:flex;flex-direction:column;align-items:center;gap:.55rem;margin-bottom:.9rem;}

/* Tabs */
[data-baseweb="tab-list"]{border-bottom:2px solid var(--parchment)!important;}
[data-baseweb="tab"]{font-family:'DM Sans',sans-serif!important;}

/* Search result */
.search-result{background:var(--parchment);border-radius:8px;padding:.65rem .9rem;margin:.25rem 0;font-size:.86rem;}

/* Slideshow */
.slideshow-img{width:100%;max-height:500px;object-fit:contain;border-radius:12px;background:#1a1a1a;}

@media (prefers-color-scheme: dark) {
  :root{
    --cream:#1A1612; --parchment:#2A2320; --bark:#E8C99A; --moss:#7DBF9E;
    --gold:#E8B84B; --rust:#E8845A; --ink:#F0EBE1; --mist:#A8B8AA;
    --shadow:rgba(0,0,0,0.40); --card-bg:#242018;
  }
  html,body,[data-testid="stAppViewContainer"]{background:var(--cream)!important;color:var(--ink)!important;}
  .card,.stat-card,.feed-card,.dp-section,.member-card,.member-list-row,
  .album-card,.diary-entry,.tl-card,.filter-strip,.profile-modal,
  .search-result,.rel-chip,.dp-rel-card{background:var(--card-bg)!important;border-color:var(--parchment)!important;}
  .member-list-row:hover{background:#2E2820!important;}
  .photo-upload-zone{background:#2A2218!important;border-color:var(--gold)!important;}
  .badge-gold{background:#3A2E10!important;color:#E8C47A!important;border-color:#8A6A20!important;}
  .badge-green{background:#0F2A1A!important;color:#7DBF9E!important;border-color:#2A6A4A!important;}
  .badge-blue{background:#0F1A3A!important;color:#7A9AE8!important;border-color:#2A4AAA!important;}
  .badge-purple{background:#1A0F3A!important;color:#A87AE8!important;border-color:#5A2AAA!important;}
  .badge-red{background:#3A0F0F!important;color:#E87A7A!important;border-color:#AA2A2A!important;}
  .msg-success{background:#0F2A1A!important;border-color:var(--moss)!important;color:#7DBF9E!important;}
  .msg-error{background:#2A0F0F!important;border-color:#C0392B!important;color:#E87A7A!important;}
  .msg-info{background:#0F1A3A!important;border-color:#3B6ECA!important;color:#7A9AE8!important;}
  .fancy-divider{background:linear-gradient(to right,transparent,var(--parchment),transparent)!important;}
  .diary-preview,.tl-desc{color:var(--mist)!important;}
  .dp-stat-num,.stat-num,.card-title,.dp-section-title,.member-card-name,
  .member-list-name,.diary-title,.tl-title,.album-title,.feed-title,
  .dp-hero-name,.namaste-title,.dp-rel-name,.rel-type{color:var(--bark)!important;}
  .tl-dot{border-color:var(--card-bg)!important;}
  [data-testid="stButton"]>button{background:var(--card-bg)!important;color:var(--ink)!important;border-color:var(--parchment)!important;}
  [data-testid="stButton"]>button[kind="primary"]{background:linear-gradient(135deg,var(--bark),var(--moss))!important;color:#1A1612!important;}
  [data-baseweb="tab-list"]{border-color:var(--parchment)!important;}
  [data-testid="stTextInput"] input,[data-testid="stTextArea"] textarea,
  [data-baseweb="select"] div{background:var(--card-bg)!important;color:var(--ink)!important;border-color:var(--parchment)!important;}
}
</style>
""", unsafe_allow_html=True)

# ── Session state ─────────────────────────────────────────────────────────────
_defaults = {
    "page": "landing", "user": None,
    "otp_email": None,
    "reg_step": 1, "reg_data": {},
    "msg": None, "msg_type": "info",
    "viewed_profile": None,
    "search_view": "grid",
    "ds_query": "", "ds_gen": "All", "ds_city": "",
    "ds_age_min": 0, "ds_age_max": 120,
    "ds_occ": "", "ds_gender": "All",
    "tree_view": "Top-Down", "tree_zoom": 100,
    "dp_target_uid": None,
    # Album
    "current_album_id": None,
    "album_view": "grid",
    "slideshow_idx": 0,
    # Diary
    "diary_entry_id": None,
    "diary_mode": "list",  # list | view | edit | new
    # Timeline
    "tl_filter": "All",
    "tl_branch": "Full",
    # Dashboard tab (use index, not jump_tab)
    "active_tab": 0,
}
for k, v in _defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v

def show_msg():
    if st.session_state.msg:
        css = {"success": "msg-success", "error": "msg-error", "info": "msg-info"}.get(st.session_state.msg_type, "msg-info")
        st.markdown(f'<div class="{css}">{st.session_state.msg}</div>', unsafe_allow_html=True)
        st.session_state.msg = None

def set_msg(t, k="info"):
    st.session_state.msg = t
    st.session_state.msg_type = k

def goto(p):
    st.session_state.page = p
    st.session_state.msg = None

def render_hero():
    st.markdown("""
    <div class="hero">
        <div class="hero-title">🌳 VanshaVriksha</div>
        <div class="hero-sub">Preserve your dynasty · Connect generations · Build your family tree</div>
    </div>""", unsafe_allow_html=True)

def _infer_generation(age):
    if age < 18:  return "Gen Z (< 18)"
    if age < 35:  return "Millennial (18–34)"
    if age < 55:  return "Gen X (35–54)"
    if age < 75:  return "Boomer (55–74)"
    return "Senior (75+)"

def fmt_feed_time(ts):
    if not ts: return ""
    if hasattr(ts, "tzinfo") and ts.tzinfo:
        ts = ts.replace(tzinfo=None)
    diff = datetime.utcnow() - ts
    if diff.days == 0:
        h = diff.seconds // 3600
        if h == 0:
            m = diff.seconds // 60
            return f"{m}m ago" if m > 0 else "just now"
        return f"{h}h ago"
    if diff.days < 7:  return f"{diff.days}d ago"
    if diff.days < 30: return f"{diff.days // 7}w ago"
    return ts.strftime("%d %b %Y")

def ensure_dob(val):
    if isinstance(val, date): return val
    return date.fromisoformat(str(val))

# ══════════════════════════════════════════════════════════════════════════════
# LANDING
# ══════════════════════════════════════════════════════════════════════════════
def page_landing():
    render_hero()
    if _db_error:
        st.markdown(f'<div class="msg-error">🔌 DB not connected. Please try again later.</div>', unsafe_allow_html=True)

    c1, c2, c3 = st.columns([1, 1.2, 1])
    with c2:
        st.markdown('<div class="card-title">Welcome</div>', unsafe_allow_html=True)
        a, b = st.columns(2)
        with a:
            if st.button("🔑 Login", use_container_width=True, type="primary"):
                goto("login"); st.rerun()
        with b:
            if st.button("✨ Register", use_container_width=True):
                goto("register"); st.rerun()

    st.markdown("---")
    cols = st.columns(3)
    features = [
        ("🏰", "Dynasty Registry", "Connect every member under your family dynasty name."),
        ("🔗", "Family Links", "Map parents, siblings, spouses, children & grandparents."),
        ("🔍", "Smart Discovery", "Search & find relatives across the entire platform."),
    ]
    for col, (icon, title, desc) in zip(cols, features):
        with col:
            st.markdown(f'<div class="card" style="text-align:center;padding:1.3rem 1rem;"><div style="font-size:1.8rem;margin-bottom:.4rem;">{icon}</div><div style="font-family:\'Cormorant Garamond\',serif;font-size:1.05rem;font-weight:700;color:var(--bark);">{title}</div><div style="font-size:.8rem;color:var(--mist);margin-top:.35rem;">{desc}</div></div>', unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════════════════════
# LOGIN
# ══════════════════════════════════════════════════════════════════════════════
def page_login():
    render_hero(); show_msg()
    c1, c2, c3 = st.columns([1, 1.4, 1])
    with c2:
        st.markdown('<div class="card-title">🔑 Sign In</div>', unsafe_allow_html=True)
        email    = st.text_input("Email", placeholder="", key="li_email")
        password = st.text_input("Password", type="password", placeholder="", key="li_pass")

        if st.button("Login", type="primary", use_container_width=True):
            if not email or not password:
                set_msg("Fill in all fields.", "error")
            elif not db_ok():
                set_msg("Database not connected.", "error")
            else:
                u = get_user_email(email)
                if not u:
                    set_msg("No account with this email.", "error")
                elif not u["verified"]:
                    set_msg("Email not verified yet.", "error")
                elif not check_pw(password, u["password"]):
                    set_msg("Wrong password.", "error")
                else:
                    st.session_state.user = dict(u)
                    set_msg(f"Welcome back, {u['full_name']}! 🌿", "success")
                    goto("dashboard")
            st.rerun()

        st.markdown('<hr class="fancy-divider">', unsafe_allow_html=True)
        b1, b2 = st.columns(2)
        with b1:
            if st.button("← Back", use_container_width=True): goto("landing"); st.rerun()
        with b2:
            if st.button("Register →", use_container_width=True): goto("register"); st.rerun()

# ══════════════════════════════════════════════════════════════════════════════
# REGISTER — 3-step wizard
# ══════════════════════════════════════════════════════════════════════════════
def page_register():
    render_hero(); show_msg()
    step = st.session_state.reg_step
    st.progress(step / 2, text=f"Step {step} of 2")
    if step == 1: _step1()
    else: _step2()

def _step1():
    c1, c2, c3 = st.columns([.5, 2, .5])
    with c2:
        st.markdown('<div class="card-title">👤 Account Details</div>', unsafe_allow_html=True)
        d = st.session_state.reg_data
        full_name = st.text_input("Full Name *",    value=d.get("full_name", ""),    placeholder="")
        email     = st.text_input("Email *",        value=d.get("email", ""),        placeholder="")
        pass1     = st.text_input("Password *",     type="password",                 placeholder="")
        pass2     = st.text_input("Confirm Password *",  type="password",                 placeholder="")
        dob_val   = ensure_dob(d["dob"]) if d.get("dob") else None
        dob       = st.date_input("Date of Birth *", value=dob_val, min_value=date(1600, 1, 1), max_value=date.today(), format="DD/MM/YYYY")
        dynasty   = st.text_input("Dynasty Name *", value=d.get("dynasty_name", ""), placeholder="")
        st.caption("🏰 Dynasty name connects you with other family members.")

        b1, b2 = st.columns(2)
        with b1:
            if st.button("← Home", use_container_width=True): goto("landing"); st.rerun()
        with b2:
            if st.button("Continue →", type="primary", use_container_width=True):
                errs = []
                if not full_name.strip(): errs.append("Full Name required")
                if not email.strip() or not valid_email(email): errs.append("Valid email required")
                if len(pass1) < 8: errs.append("Password ≥ 8 chars")
                if pass1 != pass2: errs.append("Passwords don't match")
                if not dynasty.strip(): errs.append("Dynasty Name required")
                if dob is None: errs.append("Date of birth required")
                if errs:
                    set_msg("• " + "<br>• ".join(errs), "error")
                elif db_ok() and get_user_email(email):
                    set_msg("Email already registered.", "error")
                else:
                    d.update({"full_name": full_name.strip(), "email": email.lower().strip(),
                              "password": pass1, "dob": dob.isoformat(), "dynasty_name": dynasty.strip()})
                    st.session_state.reg_step = 2
                st.rerun()

def _step2():
    c1, c2, c3 = st.columns([.5, 2, .5])
    with c2:
        st.markdown('<div class="card-title">📋 Profile Details <span style="font-size:.8rem;color:var(--mist);">(Optional)</span></div>', unsafe_allow_html=True)
        d = st.session_state.reg_data
        opts         = ["Prefer not to say", "Male", "Female", "Other"]
        gender       = st.selectbox("Gender", opts, index=opts.index(d.get("gender", "Prefer not to say")))
        birth_city   = st.text_input("Birth City",   value=d.get("birth_city", ""),   placeholder="")
        current_city = st.text_input("Current City", value=d.get("current_city", ""), placeholder="")
        occupation   = st.text_input("Occupation",   value=d.get("occupation", ""),   placeholder="")
        religion     = st.text_input("Religion",     value=d.get("religion", ""),     placeholder="")
        caste        = st.text_input("Caste",        value=d.get("caste", ""),        placeholder="")
        gotram       = st.text_input("Gotram",       value=d.get("gotram", ""),       placeholder="")

        st.markdown('<hr class="fancy-divider">', unsafe_allow_html=True)
        st.markdown("**📷 Profile Photo** *(optional)*")
        photo_file = st.file_uploader(
            "Upload a photo (JPG/PNG, max 800 KB)",
            type=["jpg", "jpeg", "png", "webp"],
            key="reg_photo", label_visibility="collapsed",
        )

        if photo_file:
            photo_data, err = process_photo(photo_file)
            if err:
                set_msg(err, "error")
            else:
                d["profile_photo"] = photo_data
                initials = "".join(p[0].upper() for p in d.get("full_name", "?").split()[:2]) or "?"
                _reg_av = avatar_html(photo_data, initials, 80)
                st.markdown(
                    f'<div class="photo-preview-wrap">{_reg_av}'
                    f'<span style="font-size:.76rem;color:var(--mist);">Preview</span></div>',
                    unsafe_allow_html=True)

        b1, b2 = st.columns(2)
        with b1:
            if st.button("← Back", use_container_width=True): st.session_state.reg_step = 1; st.rerun()
        with b2:
            if st.button("✅ Register", type="primary", use_container_width=True):
                d.update({"gender": gender, "birth_city": birth_city.strip(),
          "current_city": current_city.strip(), "occupation": occupation.strip(),
          "religion": religion.strip(), "caste": caste.strip(), "gotram": gotram.strip()})
                if db_ok():
                    try:
                        row = q_exec_return("""
                            INSERT INTO users(full_name,email,password,dob,dynasty_name,
                                              gender,birth_city,current_city,occupation,
                                              religion,caste,gotram,
                                              profile_photo,verified)
                            VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,TRUE) RETURNING *""",
                            (d["full_name"], d["email"], hash_pw(d["password"]),
                             d["dob"], d["dynasty_name"], d.get("gender", ""),
                             d.get("birth_city", ""), d.get("current_city", ""),
                             d.get("occupation", ""), d.get("religion", ""),
                             d.get("caste", ""), d.get("gotram", ""),
                             d.get("profile_photo", "")))
                        st.session_state.user     = dict(row)
                        st.session_state.reg_data = {}
                        st.session_state.reg_step = 1
                        set_msg(f"Welcome, {d['full_name']}! 🌳", "success")
                        goto("dashboard")
                    except Exception as e:
                        set_msg("Registration failed. Please try again.", "error")
                else:
                    set_msg("DB not connected.", "error")
                st.rerun()

# ══════════════════════════════════════════════════════════════════════════════
# DASHBOARD HELPERS
# ══════════════════════════════════════════════════════════════════════════════
def get_dashboard_stats(uid, dynasty):
    family_cnt  = q_one("SELECT COUNT(*) as c FROM family_links WHERE user_id=%s", (uid,))
    dynasty_cnt = q_one("SELECT COUNT(*) as c FROM users WHERE dynasty_name=%s", (dynasty,))
    album_cnt   = q_one("SELECT COUNT(*) as c FROM family_albums WHERE user_id=%s OR dynasty_name=%s", (uid, dynasty))
    diary_cnt   = q_one("SELECT COUNT(*) as c FROM family_diary WHERE user_id=%s AND is_draft=FALSE", (uid,))
    return (
        family_cnt["c"]  if family_cnt  else 0,
        dynasty_cnt["c"] if dynasty_cnt else 0,
        album_cnt["c"]   if album_cnt   else 0,
        diary_cnt["c"]   if diary_cnt   else 0,
    )

def get_activity_feed(uid, dynasty):
    feed = []
    links = q_all("""
        SELECT fl.member_name, fl.relation, fl.created_at, u.full_name as linked_name
        FROM family_links fl LEFT JOIN users u ON u.id = fl.member_id
        WHERE fl.user_id = %s ORDER BY fl.created_at DESC LIMIT 6
    """, (uid,))
    for lk in links:
        name = lk.get("linked_name") or lk["member_name"]
        feed.append({"type": "link", "text": f"You linked <strong>{name}</strong> as {lk['relation']}",
                     "time": lk["created_at"], "dot": "green"})

    new_members = q_all("""
        SELECT full_name, created_at FROM users
        WHERE dynasty_name=%s AND id!=%s ORDER BY created_at DESC LIMIT 4
    """, (dynasty, uid))
    for m in new_members:
        feed.append({"type": "member", "text": f"<strong>{m['full_name']}</strong> joined your dynasty",
                     "time": m["created_at"], "dot": "rust"})

    new_albums = q_all("""
        SELECT title, created_at FROM family_albums
        WHERE dynasty_name=%s ORDER BY created_at DESC LIMIT 3
    """, (dynasty,))
    for a in new_albums:
        feed.append({"type": "album", "text": f"Album <strong>{a['title']}</strong> was created",
                     "time": a["created_at"], "dot": "purple"})

    new_events = q_all("""
        SELECT title, event_type, created_at FROM family_timeline
        WHERE dynasty_name=%s ORDER BY created_at DESC LIMIT 3
    """, (dynasty,))
    for ev in new_events:
        feed.append({"type": "event", "text": f"Timeline: <strong>{ev['event_type']} — {ev['title']}</strong>",
                     "time": ev["created_at"], "dot": "gold"})

    feed.sort(key=lambda x: x["time"].replace(tzinfo=None) if x["time"] and hasattr(x["time"], "tzinfo") and x["time"].tzinfo else (x["time"] or datetime.min), reverse=True)
    return feed[:10]

def _render_namaste_banner(u, initials, age):
    first = u["full_name"].split()[0]
    h = datetime.utcnow().hour
    greeting = "Suprabhat" if h < 12 else ("Namaste" if h < 17 else "Shubh Sandhya")
    _banner_av   = avatar_html(u.get("profile_photo") or None, initials, 60)
    _city_info   = f"&nbsp;·&nbsp; 🏙️ {_esc(u['current_city'])}" if u.get('current_city') else "&nbsp;·&nbsp; 🏙️ —"
    _occ_info    = f"&nbsp;·&nbsp; 💼 {_esc(u['occupation'])}" if u.get('occupation') else ""
    st.markdown(f"""
    <div class="namaste-banner">
        {_banner_av}
        <div>
            <div class="namaste-title">{_esc(greeting)}, {_esc(first)}! 🙏</div>
            <div class="namaste-sub">
                🏰 {_esc(u['dynasty_name'])} Dynasty &nbsp;·&nbsp; 🎂 Age {age}
                {_city_info}{_occ_info}
            </div>
        </div>
    </div>""", unsafe_allow_html=True)

def _render_stat_cards(family_cnt, dynasty_cnt, album_cnt, diary_cnt):
    st.markdown(f"""
    <div class="stat-grid">
        <div class="stat-card"><div class="stat-icon">👨‍👩‍👧‍👦</div><div class="stat-num">{family_cnt}</div><div class="stat-label">Family Links</div></div>
        <div class="stat-card"><div class="stat-icon">🏰</div><div class="stat-num">{dynasty_cnt}</div><div class="stat-label">Dynasty Members</div></div>
        <div class="stat-card"><div class="stat-icon">📸</div><div class="stat-num">{album_cnt}</div><div class="stat-label">Albums</div></div>
        <div class="stat-card"><div class="stat-icon">📖</div><div class="stat-num">{diary_cnt}</div><div class="stat-label">Diary Entries</div></div>
    </div>""", unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════════════════════
# 2.4  DETAILED MEMBER PROFILE
# ══════════════════════════════════════════════════════════════════════════════
def _detailed_profile_tab(current_uid):
    target_uid = st.session_state.get("dp_target_uid") or current_uid
    u = get_user(target_uid)
    if not u:
        st.markdown('<div class="msg-error">Profile not found.</div>', unsafe_allow_html=True)
        return
    u = dict(u)
    is_self = (target_uid == current_uid)
    dob     = ensure_dob(u["dob"])
    age     = calc_age(dob)
    initials = "".join(p[0].upper() for p in u["full_name"].split()[:2])
    links   = get_links(target_uid)
    priv_dob   = u.get("privacy_dob",   True)
    priv_email = u.get("privacy_email", False)
    priv_city  = u.get("privacy_city",  True)
    priv_occ   = u.get("privacy_occ",   True)

    if not is_self and st.session_state.get("dp_target_uid"):
        if st.button("← Back to my profile", key="dp_back"):
            st.session_state.dp_target_uid = None; st.rerun()

    _age_meta    = f"&nbsp;·&nbsp; 🎂 Age {age}" if priv_dob or is_self else ""
    _city_meta   = f"&nbsp;·&nbsp; 🏙️ {_esc(u['current_city'])}" if (priv_city or is_self) and u.get('current_city') else ("&nbsp;·&nbsp; 🏙️ —" if is_self else "")
    _verified_b  = '<span class="badge badge-green">✓ Verified</span>' if u.get("verified") else ""
    _occ_b       = f'<span class="badge badge-blue">💼 {_esc(u["occupation"])}</span>' if (priv_occ or is_self) and u.get("occupation") else ""
    _hero_av     = avatar_html(u.get("profile_photo") or None, initials, 90)
    st.markdown(f"""
    <div class="dp-hero">
        <div style="display:flex;align-items:center;gap:1.4rem;">
            {_hero_av}
            <div>
                <div class="dp-hero-name">{_esc(u['full_name'])}</div>
                <div class="dp-hero-meta">
                    🏰 {_esc(u['dynasty_name'])} &nbsp;·&nbsp; {_infer_generation(age)}
                    {_age_meta}{_city_meta}
                </div>
                <div style="margin-top:.55rem;display:flex;flex-wrap:wrap;gap:.3rem;">
                    <span class="badge badge-gold">🌳 {len(links)} Family Links</span>
                    {_verified_b}{_occ_b}
                </div>
            </div>
        </div>
    </div>""", unsafe_allow_html=True)

    st.markdown(f"""
    <div class="dp-section">
        <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:0;text-align:center;">
            <div class="dp-stat" style="border-right:1px solid var(--parchment);">
                <div class="dp-stat-num">{len(links)}</div><div class="dp-stat-lbl">Family Links</div>
            </div>
            <div class="dp-stat" style="border-right:1px solid var(--parchment);">
                <div class="dp-stat-num">{sum(1 for lk in links if lk.get("member_id"))}</div><div class="dp-stat-lbl">Verified</div>
            </div>
            <div class="dp-stat" style="border-right:1px solid var(--parchment);">
                <div class="dp-stat-num">{age}</div><div class="dp-stat-lbl">Age</div>
            </div>
            <div class="dp-stat">
                <div class="dp-stat-num">{len(set(lk["relation"] for lk in links))}</div><div class="dp-stat-lbl">Relation Types</div>
            </div>
        </div>
    </div>""", unsafe_allow_html=True)

    col_left, col_right = st.columns([3, 2])
    with col_left:
        st.markdown('<div class="dp-section-title">👤 Personal Details</div>', unsafe_allow_html=True)
        details = []
        if priv_dob or is_self:
            details.append(("🎂 Date of Birth", dob.strftime("%d %B %Y")))
        details.append(("⚧ Gender", u.get("gender") or "—"))
        if u.get("birth_city"): details.append(("🏡 Birth City", u["birth_city"]))
        if (priv_city or is_self) and u.get("current_city"): details.append(("🏙️ Current City", u["current_city"]))
        if (priv_occ  or is_self) and u.get("occupation"):   details.append(("💼 Occupation", u["occupation"]))
        if u.get("religion"):  details.append(("🛕 Religion", u["religion"]))
        if u.get("caste"):     details.append(("🏷️ Caste",    u["caste"]))
        if u.get("gotram"):    details.append(("🔱 Gotram",   u["gotram"]))
        if priv_email or is_self: details.append(("📧 Email", u.get("email", "—")))
        if u.get("created_at"): details.append(("📅 Member Since", u["created_at"].strftime("%B %Y")))
        for k, v in details:
            st.markdown(f"""
            <div style="display:flex;justify-content:space-between;padding:.4rem 0;border-bottom:1px solid var(--parchment);">
                <span style="font-size:.72rem;text-transform:uppercase;letter-spacing:1px;color:var(--mist);">{k}</span>
                <span style="font-size:.86rem;font-weight:500;color:var(--ink);">{v}</span>
            </div>""", unsafe_allow_html=True)

        bio = u.get("bio", "")
        if bio or is_self:
            st.markdown('<div class="dp-section-title">📖 About</div>', unsafe_allow_html=True)
            if bio:
                st.markdown(f'<div class="dp-bio">{_esc(bio)}</div>', unsafe_allow_html=True)
            else:
                st.markdown('<div style="color:var(--mist);font-size:.86rem;font-style:italic;">No bio written yet.</div>', unsafe_allow_html=True)
            if is_self:
                with st.expander("✏️ Edit Bio"):
                    new_bio = st.text_area("Your bio (max 300 chars)", value=bio, max_chars=300, key="dp_bio_edit")
                    if st.button("Save Bio", key="dp_bio_save", type="primary"):
                        q_exec("UPDATE users SET bio=%s WHERE id=%s", (new_bio.strip(), current_uid))
                        get_user.clear()
                        st.session_state.user = dict(get_user(current_uid))
                        set_msg("Bio updated! ✨", "success"); st.rerun()

    with col_right:
        st.markdown('<div class="dp-section-title">👨‍👩‍👧‍👦 Family Relations</div>', unsafe_allow_html=True)
        if links:
            grouped = {}
            for lk in links: grouped.setdefault(lk["relation"], []).append(lk)
            for group_label, group_rels in RELATION_GROUPS.items():
                hits = [r for r in group_rels if r in grouped]
                if not hits: continue
                st.markdown(f'<div style="font-size:.68rem;text-transform:uppercase;letter-spacing:1.1px;color:var(--mist);margin:.55rem 0 .25rem;">{group_label}</div>', unsafe_allow_html=True)
                for rel in hits:
                    for lk in grouped[rel]:
                        name = lk.get("linked_name") or lk["member_name"]
                        lk_init = "".join(p[0].upper() for p in name.split()[:2])
                        lk_age_str = ""
                        if lk.get("linked_dob"):
                            try: lk_age_str = f" · {calc_age(ensure_dob(lk['linked_dob']))}y"
                            except: pass
                        verified_badge = "✓" if lk.get("member_id") else ""
                        _lk_av = avatar_html(lk.get("linked_photo") or None, lk_init, 32)
                        st.markdown(f"""
                        <div class="dp-rel-card">
                            {_lk_av}
                            <div><div class="dp-rel-name">{_esc(name)} {verified_badge}</div>
                            <div class="dp-rel-type">{_esc(rel)}{lk_age_str}</div></div>
                        </div>""", unsafe_allow_html=True)
        else:
            st.markdown('<div style="color:var(--mist);font-size:.86rem;">No relations added yet.</div>', unsafe_allow_html=True)

        if is_self:
            st.markdown('<div class="dp-section-title">🔒 Privacy</div>', unsafe_allow_html=True)
            st.markdown('<div style="font-size:.76rem;color:var(--mist);margin-bottom:.7rem;">Control what others can see</div>', unsafe_allow_html=True)

            _PRIVACY_COLS = {"privacy_dob", "privacy_email", "privacy_city", "privacy_occ"}
            def privacy_toggle(label, hint, field, current_val, key):
                col_a, col_b = st.columns([3, 1])
                with col_a:
                    st.markdown(f'<div class="privacy-label">{label}</div><div class="privacy-hint">{hint}</div>', unsafe_allow_html=True)
                with col_b:
                    new_val = st.toggle("", value=current_val, key=key)
                if new_val != current_val:
                    if field not in _PRIVACY_COLS:
                        raise ValueError(f"Illegal column: {field}")
                    q_exec(f"UPDATE users SET {field}=%s WHERE id=%s", (new_val, current_uid))
                    get_user.clear()
                    st.session_state.user = dict(get_user(current_uid)); st.rerun()

            privacy_toggle("Show Date of Birth", "Visible to all members", "privacy_dob", priv_dob, "priv_dob_tog")
            st.markdown('<hr class="fancy-divider">', unsafe_allow_html=True)
            privacy_toggle("Show Email", "Visible to all members", "privacy_email", priv_email, "priv_email_tog")
            st.markdown('<hr class="fancy-divider">', unsafe_allow_html=True)
            privacy_toggle("Show City", "Current city visible", "privacy_city", priv_city, "priv_city_tog")
            st.markdown('<hr class="fancy-divider">', unsafe_allow_html=True)
            privacy_toggle("Show Occupation", "Job/career visible", "privacy_occ", priv_occ, "priv_occ_tog")

# ══════════════════════════════════════════════════════════════════════════════
# 2.5  INTERACTIVE FAMILY TREE
# ══════════════════════════════════════════════════════════════════════════════
def _build_tree_data(uid):
    """
    Build a flat node dict for the family tree.

    Key design decisions
    ────────────────────
    1.  COUPLES are placed side-by-side. A "union node" (virtual, invisible) is
        inserted at the midpoint between each couple. Children hang from the
        union node, NOT from any individual person.

    2.  LAYOUT (gen 0 row):
            [Sister | BIL]  gap  [You | Spouse]
        Sister always sits to the LEFT of BIL (bloodline on the outside).
        You always sit to the LEFT of Spouse.
        A large gap separates the two family units.

    3.  PARENTAGE is stored as parentUnionKey on every descendant node:
            • Your children   → "union_you"
            • Nieces/Nephews  → "union_sib"
        The JS uses parentUnionKey to look up the correct X coordinate to
        drop the edge from, eliminating all coordinate-guessing.

    4.  PARENTS (gen -1) connect down to BOTH You and all Siblings via a shared
        horizontal bar at mid-height between gen -1 and gen 0.
    """
    u = get_user(uid)
    if not u:
        return {}, None
    u = dict(u)
    dob = ensure_dob(u["dob"])
    age = calc_age(dob)

    # ── Relation category sets ────────────────────────────────────────────────
    SPOUSE_RELS  = {"Husband", "Wife", "Partner"}
    SISTER_RELS  = {"Sister", "Stepsister"}
    BROTHER_RELS = {"Brother", "Stepbrother"}
    SIBLING_RELS = SISTER_RELS | BROTHER_RELS
    BIL_RELS     = {"Brother-in-law", "Husband's Brother",
                    "Wife's Sister's Husband",
                    "Husband's Sister", "Brother's Wife", "Wife's Sister"}
    NIECE_NEPHEW = {"Niece", "Nephew"}
    CHILD_RELS   = {"Son", "Daughter", "Stepson", "Stepdaughter"}
    PARENT_RELS  = {"Father", "Mother", "Stepfather", "Stepmother"}

    # ── Layout constants ──────────────────────────────────────────────────────
    NODE_W     = 175
    NODE_H     = 90
    H_GAP      = 40   # gap between ordinary nodes in a row
    COUPLE_GAP = 8    # tighter gap between the two people in a couple
    FAMILY_GAP = 80   # extra separation between [sis+BIL] and [You+Spouse]
    V_GAP      = 110  # vertical distance between generation rows
    ROW_H      = NODE_H + V_GAP

    # ── Build all nodes ───────────────────────────────────────────────────────
    nodes = {}
    self_id = f"self_{uid}"
    nodes[self_id] = {
        "id": self_id, "label": u["full_name"], "age": age, "gen": 0,
        "photo": u.get("profile_photo", "") or "",
        "dynasty": u["dynasty_name"], "occupation": u.get("occupation", ""),
        "city": u.get("current_city", ""), "isSelf": True,
        "relation": "You", "verified": True, "uid": uid,
        "spouseId": None, "parentUnionKey": None,
        "isSpouse": False, "isSibling": False, "isBIL": False,
        "isNieceNephew": False, "isChild": False, "isParent": False,
    }

    links = get_links(uid)
    for lk in links:
        nid  = f"lk_{lk['id']}"
        name = lk.get("linked_name") or lk["member_name"]
        # ── Normalize the stored relation to a canonical name ─────────────────
        rel  = normalize_relation(lk["relation"])
        go   = RELATION_GEN.get(rel, 0)
        lk_age = None
        if lk.get("linked_dob"):
            try:
                lk_age = calc_age(ensure_dob(lk["linked_dob"]))
            except Exception:
                pass
        nodes[nid] = {
            "id": nid, "label": name, "age": lk_age, "gen": go,
            "photo": lk.get("linked_photo", "") or "",
            "dynasty": lk.get("linked_dynasty", "") or "",
            "occupation": lk.get("linked_occ", "") or "",
            "city": lk.get("linked_city", "") or "",
            "isSelf": False, "relation": rel,
            "verified": bool(lk.get("member_id")),
            "uid": lk.get("member_id"),
            "spouseId": None, "parentUnionKey": None,
            "isSpouse":      rel in SPOUSE_RELS,
            "isSibling":     rel in SIBLING_RELS,
            "isBIL":         rel in BIL_RELS,
            "isNieceNephew": rel in NIECE_NEPHEW,
            "isChild":       rel in CHILD_RELS,
            "isParent":      rel in PARENT_RELS,
        }

    # ── Identify key players ──────────────────────────────────────────────────
    spouse_id  = next((nid for nid, n in nodes.items() if n.get("isSpouse")), None)
    sister_ids = [nid for nid, n in nodes.items()
                  if not n["isSelf"] and n["relation"] in SISTER_RELS]
    bil_ids    = [nid for nid, n in nodes.items()
                  if not n["isSelf"] and n["isBIL"] and
                  n["relation"] in {"Brother-in-law", "Wife's Sister's Husband"}]
    sibling_ids_all = [nid for nid, n in nodes.items()
                       if not n["isSelf"] and n.get("isSibling")]

    SIS_PIL_RELS = {"Sister's Father-in-law", "Sister's Mother-in-law"}  # Sister's Parents-in-law
    BRO_PIL_RELS = {"Brother's Father-in-law", "Brother's Mother-in-law"}

    # Pair: first sister with first Sister's-Husband-style BIL
    sister_id  = sister_ids[0] if sister_ids else None
    bil_id     = bil_ids[0]    if bil_ids    else None

    if spouse_id:
        nodes[spouse_id]["spouseId"]  = self_id
        nodes[self_id]["spouseId"]    = spouse_id
    if sister_id and bil_id:
        nodes[sister_id]["spouseId"]  = bil_id
        nodes[bil_id]["spouseId"]     = sister_id

    # ── Build gen buckets early (needed for couple detection) ─────────────────
    by_gen: dict = {}
    for nid, n in nodes.items():
        by_gen.setdefault(n["gen"], []).append(nid)

    # ── Detect ancestor couples (Father+Mother, Grandfather+Grandmother, etc.) ─
    # Each entry: {"nid_a": male_nid, "nid_b": female_nid, "gen": level,
    #              "child_nid": the specific node in gen+1 who is their blood child}
    #
    # PARENT COUPLE (gen -1): their blood children are You + all siblings.
    #   The "child_nid" is the self node (used as the T-bar anchor).
    #
    # GRANDPARENT COUPLE (gen -2): their blood child is the PARENT who belongs
    #   to their bloodline. e.g. Maternal Grandfather/Grandmother → Mother.
    #   Paternal Grandfather/Grandmother → Father.
    #
    # GREAT-GRANDPARENT COUPLE (gen -3): their blood child is their grandchild
    #   in gen -2.
    #
    # To resolve this we define which gen+1 relation(s) are the blood child
    # of each couple type.
    ANCESTOR_COUPLE_DEFS = {
        -1: [
            ({"Father", "Stepfather"}, {"Mother", "Stepmother"},
             None),   # child = self + siblings (handled specially in JS)
            ({"Father-in-law"},        {"Mother-in-law"},
             None),
        ],
        -2: [
            ({"Paternal Grandfather"}, {"Paternal Grandmother"},
             {"Father", "Stepfather"}),          # their blood child is the Father
            ({"Maternal Grandfather"}, {"Maternal Grandmother"},
             {"Mother", "Stepmother"}),           # their blood child is the Mother
        ],
        -3: [
            ({"Great-grandfather"},    {"Great-grandmother"},
             {"Paternal Grandfather", "Maternal Grandfather",
              "Paternal Grandmother", "Maternal Grandmother"}),
        ],
    }

    ancestor_couples = []       # [{"nid_a":…, "nid_b":…, "gen":…, "child_nid":…}, …]
    ancestor_coupled = set()    # nids already paired

    for gen_level, pair_defs in ANCESTOR_COUPLE_DEFS.items():
        gen_nids = by_gen.get(gen_level, [])
        child_gen_nids = by_gen.get(gen_level + 1, [])
        for pair_def in pair_defs:
            male_rels, female_rels, child_rels = pair_def
            male_nids   = [nid for nid in gen_nids
                           if nodes[nid]["relation"] in male_rels
                           and nid not in ancestor_coupled]
            female_nids = [nid for nid in gen_nids
                           if nodes[nid]["relation"] in female_rels
                           and nid not in ancestor_coupled]
            if male_nids and female_nids:
                nid_a, nid_b = male_nids[0], female_nids[0]
                nodes[nid_a]["spouseId"] = nid_b
                nodes[nid_b]["spouseId"] = nid_a
                # Find the specific blood child in the next generation
                child_nid = None
                if child_rels:
                    child_nid = next(
                        (nid for nid in child_gen_nids
                         if nodes[nid]["relation"] in child_rels),
                        None
                    )
                ancestor_couples.append({
                    "nid_a": nid_a, "nid_b": nid_b,
                    "gen": gen_level,
                    "child_nid": child_nid  # None for gen -1 (handled in JS)
                })
                ancestor_coupled.update([nid_a, nid_b])

    # ── Assign parentUnionKey ─────────────────────────────────────────────────
    for nid, n in nodes.items():
        if n.get("isChild"):
            n["parentUnionKey"] = "union_you"
    for nid, n in nodes.items():
        if n.get("isNieceNephew"):
            n["parentUnionKey"] = "union_sib" if (sister_id and bil_id) else "union_you"

    # ══════════════════════════════════════════════════════════════════════════
    # COORDINATE LAYOUT
    # ══════════════════════════════════════════════════════════════════════════
    y0 = 0  # gen 0 y-coordinate

    def unit_width(unit_list):
        return len(unit_list) * NODE_W + max(0, len(unit_list) - 1) * COUPLE_GAP

    # ── PASS 1: Gen 0 ────────────────────────────────────────────────────────
    gen0_placed = set()
    gen0_units  = []

    unit_a = []
    if sister_id and sister_id in by_gen.get(0, []):
        if bil_id and bil_id in by_gen.get(0, []):
            unit_a = [bil_id, sister_id]
            gen0_placed.update([sister_id, bil_id])
        else:
            unit_a = [sister_id]
            gen0_placed.add(sister_id)
    if unit_a:
        gen0_units.append(unit_a)

    unit_b = [self_id]
    gen0_placed.add(self_id)
    if spouse_id and spouse_id in by_gen.get(0, []):
        unit_b.append(spouse_id)
        gen0_placed.add(spouse_id)
    gen0_units.append(unit_b)

    others_g0 = [nid for nid in by_gen.get(0, []) if nid not in gen0_placed]
    if others_g0:
        gen0_units.insert(0, others_g0)

    total_g0_w = (sum(unit_width(u) for u in gen0_units)
                  + (len(gen0_units) - 1) * FAMILY_GAP)
    cur_x = -(total_g0_w / 2) + NODE_W / 2

    for unit in gen0_units:
        for j, nid in enumerate(unit):
            nodes[nid]["x"] = cur_x + j * (NODE_W + COUPLE_GAP)
            nodes[nid]["y"] = y0
        cur_x += unit_width(unit) + FAMILY_GAP

    # ── Compute gen-0 union points ────────────────────────────────────────────
    if spouse_id and spouse_id in nodes:
        union_you_x = (nodes[self_id]["x"] + nodes[spouse_id]["x"]) / 2
    else:
        union_you_x = nodes[self_id]["x"]

    if sister_id and bil_id and sister_id in nodes and bil_id in nodes:
        union_sib_x = (nodes[sister_id]["x"] + nodes[bil_id]["x"]) / 2
    elif sister_id and sister_id in nodes:
        union_sib_x = nodes[sister_id]["x"]
    else:
        union_sib_x = union_you_x

    # ── PASS 2: Gen +1 ───────────────────────────────────────────────────────
    you_children = [nid for nid, n in nodes.items()
                    if n.get("parentUnionKey") == "union_you"]
    sib_children = [nid for nid, n in nodes.items()
                    if n.get("parentUnionKey") == "union_sib"]

    y1 = 1 * ROW_H

    def place_group_under(nids, center_x, y):
        count = len(nids)
        if count == 0:
            return
        row_w = count * NODE_W + (count - 1) * H_GAP
        sx = center_x - row_w / 2 + NODE_W / 2
        for i, nid in enumerate(nids):
            nodes[nid]["x"] = sx + i * (NODE_W + H_GAP)
            nodes[nid]["y"] = y

    place_group_under(you_children, union_you_x, y1)
    place_group_under(sib_children, union_sib_x, y1)

    g1_placed = set(you_children + sib_children)
    g1_others = [nid for nid in by_gen.get(1, []) if nid not in g1_placed]
    if g1_others:
        max_x = max((nodes[nid]["x"] for nid in g1_placed), default=union_you_x)
        for i, nid in enumerate(g1_others):
            nodes[nid]["x"] = max_x + (i + 1) * (NODE_W + H_GAP)
            nodes[nid]["y"] = y1

    # ── PASS 3: Ancestor rows (gen -1, -2, -3) with couple pairing ───────────
    SINGLE_BLOOD_CHILD = {
        "Paternal Grandfather": {"Father", "Stepfather"},
        "Paternal Grandmother": {"Father", "Stepfather"},
        "Maternal Grandfather": {"Mother", "Stepmother"},
        "Maternal Grandmother": {"Mother", "Stepmother"},
        "Great-grandfather":    {"Paternal Grandfather", "Maternal Grandfather",
                                 "Paternal Grandmother", "Maternal Grandmother"},
        "Great-grandmother":    {"Paternal Grandfather", "Maternal Grandfather",
                                 "Paternal Grandmother", "Maternal Grandmother"},
        "Sister's Father-in-law":  {"Brother-in-law", "Wife's Sister's Husband"},
        "Sister's Mother-in-law":  {"Brother-in-law", "Wife's Sister's Husband"},
        "Brother's Father-in-law": {"Husband's Sister", "Brother's Wife"},
        "Brother's Mother-in-law": {"Husband's Sister", "Brother's Wife"},
    }

    def get_target_x(nid, child_nids):
        """Return the X of the blood child this ancestor should sit above."""
        rel = nodes[nid]["relation"]
        target_rels = SINGLE_BLOOD_CHILD.get(rel)
        if target_rels:
            t = next((cnid for cnid in child_nids
                      if nodes[cnid]["relation"] in target_rels
                      and "x" in nodes[cnid]), None)
            if t:
                return nodes[t]["x"]
        return None

    SIB_PIL_RELS = {"Sister's Father-in-law", "Sister's Mother-in-law",
                    "Brother's Father-in-law", "Brother's Mother-in-law"}

    for gen_level in sorted([g for g in by_gen if g < 0], reverse=True):
        nids = by_gen[gen_level]
        y    = gen_level * ROW_H
        placed_in_gen = set()
        child_gen_nids = by_gen.get(gen_level + 1, [])

        # ── SIB_PIL nodes: place as a couple unit above Brother-in-law ──────
        # MallaReddy (Sister's Father-in-law) + rajamma (Sister's Mother-in-law)
        # should sit together above Kotha Satish Reddy (BIL) in the gen-0 row.
        if gen_level == -1:
            sib_pil_nids = [nid for nid in nids if nodes[nid]["relation"] in SIB_PIL_RELS]

            if sib_pil_nids:
                # Find the BIL target x — the gen-0 node who is their child
                gen0_nids = by_gen.get(0, [])
                bil_target_nid = next(
                    (gnid for gnid in gen0_nids
                     if nodes[gnid]["relation"] in {"Brother-in-law", "Wife's Sister's Husband"}),
                    None
                )

                if bil_target_nid and "x" in nodes[bil_target_nid]:
                    bil_x = nodes[bil_target_nid]["x"]
                    # Place the SIB_PIL couple centred above the BIL node
                    count = len(sib_pil_nids)
                    group_w = count * NODE_W + (count - 1) * COUPLE_GAP
                    start_x = bil_x - group_w / 2 + NODE_W / 2
                    for i, nid in enumerate(sib_pil_nids):
                        nodes[nid]["x"] = start_x + i * (NODE_W + COUPLE_GAP)
                        nodes[nid]["y"] = y
                        placed_in_gen.add(nid)
                    # Mark them as a couple for JS marriage bar
                    if len(sib_pil_nids) == 2:
                        nodes[sib_pil_nids[0]]["spouseId"] = sib_pil_nids[1]
                        nodes[sib_pil_nids[1]]["spouseId"] = sib_pil_nids[0]
                        # Add to ancestor_couples so JS draws edge to BIL
                        # isSibPil=True tells JS NOT to treat this as a parent→Kavitha edge
                        ancestor_couples.append({
                            "nid_a": sib_pil_nids[0], "nid_b": sib_pil_nids[1],
                            "gen": -1, "child_nid": bil_target_nid,
                            "isSibPil": True
                        })
                else:
                    # BIL not found — place SIB_PIL to far left (not -9999)
                    # so they are visible but clearly separate
                    gen0_xs = [nodes[gnid]["x"] for gnid in gen0_nids if "x" in nodes[gnid]]
                    far_left = (min(gen0_xs) if gen0_xs else 0) - (NODE_W + FAMILY_GAP) * len(sib_pil_nids)
                    for i, nid in enumerate(sib_pil_nids):
                        nodes[nid]["x"] = far_left + i * (NODE_W + COUPLE_GAP)
                        nodes[nid]["y"] = y
                        placed_in_gen.add(nid)

        # Exclude SIB_PIL couples — they are already placed above BIL
        gen_couples = [ac for ac in ancestor_couples
                       if ac["gen"] == gen_level and not ac.get("isSibPil")]
        couple_nids_set = set()
        couple_units = []
        for ac in gen_couples:
            couple_units.append([ac["nid_a"], ac["nid_b"]])
            couple_nids_set.update([ac["nid_a"], ac["nid_b"]])

        singles = [nid for nid in nids if nid not in couple_nids_set and nid not in placed_in_gen]

        all_units = couple_units + [[s] for s in singles]

        if gen_level == -1:
            # Anchor the Father+Mother couple above union_you_x (centre of you+spouse)
            # so it never drifts into MallaReddy's column
            total_w = sum(unit_width(u) for u in all_units) + max(0, len(all_units) - 1) * H_GAP
            cx = union_you_x - total_w / 2 + NODE_W / 2
        else:
            def unit_sort_x(unit, child_nids=child_gen_nids):
                if len(unit) == 1:
                    tx = get_target_x(unit[0], child_nids)
                    return tx if tx is not None else 999999
                xs = [nodes[n]["x"] for n in unit if "x" in nodes[n]]
                return sum(xs) / len(xs) if xs else 0
            all_units.sort(key=unit_sort_x)
            total_w = sum(unit_width(u) for u in all_units) + max(0, len(all_units) - 1) * H_GAP
            cx = -(total_w / 2) + NODE_W / 2

        for unit in all_units:
            for j, nid in enumerate(unit):
                nodes[nid]["x"] = cx + j * (NODE_W + COUPLE_GAP)
                nodes[nid]["y"] = y
                placed_in_gen.add(nid)
            cx += unit_width(unit) + H_GAP

    # ── PASS 4: Descendant rows (gen +2, +3) ─────────────────────────────────
    for gen, nids in by_gen.items():
        if gen <= 1:
            continue
        count = len(nids)
        row_w = count * NODE_W + (count - 1) * H_GAP
        start_x = -(row_w / 2) + NODE_W / 2
        y = gen * ROW_H
        for i, nid in enumerate(nids):
            nodes[nid]["x"] = start_x + i * (NODE_W + H_GAP)
            nodes[nid]["y"] = y

    # ── Store metadata for JS ─────────────────────────────────────────────────
    nodes[self_id]["_unionYou"]        = {"x": union_you_x, "y": y0}
    nodes[self_id]["_unionSib"]        = {"x": union_sib_x, "y": y0}
    nodes[self_id]["_siblingIds"]      = sibling_ids_all
    nodes[self_id]["_youChildren"]     = you_children
    nodes[self_id]["_sibChildren"]     = sib_children
    nodes[self_id]["_siblingCouples"]  = ([[sister_id, bil_id]] if (sister_id and bil_id) else
                                          ([[sister_id, None]] if sister_id else []))
    nodes[self_id]["_ancestorCouples"] = [
        {"nid_a": ac["nid_a"], "nid_b": ac["nid_b"], "gen": ac["gen"],
         "child_nid": ac["child_nid"], "isSibPil": ac.get("isSibPil", False)}  
        for ac in ancestor_couples
    ]
return nodes, self_id


def _family_tree_tab(uid):
    nodes, root_id = _build_tree_data(uid)
    if not nodes:
        st.markdown('<div class="msg-info">No family data. Add family links first.</div>', unsafe_allow_html=True)
        return

    col_t2, col_t3 = st.columns([1, 1])
    with col_t2:
        zoom = st.slider("Zoom %", 40, 180, st.session_state.tree_zoom, step=10,
            key="tree_zoom_sl")
        st.session_state.tree_zoom = zoom
    with col_t3:
        show_photos = st.toggle("Show Photos", value=True, key="tree_photos")

    nodes_json = json.dumps(nodes)
    zoom_val   = zoom / 100.0
    spjs = "true" if show_photos else "false"

    tree_html = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<style>
@import url('https://fonts.googleapis.com/css2?family=Cormorant+Garamond:wght@600;700&family=DM+Sans:wght@400;500&display=swap');
*{{box-sizing:border-box;margin:0;padding:0;}}
html,body{{width:100%;height:100%;background:#FAF7F2;overflow:hidden;font-family:'DM Sans',sans-serif;}}
#viewport{{width:100%;height:100%;overflow:hidden;position:relative;cursor:grab;user-select:none;}}
#viewport.dragging{{cursor:grabbing;}}
#world{{position:absolute;top:0;left:0;transform-origin:0 0;}}
svg#edges{{position:absolute;top:0;left:0;overflow:visible;pointer-events:none;}}
.node{{position:absolute;width:175px;background:white;border-radius:10px;
  box-shadow:0 2px 12px rgba(0,0,0,.09);border:1.5px solid #e8e0d4;
  padding:10px 10px 10px 14px;cursor:pointer;transition:box-shadow .15s,border-color .15s;}}
.node:hover{{box-shadow:0 4px 20px rgba(92,61,46,.18);border-color:#C9A84C;}}
.node.is-self{{background:#FFFDF4;border-color:#C9A84C;border-width:2px;box-shadow:0 0 0 4px rgba(201,168,76,.12),0 2px 12px rgba(0,0,0,.09);}}
.node-stripe{{position:absolute;left:0;top:0;bottom:0;width:5px;border-radius:8px 0 0 8px;}}
.node-inner{{display:flex;align-items:center;gap:8px;}}
.avatar{{width:36px;height:36px;border-radius:50%;flex-shrink:0;display:flex;align-items:center;justify-content:center;font-family:'Cormorant Garamond',serif;font-weight:700;font-size:13px;border:1.8px solid;overflow:hidden;}}
.avatar img{{width:100%;height:100%;object-fit:cover;}}
.node-text{{flex:1;min-width:0;}}
.node-name{{font-family:'Cormorant Garamond',serif;font-size:12.5px;font-weight:700;color:#3D2314;
  white-space:normal;overflow:hidden;text-overflow:ellipsis;line-height:1.2;word-break:break-word;}}
.node-sub{{font-size:9.5px;color:#9CA3AF;margin-top:2px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}}
.node-rel{{font-size:8px;font-weight:600;letter-spacing:.5px;text-transform:uppercase;margin-top:3px;white-space:normal;word-break:break-word;}}
.node-badge{{position:absolute;top:5px;right:6px;font-size:10px;}}
#tooltip{{position:fixed;display:none;background:white;border:1.5px solid #C9A84C;border-radius:12px;
  padding:11px 14px;box-shadow:0 6px 26px rgba(92,61,46,.18);min-width:175px;max-width:230px;
  z-index:999;pointer-events:none;font-size:12.5px;color:#1C1C1C;}}
.tt-rel{{font-size:9.5px;color:#C9A84C;font-weight:700;letter-spacing:1px;text-transform:uppercase;margin-bottom:3px;}}
.tt-name{{font-family:'Cormorant Garamond',serif;font-size:15px;font-weight:700;color:#5C3D2E;line-height:1.2;margin-bottom:4px;}}
.tt-row{{font-size:10.5px;color:#6B7280;line-height:1.7;}}
.tt-badge{{display:inline-block;font-size:9.5px;padding:2px 7px;border-radius:20px;margin-top:4px;border:1px solid;}}
.tt-v{{background:#EAF4EE;color:#3B5249;border-color:#3B5249;}}
.tt-s{{background:#FDF3DC;color:#A0522D;border-color:#C9A84C;}}
#gen-labels{{position:absolute;left:0;top:0;pointer-events:none;}}
.gen-label{{position:absolute;font-size:9px;font-weight:600;letter-spacing:1.2px;text-transform:uppercase;
  color:#C8B99A;background:rgba(250,247,242,.85);padding:2px 7px;border-radius:5px;white-space:nowrap;}}
#controls{{position:absolute;top:10px;right:10px;display:flex;flex-direction:column;gap:4px;z-index:10;}}
.ctrl-btn{{background:white;border:1.5px solid #F0EBE1;border-radius:8px;padding:5px 11px;
  font-size:11px;cursor:pointer;color:#5C3D2E;box-shadow:0 1px 7px rgba(0,0,0,.07);
  transition:all .13s;font-family:'DM Sans',sans-serif;}}
.ctrl-btn:hover{{border-color:#C9A84C;background:#FFFBF2;}}
#legend{{position:absolute;bottom:10px;left:10px;background:rgba(255,252,247,.96);border:1px solid #F0EBE1;
  border-radius:10px;padding:7px 11px;font-size:10px;color:#8C9E8E;z-index:10;}}
.lg-row{{display:flex;align-items:center;gap:5px;margin-bottom:3px;}}
.lg-row:last-child{{margin-bottom:0;}}
.lg-dot{{width:9px;height:9px;border-radius:3px;flex-shrink:0;}}
#info-bar{{position:absolute;top:10px;left:10px;background:rgba(255,252,247,.96);border:1px solid #F0EBE1;
  border-radius:9px;padding:6px 11px;font-size:10px;color:#8C9E8E;z-index:10;}}
</style></head><body>
<div id="viewport">
  <div id="world">
    <svg id="edges"></svg>
    <div id="nodes-layer"></div>
    <div id="gen-labels"></div>
  </div>
</div>
<div id="tooltip"></div>
<div id="controls">
  <button class="ctrl-btn" onclick="resetView()">⟳ Reset</button>
  <button class="ctrl-btn" onclick="zoomIn()">＋ Zoom</button>
  <button class="ctrl-btn" onclick="zoomOut()">－ Zoom</button>
</div>
<div id="legend"></div>
<div id="info-bar"></div>
<script>
const NODES = {nodes_json};
const INIT_SCALE = {zoom_val};
const SHOW_PHOTO = {spjs};
const GEN_COLOR = {{'-3':'#7C3AED','-2':'#4F46E5','-1':'#2563EB','0':'#C9A84C','1':'#059669','2':'#D97706','3':'#DC2626'}};
const GEN_LABEL = {{'-3':'Great-grandparents','-2':'Grandparents','-1':'Parents','0':'Your Generation','1':'Children','2':'Grandchildren','3':'Great-grandchildren'}};
function gc(g){{return GEN_COLOR[String(g)]||'#9CA3AF';}}

const NW=175,NH=90,HGAP=40,VGAP=110;
const viewport=document.getElementById('viewport');
const world=document.getElementById('world');
const svg=document.getElementById('edges');
const nodesLayer=document.getElementById('nodes-layer');
const genLabelsEl=document.getElementById('gen-labels');
const tip=document.getElementById('tooltip');

let scale=INIT_SCALE,tx=0,ty=0,dragging=false,lastX=0,lastY=0;

// ── Build node DOM elements ──────────────────────────────────────────────────
const nodeEls={{}};
for(const [id,n] of Object.entries(NODES)){{
  const col=n.isSelf?'#C9A84C':gc(n.gen);
  const div=document.createElement('div');
  div.className='node'+(n.isSelf?' is-self':'');
  div.style.left=(n.x-NW/2)+'px';
  div.style.top=(n.y-NH/2)+'px';
  div.style.width=NW+'px';
  div.style.minHeight=NH+'px';
  const initials=(n.label||'').split(' ').slice(0,2).map(s=>(s[0]||'').toUpperCase()).join('');
  const avatarContent=SHOW_PHOTO&&n.photo
    ?`<img src="${{n.photo}}" alt="" onerror="this.style.display='none';this.nextSibling.style.display='flex'"><span style="display:none;width:100%;height:100%;align-items:center;justify-content:center;font-family:'Cormorant Garamond',serif;font-size:13px;font-weight:700;color:${{col}}">${{initials}}</span>`
    :`<span style="width:100%;height:100%;display:flex;align-items:center;justify-content:center;font-family:'Cormorant Garamond',serif;font-size:13px;font-weight:700;color:${{col}}">${{initials}}</span>`;
  const subParts=[];
  if(n.age) subParts.push('Age '+n.age);
  if(n.city) subParts.push(n.city);
  div.innerHTML=`
    <div class="node-stripe" style="background:${{col}}"></div>
    <div class="node-inner">
      <div class="avatar" style="background:${{col}}18;border-color:${{col}}">${{avatarContent}}</div>
      <div class="node-text">
        <div class="node-name">${{n.label||''}}</div>
        ${{subParts.length?`<div class="node-sub">${{subParts.join(' · ')}}</div>`:''}}
        <div class="node-rel" style="color:${{col}}">${{n.relation||''}}</div>
      </div>
    </div>
    <div class="node-badge">${{n.isSelf?'★':n.verified?'<span style="color:#059669">✓</span>':''}}</div>`;
  div.addEventListener('mouseenter',e=>showTip(n,e));
  div.addEventListener('mousemove',e=>moveTip(e));
  div.addEventListener('mouseleave',()=>hideTip());
  nodesLayer.appendChild(div);
  nodeEls[id]=div;
}}

// ── Draw SVG edges ────────────────────────────────────────────────────────────
//
// LAYOUT CONTRACT (set in Python):
//   • Each gen-0 couple has spouseId set on both nodes.
//   • Each gen+1 node has parentUnionKey = "union_you" | "union_sib".
//   • selfNode._unionYou / ._unionSib carry the pre-computed midpoint x,y.
//   • selfNode._youChildren / ._sibChildren list the nids in each group.
//   • selfNode._siblingIds lists all sibling nids (for parent bar).
//
// EDGE RULES:
//   1. Marriage bar: dashed horizontal between each gen-0 couple, at node centre y.
//   2. Child T-bar stem starts from the MARRIAGE BAR (node centre y), not node bottom.
//      Each family unit gets its own separate T-bar.
//   3. Parents (gen -1): shared bar spanning bloodline children, each parent connects in.
//   4. Grandparents (gen -2): each connects to its NEAREST gen-1 node independently
//      (no shared bottleneck — two grandparents can connect to two different parents).
//   5. Great-grandparents (gen -3): each connects to its nearest gen-2 node independently.
//   6. Relation labels sit to the RIGHT of the drop line, never on it.
//
function drawEdges(){{
  svg.innerHTML='';
  const selfNode=Object.values(NODES).find(n=>n.isSelf);
  if(!selfNode) return;

  function svgEl(tag){{return document.createElementNS('http://www.w3.org/2000/svg',tag);}}

  const unionYou  = selfNode._unionYou || {{x:selfNode.x, y:selfNode.y}};
  const unionSib  = selfNode._unionSib || {{x:selfNode.x, y:selfNode.y}};
  const youChildIds = new Set(selfNode._youChildren||[]);
  const sibChildIds = new Set(selfNode._sibChildren||[]);

  // ── Helper: simple elbow M→V→H→V ─────────────────────────────────────────
  function elbow(x1,y1,x2,y2,col){{
    const my=(y1+y2)/2;
    const p=svgEl('path');
    p.setAttribute('d',`M${{x1}},${{y1}} V${{my}} H${{x2}} V${{y2}}`);
    p.setAttribute('stroke',col); p.setAttribute('stroke-width','1.8');
    p.setAttribute('fill','none'); p.setAttribute('stroke-linejoin','round');
    svg.appendChild(p);
  }}

  // ── Helper: relation label pill — offset to the right of drop line ────────
  function relLabel(dropX, topY, txt, col){{
    if(!txt) return;
    const rw=Math.max(txt.length*5.2+10,34), rh=14;
    // Place pill to the RIGHT of the drop line, vertically centred in upper third
    const lx = dropX + rw/2 + 5;
    const ly = topY + 20;   // 20px below the top of the drop, well above node
    const bg=svgEl('rect');
    bg.setAttribute('x',lx-rw/2); bg.setAttribute('y',ly-rh/2);
    bg.setAttribute('width',rw);  bg.setAttribute('height',rh);
    bg.setAttribute('rx','5');
    bg.setAttribute('fill','rgba(255,252,247,0.97)');
    bg.setAttribute('stroke',col+'55'); bg.setAttribute('stroke-width','0.8');
    svg.appendChild(bg);
    const t=svgEl('text');
    t.setAttribute('x',lx); t.setAttribute('y',ly);
    t.setAttribute('text-anchor','middle'); t.setAttribute('dominant-baseline','middle');
    t.setAttribute('font-size','7.5'); t.setAttribute('fill',col);
    t.setAttribute('font-family','DM Sans,sans-serif');
    t.textContent=txt;
    svg.appendChild(t);
  }}

  // ── 1. Marriage bars — ALL generations with a spouseId pair ─────────────
  // Draw a dashed bar + heart between every couple, regardless of generation.
  const marriageBarMidX = {{}};  // nodeId → midpoint x of their marriage bar
  const mbDone=new Set();
  for(const [id,n] of Object.entries(NODES)){{
    if(!n.spouseId||mbDone.has(id)) continue;
    const sp=NODES[n.spouseId];
    if(!sp) continue;
    mbDone.add(id); mbDone.add(n.spouseId);
    const col = n.gen===0 ? '#C9A84C' : gc(n.gen);
    const barY = n.y;
    const xa=Math.min(n.x,sp.x)+NW/2, xb=Math.max(n.x,sp.x)-NW/2;
    const midX=(n.x+sp.x)/2;
    marriageBarMidX[id]=midX; marriageBarMidX[n.spouseId]=midX;
    if(xb>xa){{
      const ln=svgEl('line');
      ln.setAttribute('x1',xa); ln.setAttribute('y1',barY);
      ln.setAttribute('x2',xb); ln.setAttribute('y2',barY);
      ln.setAttribute('stroke',col+'cc'); ln.setAttribute('stroke-width','2.2');
      ln.setAttribute('stroke-dasharray','5 3');
      svg.appendChild(ln);
      const sym=svgEl('text');
      sym.setAttribute('x',(xa+xb)/2); sym.setAttribute('y',barY-11);
      sym.setAttribute('text-anchor','middle'); sym.setAttribute('dominant-baseline','middle');
      sym.setAttribute('font-size','13'); sym.setAttribute('fill',col);
      sym.textContent='♥';
      svg.appendChild(sym);
    }}
  }}

  // ── 2. Child T-bars — stem from marriage bar midpoint ─────────────────────
  function drawChildTBar(unionX, unionNodeY, childNids, col){{
    if(!childNids.length) return;
    const childNodes=childNids.map(id=>NODES[id]).filter(Boolean);
    if(!childNodes.length) return;

    const stemTopY = unionNodeY + NH/2;                // bottom edge of the node row
    const barY     = stemTopY + VGAP * 0.42;           // child horizontal bar

    const cxs  = childNodes.map(c=>c.x);
    const barX1= Math.min(...cxs), barX2=Math.max(...cxs);

    const vStem=svgEl('line');
    vStem.setAttribute('x1',unionX); vStem.setAttribute('y1',stemTopY);
    vStem.setAttribute('x2',unionX); vStem.setAttribute('y2',barY);
    vStem.setAttribute('stroke',col); vStem.setAttribute('stroke-width','2');
    svg.appendChild(vStem);

    const hBar=svgEl('line');
    hBar.setAttribute('x1',barX1); hBar.setAttribute('y1',barY);
    hBar.setAttribute('x2',barX2); hBar.setAttribute('y2',barY);
    hBar.setAttribute('stroke',col); hBar.setAttribute('stroke-width','2');
    svg.appendChild(hBar);

    for(const c of childNodes){{
      const dropLine=svgEl('line');
      dropLine.setAttribute('x1',c.x); dropLine.setAttribute('y1',barY);
      dropLine.setAttribute('x2',c.x); dropLine.setAttribute('y2',c.y-NH/2);
      dropLine.setAttribute('stroke',col); dropLine.setAttribute('stroke-width','1.8');
      svg.appendChild(dropLine);
      relLabel(c.x, barY, (c.relation||'').trim(), col);
    }}
  }}

  const childCol = gc(1);
  if(youChildIds.size)
    drawChildTBar(unionYou.x, unionYou.y, [...youChildIds], childCol);
  if(sibChildIds.size)
    drawChildTBar(unionSib.x, unionSib.y, [...sibChildIds], childCol);

  // ── 3. Parents (gen -1) → stem from couple union down to children bar ──────
  //
  // If Father+Mother are a detected couple: stem drops from their midpoint.
  // Otherwise fall back to the old shared-bar approach.
  //
  const ancestorCouples = selfNode._ancestorCouples || [];
  const sibIds     = (selfNode._siblingIds||[]);
  // Exclude siblings who have a spouse (they connect via their own couple edge to parents)
  const sibsWithSpouse = new Set(
    Object.values(NODES)
      .filter(n=>n.gen===0 && !n.isSelf && n.spouseId)
      .map(n=>n.id)
  );
  const bloodIds   = [selfNode.id, ...sibIds.filter(id=>!sibsWithSpouse.has(id))];
  const bloodNodes = bloodIds.map(id=>NODES[id]).filter(Boolean);
  const SIB_PIL = new Set(["Sister's Father-in-law","Sister's Mother-in-law",
                            "Brother's Father-in-law","Brother's Mother-in-law"]);
  const parentNodes= Object.values(NODES).filter(n=>n.gen===-1 && !SIB_PIL.has(n.relation));
  const parentCol  = gc(-1);

  // Partition parent nodes into coupled vs single
  const parentCoupleHandled = new Set();
  // Exclude SIB_PIL couples (MallaReddy+rajamma) — they connect to BIL, not to Kavitha
  const parentGenCouples = ancestorCouples.filter(ac=>ac.gen===-1 && !ac.isSibPil);

  for(const ac of parentGenCouples){{
    const pa=NODES[ac.nid_a], pb=NODES[ac.nid_b];
    if(!pa||!pb) continue;
    parentCoupleHandled.add(ac.nid_a); parentCoupleHandled.add(ac.nid_b);
    const unionX = (pa.x + pb.x) / 2;
    const unionY = pa.y;  // both at same Y

    if(bloodNodes.length){{
      // Stem from couple bottom down to children
      const bxs  = bloodNodes.map(n=>n.x);
      const barX1= Math.min(...bxs), barX2=Math.max(...bxs);
      const stemY = unionY + NH/2;
      const barY  = (stemY + bloodNodes[0].y - NH/2) / 2;

      // Vertical stem from union midpoint
      const vl=svgEl('line');
      vl.setAttribute('x1',unionX); vl.setAttribute('y1',stemY);
      vl.setAttribute('x2',unionX); vl.setAttribute('y2',barY);
      vl.setAttribute('stroke',parentCol+'99'); vl.setAttribute('stroke-width','1.8');
      svg.appendChild(vl);

      // Horizontal bar spanning children
      const hBar=svgEl('line');
      hBar.setAttribute('x1',barX1); hBar.setAttribute('y1',barY);
      hBar.setAttribute('x2',barX2); hBar.setAttribute('y2',barY);
      hBar.setAttribute('stroke',parentCol+'99'); hBar.setAttribute('stroke-width','1.8');
      svg.appendChild(hBar);

      // Drop to each child
      for(const c of bloodNodes){{
        const dl=svgEl('line');
        dl.setAttribute('x1',c.x); dl.setAttribute('y1',barY);
        dl.setAttribute('x2',c.x); dl.setAttribute('y2',c.y-NH/2);
        dl.setAttribute('stroke',parentCol+'99'); dl.setAttribute('stroke-width','1.8');
        svg.appendChild(dl);
      }}
    }}
  }}

  // Fallback: any unpaired parent nodes use the old shared-bar approach
  const unpairedParents = parentNodes.filter(n=>!parentCoupleHandled.has(n.id));
  if(unpairedParents.length && bloodNodes.length){{
    const parBottomY = unpairedParents[0].y + NH/2;
    const bloodTopY  = bloodNodes[0].y  - NH/2;
    const barY = (parBottomY + bloodTopY) / 2;

    const bxs  = bloodNodes.map(n=>n.x);
    const barX1= Math.min(...bxs), barX2=Math.max(...bxs);

    const hBar=svgEl('line');
    hBar.setAttribute('x1',barX1); hBar.setAttribute('y1',barY);
    hBar.setAttribute('x2',barX2); hBar.setAttribute('y2',barY);
    hBar.setAttribute('stroke',parentCol+'99'); hBar.setAttribute('stroke-width','1.8');
    svg.appendChild(hBar);

    for(const c of bloodNodes){{
      const dl=svgEl('line');
      dl.setAttribute('x1',c.x); dl.setAttribute('y1',barY);
      dl.setAttribute('x2',c.x); dl.setAttribute('y2',c.y-NH/2);
      dl.setAttribute('stroke',parentCol+'99'); dl.setAttribute('stroke-width','1.8');
      svg.appendChild(dl);
    }}

    for(const par of unpairedParents){{
      const px=par.x, py=par.y+NH/2;
      const bx=Math.max(barX1, Math.min(barX2, px));
      if(Math.abs(px-bx)<1){{
        const vl=svgEl('line');
        vl.setAttribute('x1',px); vl.setAttribute('y1',py);
        vl.setAttribute('x2',px); vl.setAttribute('y2',barY);
        vl.setAttribute('stroke',parentCol+'99'); vl.setAttribute('stroke-width','1.8');
        svg.appendChild(vl);
      }} else {{
        elbow(px,py,bx,barY,parentCol+'99');
      }}
    }}
  }}

  // ── 3b. Parents also connect down to each married sibling (blood child) ──────
  // e.g. Father+Mother → Sister (even though Sister has a spouse/BIL)
  const sibCoupleTargets = sibIds.filter(id=>sibsWithSpouse.has(id))
    .map(id=>NODES[id]).filter(Boolean);
  if(sibCoupleTargets.length && parentGenCouples.length){{
    const ac0 = parentGenCouples[0];
    const pa=NODES[ac0.nid_a], pb=NODES[ac0.nid_b];
    if(pa && pb){{
      const unionX=(pa.x+pb.x)/2, unionY=pa.y;
      for(const sib of sibCoupleTargets){{
        elbow(unionX, unionY+NH/2, sib.x, sib.y-NH/2, parentCol+'99');
      }}
    }}
  }} else if(sibCoupleTargets.length && bloodNodes.length===1){{
    // No detected couple but we have a single parent — elbow to each married sib
    const singlePars = parentNodes.filter(n=>!parentCoupleHandled.has(n.id));
    for(const par of singlePars){{
      for(const sib of sibCoupleTargets){{
        elbow(par.x, par.y+NH/2, sib.x, sib.y-NH/2, parentCol+'99');
      }}
    }}
  }}

  // ── 4 & 5. Ancestors gen ≤ -2 ─────────────────────────────────────────────
  //
  // Coupled pairs: stem drops from couple midpoint to their SPECIFIC blood child
  //   (stored as ac.child_nid). Falls back to nearest-by-distance only if
  //   child_nid is null or not found.
  // Unpaired singles: each connects independently to their nearest gen+1 node.
  //
  const ancestorHandled = new Set();

  // Process couples first
  for(const ac of ancestorCouples){{
    if(ac.gen >= -1) continue;   // gen -2 and below only here
    const pa=NODES[ac.nid_a], pb=NODES[ac.nid_b];
    if(!pa||!pb) continue;
    ancestorHandled.add(ac.nid_a); ancestorHandled.add(ac.nid_b);

    const unionX = (pa.x + pb.x) / 2;
    const unionY = pa.y;
    const adjGen = ac.gen + 1;
    const adjNodes = Object.values(NODES).filter(p=>p.gen===adjGen);
    if(!adjNodes.length) continue;

    // Use the specific blood child if known; otherwise fall back to nearest
    const target = (ac.child_nid && NODES[ac.child_nid])
      ? NODES[ac.child_nid]
      : adjNodes.reduce((a,b)=>
          Math.abs(a.x-unionX) <= Math.abs(b.x-unionX) ? a : b
        );
    elbow(unionX, unionY+NH/2, target.x, target.y-NH/2, gc(ac.gen)+'bb');
  }}

  // Process unpaired ancestor singles
  // Use relation-based targeting so e.g. a lone Maternal Grandfather
  // always connects to Mother (not nearest node by X which could be Father).
  const SINGLE_ANCESTOR_TARGET = {{
    'Maternal Grandfather': new Set(['Mother','Stepmother']),
    'Maternal Grandmother': new Set(['Mother','Stepmother']),
    'Paternal Grandfather': new Set(['Father','Stepfather']),
    'Paternal Grandmother': new Set(['Father','Stepfather']),
    'Great-grandfather':    new Set(['Paternal Grandfather','Maternal Grandfather',
                                     'Paternal Grandmother','Maternal Grandmother']),
    'Great-grandmother':    new Set(['Paternal Grandfather','Maternal Grandfather',
                                     'Paternal Grandmother','Maternal Grandmother']),
  }};
  for(const [id,n] of Object.entries(NODES)){{
    if(n.gen>=-1) continue;
    if(ancestorHandled.has(id)) continue;
    const adjGen = n.gen + 1;
    const adjNodes = Object.values(NODES).filter(p=>p.gen===adjGen);
    if(!adjNodes.length) continue;
    // Try relation-based target first, fall back to nearest-X
    const relTargets = SINGLE_ANCESTOR_TARGET[n.relation];
    let target = null;
    if(relTargets){{
      target = adjNodes.find(p=>relTargets.has(p.relation)) || null;
    }}
    if(!target){{
      target = adjNodes.reduce((a,b)=>
        Math.abs(a.x-n.x) <= Math.abs(b.x-n.x) ? a : b
      );
    }}
    elbow(n.x, n.y+NH/2, target.x, target.y-NH/2, gc(n.gen)+'bb');
  }}

  // ── 5b. Sister's/Brother's parents-in-law → connect down to BIL/Sister-in-law ──
  // If they are a couple (spouseId set), draw from their midpoint.
  // Otherwise draw individual elbows.
  const SIB_PIL_TARGET = {{
    "Sister's Father-in-law":  new Set(["Brother-in-law","Wife's Sister's Husband"]),
    "Sister's Mother-in-law":  new Set(["Brother-in-law","Wife's Sister's Husband"]),
    "Brother's Father-in-law": new Set(["Husband's Sister","Brother's Wife"]),
    "Brother's Mother-in-law": new Set(["Husband's Sister","Brother's Wife"]),
  }};
  // Draw SIB_PIL edges using ancestorCouples entries tagged isSibPil=true
  const sibPilCouples = ancestorCouples.filter(ac=>ac.isSibPil);
  const sibPilHandled = new Set();
  for(const ac of sibPilCouples){{
    const pa=NODES[ac.nid_a], pb=NODES[ac.nid_b];
    const target = ac.child_nid ? NODES[ac.child_nid] : null;
    if(!target) continue;
    const col = gc(-1)+'bb';
    if(pa && pb){{
      // Couple → stem from midpoint down to BIL
      sibPilHandled.add(ac.nid_a); sibPilHandled.add(ac.nid_b);
      const midX = (pa.x + pb.x) / 2;
      const stemY = pa.y + NH/2;
      const barY  = (stemY + target.y - NH/2) / 2;
      const vs=svgEl('line');
      vs.setAttribute('x1',midX); vs.setAttribute('y1',stemY);
      vs.setAttribute('x2',midX); vs.setAttribute('y2',barY);
      vs.setAttribute('stroke',col); vs.setAttribute('stroke-width','1.8');
      svg.appendChild(vs);
      elbow(midX, barY, target.x, target.y-NH/2, col);
    }}
  }}
  // Any single (unpaired) SIB_PIL nodes
  for(const [id,n] of Object.entries(NODES)){{
    if(!SIB_PIL.has(n.relation)) continue;
    if(sibPilHandled.has(id)) continue;
    const col = gc(-1)+'bb';
    const targetRels = SIB_PIL_TARGET[n.relation];
    const gen0Nodes = Object.values(NODES).filter(p=>p.gen===0);
    const target = gen0Nodes.find(p=>targetRels && targetRels.has(p.relation)) || null;
    if(!target) continue;
    sibPilHandled.add(id);
    elbow(n.x, n.y+NH/2, target.x, target.y-NH/2, col);
  }}

  // ── 6. Descendants gen ≥ 2 ────────────────────────────────────────────────
  for(const [id,n] of Object.entries(NODES)){{
    if(n.gen<2) continue;
    const adj=Object.values(NODES).filter(p=>p.gen===n.gen-1);
    if(!adj.length) continue;
    const par=adj.reduce((a,b)=>Math.abs(a.x-n.x)<Math.abs(b.x-n.x)?a:b);
    elbow(par.x, par.y+NH/2, n.x, n.y-NH/2, gc(n.gen)+'99');
    relLabel(n.x, n.y-NH/2-22, (n.relation||'').trim(), gc(n.gen));
  }}
}}

// ── Generation row labels — fixed to viewport left, not world coords ──────────
function drawGenLabels(){{
  // Clean up any previously appended label divs
  if(window._genLabelData) window._genLabelData.forEach(item=>item.div.remove());
  window._genLabelData=[];
  const gens=[...new Set(Object.values(NODES).map(n=>n.gen))].sort((a,b)=>a-b);
  gens.forEach(g=>{{
    const rowNodes=Object.values(NODES).filter(n=>n.gen===g);
    const worldY=rowNodes[0].y; // center Y of this gen row in world coords
    const div=document.createElement('div');
    div.className='gen-label';
    div.style.left='8px';
    div.style.position='absolute';  // inside #viewport, not body
    div.style.zIndex='10';
    div.style.pointerEvents='none';
    div.textContent=GEN_LABEL[String(g)]||('Gen '+g);
    div.style.color=gc(g);
    viewport.appendChild(div); // attach to viewport so coords are viewport-relative
    window._genLabelData.push({{div, worldY}});
  }});
  updateGenLabelPositions();
}}

function updateGenLabelPositions(){{
  if(!window._genLabelData) return;
  const vph=viewport.clientHeight||660;
  window._genLabelData.forEach(item=>{{
    const screenY = item.worldY * scale + ty;
    item.div.style.top = screenY + 'px';
    item.div.style.display=(screenY>10&&screenY<vph-20)?'block':'none';
  }});
}}

// ── Legend & info bar ─────────────────────────────────────────────────────────
function buildLegend(){{
  const present=[...new Set(Object.values(NODES).map(n=>String(n.gen)))].sort((a,b)=>+a-+b);
  document.getElementById('legend').innerHTML=present.map(g=>
    `<div class="lg-row"><div class="lg-dot" style="background:${{gc(+g)}}"></div>${{GEN_LABEL[g]||'Gen '+g}}</div>`
  ).join('');
}}
function buildInfo(){{
  const tot=Object.keys(NODES).length;
  const gens=new Set(Object.values(NODES).map(n=>n.gen)).size;
  document.getElementById('info-bar').textContent=`🌳 ${{tot}} member${{tot!==1?'s':''}} · ${{gens}} generation${{gens!==1?'s':''}} · Drag to pan · Scroll to zoom`;
}}

// ── Tooltip ──────────────────────────────────────────────────────────────────
function showTip(n,e){{
  let html='';
  if(n.relation) html+=`<div class="tt-rel">${{n.relation}}</div>`;
  html+=`<div class="tt-name">${{n.label}}</div>`;
  if(n.dynasty) html+=`<div class="tt-row">🏰 ${{n.dynasty}}</div>`;
  if(n.age)     html+=`<div class="tt-row">🎂 Age ${{n.age}}</div>`;
  if(n.occupation) html+=`<div class="tt-row">💼 ${{n.occupation}}</div>`;
  if(n.city)    html+=`<div class="tt-row">🏙️ ${{n.city}}</div>`;
  if(n.verified&&!n.isSelf) html+=`<span class="tt-badge tt-v">✓ Verified</span>`;
  if(n.isSelf)  html+=`<span class="tt-badge tt-s">★ You</span>`;
  tip.innerHTML=html;tip.style.display='block';
  moveTip(e);
}}
function moveTip(e){{
  tip.style.left=(e.clientX+14)+'px';tip.style.top=(e.clientY-8)+'px';
}}
function hideTip(){{tip.style.display='none';}}

// ── Pan & zoom ────────────────────────────────────────────────────────────────
function applyTransform(){{
  world.style.transform=`translate(${{tx}}px,${{ty}}px) scale(${{scale}})`;
  updateGenLabelPositions();
}}
viewport.addEventListener('mousedown',e=>{{dragging=true;lastX=e.clientX;lastY=e.clientY;viewport.classList.add('dragging');}});
window.addEventListener('mouseup',()=>{{dragging=false;viewport.classList.remove('dragging');}});
window.addEventListener('mousemove',e=>{{
  if(!dragging) return;
  tx+=e.clientX-lastX;ty+=e.clientY-lastY;
  lastX=e.clientX;lastY=e.clientY;applyTransform();
}});
viewport.addEventListener('wheel',e=>{{
  e.preventDefault();
  const factor=e.deltaY>0?.88:1.14;
  const rect=viewport.getBoundingClientRect();
  const ox=e.clientX-rect.left,oy=e.clientY-rect.top;
  tx=ox+(tx-ox)*factor;ty=oy+(ty-oy)*factor;
  scale=Math.max(.15,Math.min(4,scale*factor));
  applyTransform();
}},{{passive:false}});

// Touch support
let lastDist=0;
viewport.addEventListener('touchstart',e=>{{
  if(e.touches.length===1){{dragging=true;lastX=e.touches[0].clientX;lastY=e.touches[0].clientY;}}
  else if(e.touches.length===2) lastDist=Math.hypot(e.touches[0].clientX-e.touches[1].clientX,e.touches[0].clientY-e.touches[1].clientY);
}},{{passive:true}});
viewport.addEventListener('touchmove',e=>{{
  e.preventDefault();
  if(e.touches.length===1&&dragging){{
    tx+=e.touches[0].clientX-lastX;ty+=e.touches[0].clientY-lastY;
    lastX=e.touches[0].clientX;lastY=e.touches[0].clientY;applyTransform();
  }}else if(e.touches.length===2){{
    const d=Math.hypot(e.touches[0].clientX-e.touches[1].clientX,e.touches[0].clientY-e.touches[1].clientY);
    scale=Math.max(.15,Math.min(4,scale*(d/lastDist)));lastDist=d;applyTransform();
  }}
}},{{passive:false}});
viewport.addEventListener('touchend',()=>{{dragging=false;}},{{passive:true}});

function zoomIn(){{scale=Math.min(4,scale*1.2);applyTransform();}}
function zoomOut(){{scale=Math.max(.15,scale/1.2);applyTransform();}}
function resetView(){{
  const vw=viewport.clientWidth||900, vh=viewport.clientHeight||660;
  // Compute bounding box of all nodes in world coords
  const xs=Object.values(NODES).map(n=>n.x);
  const ys=Object.values(NODES).map(n=>n.y);
  const minX=Math.min(...xs)-NW/2, maxX=Math.max(...xs)+NW/2;
  const minY=Math.min(...ys)-NH/2, maxY=Math.max(...ys)+NH/2;
  const contentW=maxX-minX, contentH=maxY-minY;
  // Fit scale so content fills ~80% of viewport
  const fitScale=Math.min(0.9*vw/contentW, 0.82*vh/contentH, INIT_SCALE);
  scale=fitScale;
  // Centre the content
  tx = vw/2 - (minX + contentW/2)*scale;
  ty = vh/2 - (minY + contentH/2)*scale;
  applyTransform();
}}

// ── Boot ──────────────────────────────────────────────────────────────────────
drawEdges();
buildLegend();
buildInfo();

// resetView needs real viewport dimensions. Inside a Streamlit tab the iframe
// is hidden (display:none or zero-size) until the user clicks the tab, so
// requestAnimationFrame fires when clientWidth/clientHeight are still 0 and
// the tree ends up invisible. Use ResizeObserver + staggered setTimeouts to
// re-run resetView the first time the viewport actually has a non-zero size.
let _booted = false;
function _boot() {{
  if (_booted) return;
  const vw = viewport.clientWidth, vh = viewport.clientHeight;
  if (vw > 0 && vh > 0) {{
    _booted = true;
    resetView();
    drawGenLabels();
  }}
}}
// Try immediately in case the tab is already visible
requestAnimationFrame(_boot);
// Staggered fallbacks for browsers that don't fire ResizeObserver reliably
// when a hidden Streamlit tab becomes visible
setTimeout(_boot, 500);
setTimeout(_boot, 1200);
setTimeout(_boot, 2500);
// Also watch for when the element is resized into view (tab click)
if (typeof ResizeObserver !== 'undefined') {{
  const ro = new ResizeObserver(() => {{
    _boot();
    if (_booted) ro.disconnect();
  }});
  ro.observe(viewport);
}}
</script></body></html>"""

    st.components.v1.html(tree_html, height=660, scrolling=False)
    st.markdown("""<div style="font-size:.76rem;color:var(--mist);text-align:center;margin-top:.3rem;">
    🖱️ <strong>Drag</strong> to pan &nbsp;·&nbsp; <strong>Scroll/Pinch</strong> to zoom &nbsp;·&nbsp;
    <strong>Hover</strong> nodes for details
    </div>""", unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════════════════════
# DYNASTY SEARCH
# ══════════════════════════════════════════════════════════════════════════════
def _dynasty_search_tab(uid):
    if st.session_state.viewed_profile:
        vp      = st.session_state.viewed_profile
        vp_dob  = ensure_dob(vp["dob"])
        vp_age  = calc_age(vp_dob)
        vp_init = "".join(p[0].upper() for p in vp["full_name"].split()[:2])
        # ── Build the entire modal as one self-contained HTML block ──────────
        _vp_avatar   = avatar_html(vp.get("profile_photo") or None, vp_init, 86)
        _vp_gen_badge = f'<span class="badge badge-gold">🏰 {_esc(vp["dynasty_name"])}</span> <span class="badge badge-green">{_infer_generation(vp_age)}</span>'
        _detail_rows = [
            ("Date of Birth", vp_dob.strftime("%d %B %Y") if vp.get("privacy_dob", True) else "Hidden"),
            ("Age",           f"{vp_age} years"),
            ("Gender",        vp.get("gender") or "—"),
            ("Birth City",    vp.get("birth_city") or "—"),
            ("Current City",  vp.get("current_city") or "—" if vp.get("privacy_city", True) else "Hidden"),
            ("Occupation",    vp.get("occupation") or "—" if vp.get("privacy_occ", True) else "Hidden"),
        ]
        _detail_html = "".join(
            f'<div style="flex:1 1 45%;min-width:140px;">'
            f'<div class="profile-detail-key">{k}</div>'
            f'<div style="font-size:.88rem;font-weight:500;margin-bottom:.65rem;">{_esc(str(v))}</div>'
            f'</div>'
            for k, v in _detail_rows
        )
        vp_links = get_links(vp["id"])
        _family_html = ""
        if vp_links:
            _badges = "".join(
                f'<span class="badge badge-green">{_esc(lk["relation"])}: {_esc(lk.get("linked_name") or lk["member_name"])}</span>'
                for lk in vp_links[:6]
            )
            _family_html = f'<hr class="fancy-divider"><div style="font-size:.76rem;text-transform:uppercase;letter-spacing:1.2px;color:var(--mist);margin-bottom:.4rem;">Known Family</div>{_badges}'

        st.markdown(f"""
        <div class="profile-modal">
            <div style="display:flex;align-items:center;gap:1.2rem;margin-bottom:.9rem;">
                {_vp_avatar}
                <div>
                    <div style="font-family:'Cormorant Garamond',serif;font-size:1.35rem;font-weight:700;color:var(--bark);">{_esc(vp["full_name"])}</div>
                    <div style="margin-top:.35rem;">{_vp_gen_badge}</div>
                </div>
            </div>
            <hr class="fancy-divider">
            <div style="display:flex;flex-wrap:wrap;gap:.3rem 1.5rem;">
                {_detail_html}
            </div>
            {_family_html}
        </div>
        <hr class="fancy-divider">
        """, unsafe_allow_html=True)
        b1, b2 = st.columns(2)
        with b1:
            if st.button("✕ Close", key="close_profile"):
                st.session_state.viewed_profile = None; st.rerun()
        with b2:
            if st.button("👤 Full Profile", key="open_full_profile", type="primary"):
                st.session_state.dp_target_uid = vp["id"]
                st.session_state.viewed_profile = None
                st.session_state.active_tab = 0
                st.rerun()

    st.markdown('<div class="search-hero"><div class="search-hero-title">🔍 Dynasty Search</div></div>', unsafe_allow_html=True)
    q = st.text_input("Dynasty name, member name, or city", value=st.session_state.ds_query,
        placeholder="Search your Dynasty", key="ds_q_input", label_visibility="collapsed")
    st.session_state.ds_query = q

    st.markdown('<div style="font-size:.73rem;text-transform:uppercase;letter-spacing:1.2px;color:var(--mist);margin-bottom:.5rem;">🎛️ Filters</div>', unsafe_allow_html=True)
    fc1, fc2, fc3, fc4, fc5 = st.columns([1.5, 1.5, 1.5, 1, 1])
    with fc1:
        gen_opts = ["All", "Gen Z (< 18)", "Millennial (18–34)", "Gen X (35–54)", "Boomer (55–74)", "Senior (75+)"]
        st.session_state.ds_gen = st.selectbox("Generation", gen_opts,
            index=gen_opts.index(st.session_state.ds_gen) if st.session_state.ds_gen in gen_opts else 0,
            key="ds_gen_sel", label_visibility="collapsed")
    with fc2:
        st.session_state.ds_city = st.text_input("City", value=st.session_state.ds_city,
            placeholder="Filter by city…", key="ds_city_inp", label_visibility="collapsed")
    with fc3:
        st.session_state.ds_occ = st.text_input("Occupation", value=st.session_state.ds_occ,
            placeholder="Filter by occupation…", key="ds_occ_inp", label_visibility="collapsed")
    with fc4:
        gnd = ["All", "Male", "Female", "Other"]
        st.session_state.ds_gender = st.selectbox("Gender", gnd,
            index=gnd.index(st.session_state.ds_gender) if st.session_state.ds_gender in gnd else 0,
            key="ds_gender_sel", label_visibility="collapsed")
    with fc5:
        if st.button("Clear Filters", key="ds_clear", use_container_width=True):
            st.session_state.ds_query = ""; st.session_state.ds_gen = "All"
            st.session_state.ds_city = ""; st.session_state.ds_occ = ""; st.session_state.ds_gender = "All"
            st.rerun()

    base_sql = "SELECT * FROM users WHERE id != %s"
    params = [uid]
    if q:
        base_sql += " AND (full_name ILIKE %s OR dynasty_name ILIKE %s OR current_city ILIKE %s OR birth_city ILIKE %s)"
        params += [f"%{q}%"] * 4
    if st.session_state.ds_city:
        base_sql += " AND (current_city ILIKE %s OR birth_city ILIKE %s)"
        params += [f"%{st.session_state.ds_city}%"] * 2
    if st.session_state.ds_occ:
        base_sql += " AND occupation ILIKE %s"
        params.append(f"%{st.session_state.ds_occ}%")
    if st.session_state.ds_gender != "All":
        base_sql += " AND gender = %s"
        params.append(st.session_state.ds_gender)
    base_sql += " ORDER BY dynasty_name, full_name LIMIT 60"
    results = q_all(base_sql, tuple(params))

    def age_in_gen(age, gen):
        if gen == "All": return True
        if gen == "Gen Z (< 18)":      return age < 18
        if gen == "Millennial (18–34)": return 18 <= age <= 34
        if gen == "Gen X (35–54)":      return 35 <= age <= 54
        if gen == "Boomer (55–74)":     return 55 <= age <= 74
        if gen == "Senior (75+)":       return age >= 75
        return True

    filtered = []
    for r in results:
        dob_r = ensure_dob(r["dob"]); age_r = calc_age(dob_r)
        if age_in_gen(age_r, st.session_state.ds_gen): filtered.append((r, dob_r, age_r))

    n = len(filtered)
    rc1, rc2 = st.columns([3, 1])
    with rc1:
        st.markdown(f'<div style="font-size:.83rem;color:var(--mist);margin-bottom:.45rem;">{"No results." if n==0 else f"{n} member{"s" if n!=1 else ""} found"}</div>', unsafe_allow_html=True)
    with rc2:
        vw1, vw2 = st.columns(2)
        with vw1:
            if st.button("⊞", key="view_grid", use_container_width=True,
                         type="primary" if st.session_state.search_view == "grid" else "secondary"):
                st.session_state.search_view = "grid"; st.rerun()
        with vw2:
            if st.button("☰", key="view_list", use_container_width=True,
                         type="primary" if st.session_state.search_view == "list" else "secondary"):
                st.session_state.search_view = "list"; st.rerun()

    if n == 0:
        st.markdown('<div class="msg-info">Try a different name, city or clear filters.</div>', unsafe_allow_html=True)
        return

    if st.session_state.search_view == "grid":
        cols = st.columns(3)
        for idx, (r, dob_r, age_r) in enumerate(filtered):
            r_init      = "".join(p[0].upper() for p in r["full_name"].split()[:2])
            r_avatar    = avatar_html(r.get("profile_photo") or None, r_init, 54)
            city_badge  = f'<span class="badge badge-green">{_esc(r["current_city"])}</span>' if r.get("current_city") else '<span class="badge badge-gold">—</span>'
            with cols[idx % 3]:
                st.markdown(f"""
                <div class="member-card">
                    <div style="display:flex;justify-content:center;">{r_avatar}</div>
                    <div class="member-card-name">{_esc(r['full_name'])}</div>
                    <div class="member-card-dynasty">&#127968; {_esc(r['dynasty_name'])}</div>
                    <div style="display:flex;flex-wrap:wrap;justify-content:center;gap:.22rem;margin-top:.45rem;">
                        <span class="badge badge-gold">{_infer_generation(age_r)}</span>
                        {city_badge}
                    </div>
                </div>""", unsafe_allow_html=True)
                if st.button("View Profile", key=f"vp_{r['id']}", use_container_width=True):
                    st.session_state.viewed_profile = dict(r); st.rerun()
    else:
        for r, dob_r, age_r in filtered:
            r_init   = "".join(p[0].upper() for p in r["full_name"].split()[:2])
            r_avatar = avatar_html(r.get("profile_photo") or None, r_init, 42)
            city_str = f" · {_esc(r['current_city'])}" if r.get('current_city') else " · —"
            lc1, lc2 = st.columns([5, 1])
            with lc1:
                st.markdown(f"""
                <div class="member-list-row">
                    {r_avatar}
                    <div><div class="member-list-name">{_esc(r['full_name'])}</div>
                    <div class="member-list-meta">&#127968; {_esc(r['dynasty_name'])} · Age {age_r}{city_str} · {_infer_generation(age_r)}</div></div>
                </div>""", unsafe_allow_html=True)
            with lc2:
                if st.button("View", key=f"vlp_{r['id']}", use_container_width=True):
                    st.session_state.viewed_profile = dict(r); st.rerun()

# ══════════════════════════════════════════════════════════════════════════════
# 3.1  FAMILY ALBUM
# ══════════════════════════════════════════════════════════════════════════════
def _family_album_tab(uid, dynasty):
    if st.session_state.current_album_id:
        _album_detail_view(uid, dynasty)
        return

    st.markdown('<div style="font-family:\'Cormorant Garamond\',serif;font-size:1.55rem;font-weight:700;color:var(--bark);margin-bottom:.8rem;">📸 Family Album</div>', unsafe_allow_html=True)

    albums = q_all("""
        SELECT a.*, u.full_name as creator_name,
               COUNT(m.id) as media_count
        FROM family_albums a
        LEFT JOIN users u ON u.id = a.user_id
        LEFT JOIN album_media m ON m.album_id = a.id
        WHERE a.user_id = %s OR (a.dynasty_name = %s AND a.privacy = 'dynasty')
        GROUP BY a.id, u.full_name
        ORDER BY a.created_at DESC
    """, (uid, dynasty))

    col_a, col_b = st.columns([3, 1])
    with col_b:
        if st.button("➕ New Album", type="primary", use_container_width=True, key="new_album_btn"):
            st.session_state["_album_creating"] = True

    if st.session_state.get("_album_creating"):
        with st.expander("📁 Create New Album", expanded=True):
            al_title = st.text_input("Album Title *", placeholder="", key="al_title")
            al_desc  = st.text_area("Description", placeholder="", key="al_desc", max_chars=300)
            al_priv  = st.selectbox("Visibility", ["dynasty", "private"], key="al_priv",
                format_func=lambda x: "🏰 Dynasty (shared with family)" if x == "dynasty" else "🔒 Private (only me)")
            al_cover_file = st.file_uploader("Cover Photo (optional)", type=["jpg","jpeg","png","webp"], key="al_cover")
            c1, c2 = st.columns(2)
            with c1:
                if st.button("Cancel", key="al_cancel"):
                    st.session_state["_album_creating"] = False; st.rerun()
            with c2:
                if st.button("Create Album", type="primary", key="al_create"):
                    if not al_title.strip():
                        set_msg("Album title required.", "error")
                    else:
                        cover_data = ""
                        if al_cover_file:
                            cd, err = process_photo_rect(al_cover_file, 600, 400)
                            if err: set_msg(err, "error")
                            else: cover_data = cd
                        q_exec("""INSERT INTO family_albums(user_id,dynasty_name,title,description,cover_photo,privacy)
                                  VALUES(%s,%s,%s,%s,%s,%s)""",
                               (uid, dynasty, al_title.strip(), al_desc.strip(), cover_data, al_priv))
                        set_msg(f"Album '{al_title}' created! 📸", "success")
                        st.session_state["_album_creating"] = False
                    st.rerun()

    show_msg()

    if not albums:
        st.markdown('<div class="msg-info">No albums yet. Create your first family album! 📷</div>', unsafe_allow_html=True)
        return

    cols = st.columns(min(len(albums), 4))
    for idx, alb in enumerate(albums):
        with cols[idx % min(len(albums), 4)]:
            if alb.get("cover_photo"):
                st.markdown(f'<div class="album-card"><img src="{alb["cover_photo"]}" class="album-cover" />', unsafe_allow_html=True)
            else:
                st.markdown('<div class="album-card"><div class="album-cover-placeholder">📁</div>', unsafe_allow_html=True)
            priv_badge = "🏰" if alb["privacy"] == "dynasty" else "🔒"
            st.markdown(f"""
            <div class="album-info">
                <div class="album-title">{alb['title']}</div>
                <div class="album-meta">{priv_badge} · {alb['media_count']} photos · by {alb['creator_name']}</div>
            </div></div>""", unsafe_allow_html=True)
            if st.button("Open", key=f"open_al_{alb['id']}", use_container_width=True):
                st.session_state.current_album_id = alb["id"]
                st.session_state.album_view = "grid"
                st.session_state.slideshow_idx = 0
                st.rerun()


def _album_detail_view(uid, dynasty):
    alb_id = st.session_state.current_album_id
    alb = q_one("SELECT a.*, u.full_name as creator_name FROM family_albums a LEFT JOIN users u ON u.id=a.user_id WHERE a.id=%s", (alb_id,))
    if not alb:
        set_msg("Album not found.", "error"); st.session_state.current_album_id = None; st.rerun()

    media = q_all("""
        SELECT m.*, u.full_name as uploader_name FROM album_media m
        LEFT JOIN users u ON u.id = m.user_id
        WHERE m.album_id = %s ORDER BY m.taken_on DESC NULLS LAST, m.created_at DESC
    """, (alb_id,))

    col_back, col_title, col_acts = st.columns([1, 3, 2])
    with col_back:
        if st.button("← Albums", key="back_to_albums"):
            st.session_state.current_album_id = None; st.rerun()
    with col_title:
        st.markdown(f'<div style="font-family:\'Cormorant Garamond\',serif;font-size:1.4rem;font-weight:700;color:var(--bark);">{alb["title"]}</div>', unsafe_allow_html=True)
        st.markdown(f'<div style="font-size:.76rem;color:var(--mist);">{alb.get("description","")}</div>', unsafe_allow_html=True)
    with col_acts:
        vw_col1, vw_col2, vw_col3 = st.columns(3)
        with vw_col1:
            if st.button("⊞", key="av_grid", use_container_width=True,
                         type="primary" if st.session_state.album_view == "grid" else "secondary"):
                st.session_state.album_view = "grid"; st.rerun()
        with vw_col2:
            if st.button("▶", key="av_slide", use_container_width=True,
                         type="primary" if st.session_state.album_view == "slideshow" else "secondary"):
                st.session_state.album_view = "slideshow"; st.rerun()
        with vw_col3:
            if st.button("📅", key="av_timeline", use_container_width=True,
                         type="primary" if st.session_state.album_view == "timeline" else "secondary"):
                st.session_state.album_view = "timeline"; st.rerun()

    with st.expander("📤 Add Photos to Album"):
        uf_col1, uf_col2 = st.columns(2)
        with uf_col1:
            up_files = st.file_uploader("Choose photos", type=["jpg","jpeg","png","webp"],
                accept_multiple_files=True, key=f"up_photos_{alb_id}")
            up_caption  = st.text_input("Caption (all)", placeholder="", key=f"up_cap_{alb_id}")
            up_location = st.text_input("Location",      placeholder="", key=f"up_loc_{alb_id}")
        with uf_col2:
            up_tags    = st.text_input("Tags (comma separated)", placeholder="", key=f"up_tags_{alb_id}")
            up_date= st.date_input("Date Taken", value=date.today(), key=f"up_date_{alb_id}", format="DD/MM/YYYY")

        if st.button("Upload", type="primary", key=f"do_upload_{alb_id}"):
            if not up_files:
                set_msg("Select at least one photo.", "error")
            else:
                errors, count = [], 0
                for f in up_files:
                    pd, err = process_photo_rect(f)
                    if err: errors.append(err)
                    else:
                        q_exec("""INSERT INTO album_media(album_id,user_id,media_data,caption,location,tags,taken_on)
                                  VALUES(%s,%s,%s,%s,%s,%s,%s)""",
                               (alb_id, uid, pd, up_caption.strip(), up_location.strip(),
                                up_tags.strip(), up_date))
                        count += 1
                if count: set_msg(f"{count} photo(s) uploaded! 📸", "success")
                if errors: set_msg("; ".join(errors), "error")
            st.rerun()

    show_msg()

    if not media:
        st.markdown('<div class="msg-info">No photos yet. Upload the first one! 📷</div>', unsafe_allow_html=True)
        return

    if st.session_state.album_view == "grid":
        cols = st.columns(4)
        for idx, m in enumerate(media):
            with cols[idx % 4]:
                st.image(m["media_data"], use_container_width=True)
                if m.get("caption"):
                    st.caption(m["caption"])
                reactions = q_all("SELECT reaction, COUNT(*) as cnt FROM media_reactions WHERE media_id=%s GROUP BY reaction", (m["id"],))
                r_str = "  ".join(f'{r["reaction"]} {r["cnt"]}' for r in reactions) if reactions else ""
                if r_str:
                    st.markdown(f'<div style="font-size:.8rem;color:var(--mist);">{r_str}</div>', unsafe_allow_html=True)
                rc1, rc2 = st.columns(2)
                with rc1:
                    if st.button("❤️", key=f"react_{m['id']}", help="Like", use_container_width=True):
                        try:
                            q_exec("INSERT INTO media_reactions(media_id,user_id,reaction) VALUES(%s,%s,'❤️') ON CONFLICT DO NOTHING", (m["id"], uid))
                        except: pass
                        st.rerun()
                with rc2:
                    if alb["user_id"] == uid or m["user_id"] == uid:
                        if st.button("🗑️", key=f"del_media_{m['id']}", use_container_width=True):
                            q_exec("DELETE FROM album_media WHERE id=%s", (m["id"],))
                            set_msg("Photo removed.", "info"); st.rerun()

    elif st.session_state.album_view == "slideshow":
        idx = st.session_state.slideshow_idx % len(media)
        m   = media[idx]
        st.markdown(f'<div style="text-align:center;font-size:.78rem;color:var(--mist);">Photo {idx+1} of {len(media)}</div>', unsafe_allow_html=True)
        st.image(m["media_data"], use_container_width=True)
        if m.get("caption"):
            st.markdown(f'<div style="text-align:center;font-size:.9rem;color:var(--ink);margin:.4rem 0;">{m["caption"]}</div>', unsafe_allow_html=True)
        if m.get("location"):
            st.markdown(f'<div style="text-align:center;font-size:.76rem;color:var(--mist);">📍 {m["location"]}</div>', unsafe_allow_html=True)
        nav1, nav2, nav3 = st.columns([1, 2, 1])
        with nav1:
            if st.button("◀ Prev", use_container_width=True, key="slide_prev"):
                st.session_state.slideshow_idx = (idx - 1) % len(media); st.rerun()
        with nav2:
            if m.get("taken_on"):
                st.markdown(f'<div style="text-align:center;font-size:.76rem;color:var(--mist);">📅 {m["taken_on"]}</div>', unsafe_allow_html=True)
        with nav3:
            if st.button("Next ▶", use_container_width=True, key="slide_next"):
                st.session_state.slideshow_idx = (idx + 1) % len(media); st.rerun()

    elif st.session_state.album_view == "timeline":
        from collections import defaultdict
        by_date = defaultdict(list)
        for m in media:
            key = str(m.get("taken_on") or m["created_at"].date() if m.get("created_at") else "Unknown")
            by_date[key].append(m)
        for dt in sorted(by_date.keys(), reverse=True):
            st.markdown(f'<div class="tl-event"><div class="tl-dot"></div><div class="tl-card">', unsafe_allow_html=True)
            try: dt_fmt = date.fromisoformat(dt).strftime("%d %B %Y")
            except: dt_fmt = dt
            st.markdown(f'<div style="font-size:.78rem;color:var(--mist);margin-bottom:.5rem;">📅 {dt_fmt} — {len(by_date[dt])} photo(s)</div>', unsafe_allow_html=True)
            tl_cols = st.columns(min(len(by_date[dt]), 4))
            for j, m in enumerate(by_date[dt]):
                with tl_cols[j % 4]:
                    st.image(m["media_data"], use_container_width=True)
                    if m.get("caption"): st.caption(m["caption"])
            st.markdown('</div></div>', unsafe_allow_html=True)

    if alb["user_id"] == uid:
        st.markdown('<hr class="fancy-divider">', unsafe_allow_html=True)
        with st.expander("⚠️ Danger Zone"):
            if st.button("🗑️ Delete Album", key="del_album"):
                q_exec("DELETE FROM family_albums WHERE id=%s", (alb_id,))
                set_msg("Album deleted.", "info")
                st.session_state.current_album_id = None; st.rerun()

# ══════════════════════════════════════════════════════════════════════════════
# 3.2  FAMILY DIARY
# ══════════════════════════════════════════════════════════════════════════════
def _family_diary_tab(uid):
    mode = st.session_state.diary_mode

    if mode in ("new", "edit"):
        entry = None
        if mode == "edit" and st.session_state.diary_entry_id:
            entry = q_one("SELECT * FROM family_diary WHERE id=%s AND user_id=%s",
                          (st.session_state.diary_entry_id, uid))
        if mode == "edit" and not entry:
            set_msg("Entry not found.", "error"); st.session_state.diary_mode = "list"; st.rerun()

        st.markdown(f'<div style="font-family:\'Cormorant Garamond\',serif;font-size:1.45rem;font-weight:700;color:var(--bark);margin-bottom:.8rem;">{"✏️ Edit Entry" if mode=="edit" else "📝 New Diary Entry"}</div>', unsafe_allow_html=True)

        d_title   = st.text_input("Title *", value=entry["title"] if entry else "", placeholder="", key="d_title")
        d_date    = st.date_input("Date", value=ensure_dob(entry["entry_date"]) if entry else date.today(), key="d_date", format="DD/MM/YYYY")
        d_content = st.text_area("Write your entry…", value=entry["content"] if entry else "",
            height=280, key="d_content", placeholder="")

        col1, col2, col3 = st.columns(3)
        with col1:
            mood_opts = [""] + MOODS
            d_mood = st.selectbox("Mood", mood_opts,
                index=mood_opts.index(entry["mood"]) if entry and entry["mood"] in mood_opts else 0,
                key="d_mood")
        with col2:
            d_tags = st.text_input("Tags", value=entry["tags"] if entry else "",
                placeholder="", key="d_tags")
        with col3:
            priv_opts = ["private", "dynasty"]
            d_priv = st.selectbox("Privacy", priv_opts,
                index=priv_opts.index(entry["privacy"]) if entry and entry["privacy"] in priv_opts else 0,
                key="d_priv",
                format_func=lambda x: "🔒 Private" if x == "private" else "🏰 Dynasty")

        btn1, btn2, btn3, btn4 = st.columns(4)
        with btn1:
            if st.button("← Back", key="d_back"):
                st.session_state.diary_mode = "list"; st.rerun()
        with btn2:
            if st.button("💾 Save Draft", key="d_draft"):
                if not d_title.strip():
                    set_msg("Title required.", "error"); st.rerun()
                if mode == "new":
                    q_exec("INSERT INTO family_diary(user_id,title,content,tags,mood,privacy,is_draft,entry_date) VALUES(%s,%s,%s,%s,%s,%s,TRUE,%s)",
                           (uid, d_title.strip(), d_content.strip(), d_tags.strip(), d_mood, d_priv, d_date))
                else:
                    q_exec("UPDATE family_diary SET title=%s,content=%s,tags=%s,mood=%s,privacy=%s,is_draft=TRUE,entry_date=%s,updated_at=NOW() WHERE id=%s",
                           (d_title.strip(), d_content.strip(), d_tags.strip(), d_mood, d_priv, d_date, entry["id"]))
                set_msg("Draft saved! 📝", "success")
                st.session_state.diary_mode = "list"; st.rerun()
        with btn3:
            if st.button("✅ Publish", type="primary", key="d_publish"):
                if not d_title.strip() or not d_content.strip():
                    set_msg("Title and content required.", "error"); st.rerun()
                if mode == "new":
                    q_exec("INSERT INTO family_diary(user_id,title,content,tags,mood,privacy,is_draft,entry_date) VALUES(%s,%s,%s,%s,%s,%s,FALSE,%s)",
                           (uid, d_title.strip(), d_content.strip(), d_tags.strip(), d_mood, d_priv, d_date))
                else:
                    q_exec("UPDATE family_diary SET title=%s,content=%s,tags=%s,mood=%s,privacy=%s,is_draft=FALSE,entry_date=%s,updated_at=NOW() WHERE id=%s",
                           (d_title.strip(), d_content.strip(), d_tags.strip(), d_mood, d_priv, d_date, entry["id"]))
                set_msg("Entry published! ✨", "success")
                st.session_state.diary_mode = "list"; st.rerun()
        with btn4:
            if mode == "edit" and st.button("🗑️ Delete", key="d_del"):
                q_exec("DELETE FROM family_diary WHERE id=%s AND user_id=%s", (entry["id"], uid))
                set_msg("Entry deleted.", "info")
                st.session_state.diary_mode = "list"; st.rerun()
        show_msg()
        return

    if mode == "view" and st.session_state.diary_entry_id:
        entry = q_one("SELECT * FROM family_diary WHERE id=%s", (st.session_state.diary_entry_id,))
        if not entry:
            set_msg("Entry not found.", "error"); st.session_state.diary_mode = "list"; st.rerun()
        entry = dict(entry)
        c1, c2 = st.columns([1, 3])
        with c1:
            if st.button("← Diary", key="d_view_back"): st.session_state.diary_mode = "list"; st.rerun()
        with c2:
            if entry["user_id"] == uid:
                if st.button("✏️ Edit", key="d_edit_btn", type="primary"):
                    st.session_state.diary_entry_id = entry["id"]
                    st.session_state.diary_mode = "edit"; st.rerun()
        mood_str = f'<span class="diary-mood">{entry["mood"]}</span>' if entry.get("mood") else ""
        st.markdown(f"""
        <div class="diary-date">{ensure_dob(entry['entry_date']).strftime('%A, %d %B %Y')}</div>
        <div style="font-family:'Cormorant Garamond',serif;font-size:1.8rem;font-weight:700;color:var(--bark);">{mood_str}{entry['title']}</div>
        """, unsafe_allow_html=True)
        if entry.get("tags"):
            for t in entry["tags"].split(","):
                if t.strip(): st.markdown(f'<span class="badge badge-blue"># {t.strip()}</span>', unsafe_allow_html=True)
        st.markdown('<hr class="fancy-divider">', unsafe_allow_html=True)
        st.markdown(f'<div class="diary-full-content">{_esc(entry["content"])}</div>', unsafe_allow_html=True)
        st.markdown(f'<div style="font-size:.72rem;color:var(--mist);margin-top:1rem;">{"🔒 Private" if entry["privacy"]=="private" else "🏰 Dynasty"} · {"Draft" if entry["is_draft"] else "Published"}</div>', unsafe_allow_html=True)
        return

    st.markdown('<div style="font-family:\'Cormorant Garamond\',serif;font-size:1.55rem;font-weight:700;color:var(--bark);margin-bottom:.8rem;">📖 Family Diary</div>', unsafe_allow_html=True)

    col_a, col_b, col_c = st.columns([2, 1, 1])
    with col_a:
        d_search = st.text_input("Search entries…", placeholder="Keywords, tags…", key="d_search", label_visibility="collapsed")
    with col_b:
        d_filter = st.selectbox("Filter", ["All", "Published", "Drafts", "Private", "Dynasty"],
            key="d_filter", label_visibility="collapsed")
    with col_c:
        if st.button("📝 New Entry", type="primary", use_container_width=True, key="new_diary_btn"):
            st.session_state.diary_mode = "new"; st.rerun()

    show_msg()

    sql = "SELECT * FROM family_diary WHERE user_id=%s"
    params = [uid]
    if d_search:
        sql += " AND (title ILIKE %s OR content ILIKE %s OR tags ILIKE %s)"
        params += [f"%{d_search}%"] * 3
    if d_filter == "Published": sql += " AND is_draft=FALSE"
    elif d_filter == "Drafts":  sql += " AND is_draft=TRUE"
    elif d_filter == "Private": sql += " AND privacy='private'"
    elif d_filter == "Dynasty": sql += " AND privacy='dynasty'"
    sql += " ORDER BY entry_date DESC LIMIT 50"
    entries = q_all(sql, tuple(params))

    if not entries:
        st.markdown('<div class="msg-info">No diary entries yet. Write your first one! ✍️</div>', unsafe_allow_html=True)
        return

    for e in entries:
        e = dict(e)
        ed = ensure_dob(e["entry_date"])
        preview = e["content"][:160].replace("\n", " ") + ("…" if len(e["content"]) > 160 else "")
        mood_str = f'<span class="diary-mood">{e["mood"]}</span>' if e.get("mood") else ""
        draft_badge = '<span class="badge badge-gold">Draft</span>' if e.get("is_draft") else ""
        priv_badge = "🔒" if e["privacy"] == "private" else "🏰"

        st.markdown(f"""
        <div class="diary-entry">
            <div class="diary-date">{priv_badge} {ed.strftime('%d %B %Y')} {draft_badge}</div>
            <div class="diary-title">{mood_str}{e['title']}</div>
            <div class="diary-preview">{preview}</div>
            {f'<div style="margin-top:.35rem;">' + "".join(f'<span class="badge badge-blue"># {t.strip()}</span>' for t in e["tags"].split(",") if t.strip()) + '</div>' if e.get("tags") else ""}
        </div>""", unsafe_allow_html=True)
        ec1, ec2 = st.columns([4, 1])
        with ec2:
            if st.button("Read →", key=f"read_entry_{e['id']}", use_container_width=True):
                st.session_state.diary_entry_id = e["id"]
                st.session_state.diary_mode = "view"; st.rerun()

# ══════════════════════════════════════════════════════════════════════════════
# 3.3  FAMILY TIMELINE
# ══════════════════════════════════════════════════════════════════════════════
def _family_timeline_tab(uid, dynasty):
    st.markdown('<div style="font-family:\'Cormorant Garamond\',serif;font-size:1.55rem;font-weight:700;color:var(--bark);margin-bottom:.8rem;">📅 Family Timeline</div>', unsafe_allow_html=True)

    col_f1, col_f2, col_f3, col_f4 = st.columns([2, 1.5, 1.5, 1.2])
    with col_f1:
        et_types_opts = ["All"] + EVENT_TYPES
        tl_filter = st.selectbox("Event Type", et_types_opts,
            index=et_types_opts.index(st.session_state.tl_filter) if st.session_state.tl_filter in et_types_opts else 0,
            key="tl_type_sel", label_visibility="collapsed")
        st.session_state.tl_filter = tl_filter
    with col_f2:
        branch_opts = ["Full Dynasty", "Personal", "Branch"]
        tl_branch_disp = st.selectbox("Branch", branch_opts,
            index=branch_opts.index(st.session_state.tl_branch) if st.session_state.tl_branch in branch_opts else 0,
            key="tl_branch_sel", label_visibility="collapsed")
        st.session_state.tl_branch = tl_branch_disp
    with col_f3:
        tl_search = st.text_input("Search events…", placeholder="Name, place…", key="tl_search", label_visibility="collapsed")
    with col_f4:
        if st.button("➕ Add Event", type="primary", use_container_width=True, key="tl_add_btn"):
            st.session_state["_tl_adding"] = True

    if st.session_state.get("_tl_adding"):
        with st.expander("📌 Add Timeline Event", expanded=True):
            et_col1, et_col2 = st.columns(2)
            with et_col1:
                ev_type  = st.selectbox("Event Type *", EVENT_TYPES, key="ev_type")
                ev_title = st.text_input("Title *", placeholder="", key="ev_title")
                ev_date  = st.date_input("Event Date *", key="ev_date", format="DD/MM/YYYY")
                ev_loc   = st.text_input("Location", placeholder="", key="ev_loc")
            with et_col2:
                ev_desc  = st.text_area("Description", placeholder="", key="ev_desc", height=100)
                ev_tags  = st.text_input("Tags", placeholder="", key="ev_tags")
                ev_priv  = st.selectbox("Privacy", ["dynasty", "private"], key="ev_priv",
                    format_func=lambda x: "🏰 Dynasty" if x == "dynasty" else "🔒 Private")
                ev_media_file = st.file_uploader("Attach Photo (optional)", type=["jpg","jpeg","png","webp"], key="ev_media")

            ec1, ec2 = st.columns(2)
            with ec1:
                if st.button("Cancel", key="ev_cancel"):
                    st.session_state["_tl_adding"] = False; st.rerun()
            with ec2:
                if st.button("Add to Timeline", type="primary", key="ev_save"):
                    if not ev_title.strip():
                        set_msg("Event title required.", "error")
                    else:
                        media_data = ""
                        if ev_media_file:
                            md, err = process_photo_rect(ev_media_file, 600, 400)
                            if err: set_msg(err, "error")
                            else: media_data = md
                        q_exec("""INSERT INTO family_timeline
                                  (user_id,dynasty_name,event_type,title,description,event_date,location,tags,media_data,privacy)
                                  VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                               (uid, dynasty, ev_type, ev_title.strip(), ev_desc.strip(),
                                ev_date, ev_loc.strip(), ev_tags.strip(), media_data, ev_priv))
                        set_msg(f"Event '{ev_title}' added to timeline! 🎉", "success")
                        st.session_state["_tl_adding"] = False
                    st.rerun()

    show_msg()

    if st.session_state.tl_branch == "Personal":
        tl_sql = "SELECT t.*, u.full_name as creator_name FROM family_timeline t LEFT JOIN users u ON u.id=t.user_id WHERE t.user_id=%s"
        tl_params = [uid]
    else:
        tl_sql = "SELECT t.*, u.full_name as creator_name FROM family_timeline t LEFT JOIN users u ON u.id=t.user_id WHERE (t.dynasty_name=%s AND t.privacy='dynasty') OR t.user_id=%s"
        tl_params = [dynasty, uid]

    if st.session_state.tl_filter != "All":
        tl_sql += " AND t.event_type=%s"
        tl_params.append(st.session_state.tl_filter)
    if tl_search:
        tl_sql += " AND (t.title ILIKE %s OR t.description ILIKE %s OR t.location ILIKE %s)"
        tl_params += [f"%{tl_search}%"] * 3
    tl_sql += " ORDER BY t.event_date DESC LIMIT 80"
    events = q_all(tl_sql, tuple(tl_params))

    if not events:
        st.markdown('<div class="msg-info">No timeline events yet. Add your family\'s first milestone! 🌟</div>', unsafe_allow_html=True)
        return

    st.markdown(f'<div style="font-size:.82rem;color:var(--mist);margin-bottom:.6rem;">{len(events)} event(s) across {len(set(ev["event_type"] for ev in events))} type(s)</div>', unsafe_allow_html=True)

    from collections import defaultdict
    by_decade = defaultdict(list)
    for ev in events:
        yr = ev["event_date"].year if hasattr(ev["event_date"], "year") else int(str(ev["event_date"])[:4])
        decade = (yr // 10) * 10
        by_decade[decade].append(ev)

    for decade in sorted(by_decade.keys(), reverse=True):
        st.markdown(f"""
        <div style="font-family:'Cormorant Garamond',serif;font-size:1.25rem;font-weight:700;
                    color:var(--bark);margin:.5rem 0 .8rem;padding-left:.3rem;">
            {decade}s
        </div>""", unsafe_allow_html=True)

        for ev in sorted(by_decade[decade], key=lambda e: e["event_date"], reverse=True):
            ev = dict(ev)
            type_colors = {
                "🎂 Birth": "#059669", "💍 Marriage": "#C9A84C", "⚰️ Death": "#6B7280",
                "🏠 Migration": "#2563EB", "🎓 Education": "#7C3AED", "💼 Career": "#D97706",
            }
            dot_color = next((v for k, v in type_colors.items() if k in ev["event_type"]), "#C9A84C")

            st.markdown(f"""
            <div class="tl-event">
                <div class="tl-dot" style="background:{dot_color};box-shadow:0 0 0 2px {dot_color};"></div>
                <div class="tl-card">
                    <div style="display:flex;justify-content:space-between;align-items:flex-start;flex-wrap:wrap;gap:.3rem;">
                        <div>
                            <div class="tl-event-type">{ev['event_type']}</div>
                            <div class="tl-title">{ev['title']}</div>
                        </div>
                        <div style="text-align:right;">
                            <div class="tl-date">{ev['event_date'].strftime('%d %b %Y') if hasattr(ev['event_date'],'strftime') else ev['event_date']}</div>
                            <div style="font-size:.7rem;color:var(--mist);">by {ev.get('creator_name','')}</div>
                        </div>
                    </div>
                    {f'<div class="tl-desc">{ev["description"]}</div>' if ev.get("description") else ""}
                    {f'<div class="tl-loc">📍 {ev["location"]}</div>' if ev.get("location") else ""}
                    {f'<div style="margin-top:.4rem;">' + "".join(f'<span class="badge badge-blue"># {t.strip()}</span>' for t in ev["tags"].split(",") if t.strip()) + '</div>' if ev.get("tags") else ""}
                </div>
            </div>""", unsafe_allow_html=True)

            if ev.get("media_data") or ev["user_id"] == uid:
                ec1, ec2 = st.columns([4, 1])
                with ec1:
                    if ev.get("media_data"):
                        st.image(ev["media_data"], width=300)
                with ec2:
                    if ev["user_id"] == uid:
                        if st.button("🗑️", key=f"del_ev_{ev['id']}", help="Delete event"):
                            q_exec("DELETE FROM family_timeline WHERE id=%s", (ev["id"],))
                            set_msg("Event removed.", "info"); st.rerun()

# ══════════════════════════════════════════════════════════════════════════════
# FAMILY LINKS TAB — with bidirectional link support (PATCHED)
# ══════════════════════════════════════════════════════════════════════════════
def _family_links_tab(uid):
    u = st.session_state.user
    links = get_links(uid)

    st.markdown('<div class="card-title">👨‍👩‍👧‍👦 Family Links</div>', unsafe_allow_html=True)

    if links:
        # Normalize relation names before grouping so variant spellings
        # (e.g. "Brother-in-law (Jija)") are bucketed under the canonical key.
        grouped = {}
        for lk in links:
            canonical_rel = normalize_relation(lk["relation"])
            grouped.setdefault(canonical_rel, []).append(lk)

        # Track any relations that don't belong to any known group
        ungrouped_rels = set(grouped.keys()) - set(
            r for rels in RELATION_GROUPS.values() for r in rels
        )

        for group_label, group_rels in RELATION_GROUPS.items():
            group_hits = [r for r in group_rels if r in grouped]
            if not group_hits:
                continue
            st.markdown(
                f'<div style="font-size:.7rem;text-transform:uppercase;'
                f'letter-spacing:1.2px;color:var(--mist);margin:.75rem 0 .25rem;">'
                f'{group_label}</div>',
                unsafe_allow_html=True
            )
            for rel in group_hits:
                for lk in grouped[rel]:
                    name    = lk.get("linked_name") or lk["member_name"]
                    dynasty = f"· {lk['linked_dynasty']}" if lk.get("linked_dynasty") else ""
                    # Show canonical relation; note original in tooltip if different
                    raw_rel = lk["relation"]
                    display_rel = rel if rel == raw_rel else f"{rel}"
                    badge   = (
                        '<span class="badge badge-green">✓ Verified</span>'
                        if lk.get("member_id")
                        else '<span class="badge badge-gold">Unregistered</span>'
                    )
                    lk_init = "".join(p[0].upper() for p in name.split()[:2])
                    mini_av = avatar_html(lk.get("linked_photo") or None, lk_init, 30)
                    c1, c2  = st.columns([5, 1])
                    with c1:
                        st.markdown(
                            f'<div class="rel-chip">{mini_av}'
                            f'<span class="rel-type">{display_rel}</span>'
                            f'<span>{name}</span>'
                            f'<span style="color:var(--mist);font-size:.78rem;">{dynasty}</span>'
                            f'{badge}</div>',
                            unsafe_allow_html=True
                        )
                    with c2:
                        if st.button("✕", key=f"rm_lk_{lk['id']}", help="Remove link"):
                            _remove_link_handler(lk, uid, name)
                            st.rerun()

        # Show any truly unrecognized relations under "Others"
        if ungrouped_rels:
            st.markdown(
                '<div style="font-size:.7rem;text-transform:uppercase;'
                'letter-spacing:1.2px;color:var(--mist);margin:.75rem 0 .25rem;">'
                '🌐 Others</div>',
                unsafe_allow_html=True
            )
            for rel in sorted(ungrouped_rels):
                for lk in grouped[rel]:
                    name = lk.get("linked_name") or lk["member_name"]
                    badge = (
                        '<span class="badge badge-green">✓ Verified</span>'
                        if lk.get("member_id")
                        else '<span class="badge badge-gold">Unregistered</span>'
                    )
                    lk_init = "".join(p[0].upper() for p in name.split()[:2])
                    mini_av = avatar_html(lk.get("linked_photo") or None, lk_init, 30)
                    c1, c2  = st.columns([5, 1])
                    with c1:
                        st.markdown(
                            f'<div class="rel-chip">{mini_av}'
                            f'<span class="rel-type">{rel}</span>'
                            f'<span>{name}</span>{badge}</div>',
                            unsafe_allow_html=True
                        )
                    with c2:
                        if st.button("✕", key=f"rm_lk_{lk['id']}", help="Remove link"):
                            _remove_link_handler(lk, uid, name)
                            st.rerun()
    else:
        st.markdown(
            '<div class="msg-info">No family links yet. Add one below 👇</div>',
            unsafe_allow_html=True
        )

    st.markdown('<hr class="fancy-divider">', unsafe_allow_html=True)
    st.markdown("**🔗 Link a Registered Member**")

    with st.expander("Search & link a registered member", expanded=True):
        rel_type = relation_selectbox("Relation", key="add_rel", default="Son")
        sq = st.text_input("Search by name, email or dynasty", key="link_search")
        if sq:
            results = q_all(
                """SELECT * FROM users WHERE id != %s AND (
                    full_name ILIKE %s OR dynasty_name ILIKE %s OR email ILIKE %s
                ) LIMIT 10""",
                (uid, f"%{sq}%", f"%{sq}%", f"%{sq}%")
            )
            if results:
                for res in results:
                    dob_r    = ensure_dob(res["dob"])
                    res_init = "".join(p[0].upper() for p in res["full_name"].split()[:2])
                    rc1, rc2 = st.columns([3, 1])
                    with rc1:
                        _res_av = avatar_html(res.get("profile_photo") or None, res_init, 34)
                        st.markdown(
                            f'<div class="search-result" style="display:flex;align-items:center;gap:.6rem;">'
                            f'{_res_av}'
                            f'<div><strong>{_esc(res["full_name"])}</strong> · '
                            f'<span style="color:var(--mist);">{_esc(res["dynasty_name"])}</span> · '
                            f'Age {calc_age(dob_r)}'
                            f'{(" · " + _esc(res["current_city"])) if res.get("current_city") else " · —"}'
                            f'</div></div>',
                            unsafe_allow_html=True
                        )
                    with rc2:
                        if st.button("Link", key=f"lnk_{res['id']}"):
                            _link_button_handler(uid, res, rel_type)
                            st.rerun()
            else:
                st.markdown(
                    '<div class="msg-info">No members found.</div>',
                    unsafe_allow_html=True
                )

    st.markdown('<hr class="fancy-divider">', unsafe_allow_html=True)
    st.markdown("**➕ Add Unregistered Family Member**")
    with st.expander("Manually add a name"):
        mn = st.text_input("Member Name", key="manual_name")
        mr = relation_selectbox("Relation", key="manual_rel", default="Son")
        if st.button("Add Member", key="manual_add"):
            if not mn.strip():
                set_msg("Enter a name.", "error")
            else:
                # Unregistered members have no member_id so no reciprocal needed
                q_exec(
                    "INSERT INTO family_links(user_id, member_name, relation) VALUES(%s,%s,%s)",
                    (uid, mn.strip(), mr)
                )
                set_msg(f"Added {mn} as {mr}.", "success")
            st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
# SETTINGS TAB
# ══════════════════════════════════════════════════════════════════════════════
def _settings_tab(uid):
    u = st.session_state.user
    initials = "".join(p[0].upper() for p in u["full_name"].split()[:2])
    st.markdown('<div class="card-title">⚙️ Edit Profile</div>', unsafe_allow_html=True)

    st.markdown("**📷 Profile Photo**")
    current_photo = u.get("profile_photo") or None
    new_photo_file = st.file_uploader("Upload new photo (JPG/PNG, max 800 KB)",
        type=["jpg","jpeg","png","webp"], key="settings_photo", label_visibility="collapsed")

    preview_photo = current_photo
    if new_photo_file:
        pd, err = process_photo(new_photo_file)
        if err: set_msg(err, "error")
        else: preview_photo = pd

    col_prev, col_btn = st.columns([1, 2])
    with col_prev:
        _prev_av    = avatar_html(preview_photo, initials, 76)
        _prev_label = "New preview" if new_photo_file else "Current photo"
        st.markdown(f'<div class="photo-preview-wrap">{_prev_av}'
            f'<span style="font-size:.75rem;color:var(--mist);">{_prev_label}</span>'
            f'</div>', unsafe_allow_html=True)
    with col_btn:
        st.write(""); st.write("")
        sc1, sc2 = st.columns(2)
        with sc1:
            if st.button("💾 Save Photo", type="primary", use_container_width=True, disabled=not new_photo_file):
                if new_photo_file:
                    pd, err = process_photo(new_photo_file)
                    if err: set_msg(err, "error")
                    else:
                        q_exec("UPDATE users SET profile_photo=%s WHERE id=%s", (pd, uid))
                        get_user.clear()
                        st.session_state.user = dict(get_user(uid))
                        set_msg("Profile photo updated! 📸", "success")
                st.rerun()
        with sc2:
            if st.button("🗑️ Remove", use_container_width=True, disabled=not current_photo):
                q_exec("UPDATE users SET profile_photo='' WHERE id=%s", (uid,))
                get_user.clear()
                st.session_state.user = dict(get_user(uid))
                set_msg("Photo removed.", "info"); st.rerun()

    st.markdown('<hr class="fancy-divider">', unsafe_allow_html=True)
    with st.form("edit_form"):
        fn  = st.text_input("Full Name",    value=u["full_name"])
        occ = st.text_input("Occupation",   value=u.get("occupation", ""))
        rel = st.text_input("Religion",     value=u.get("religion", ""))
        cst = st.text_input("Caste",        value=u.get("caste", ""))
        got = st.text_input("Gotram",       value=u.get("gotram", ""))
        bc  = st.text_input("Birth City",   value=u.get("birth_city", ""))
        cc  = st.text_input("Current City", value=u.get("current_city", ""))
        opts = ["Prefer not to say", "Male", "Female", "Other"]
        gen = st.selectbox("Gender", opts, index=opts.index(u.get("gender", "Prefer not to say")))
        dyn = st.text_input("Dynasty Name", value=u["dynasty_name"])
        if st.form_submit_button("💾 Save Changes", type="primary"):
            if not fn.strip() or not dyn.strip():
                set_msg("Full Name and Dynasty Name required.", "error")
            else:
                q_exec("""UPDATE users SET full_name=%s,occupation=%s,birth_city=%s,
                           current_city=%s,gender=%s,dynasty_name=%s,
                           religion=%s,caste=%s,gotram=%s WHERE id=%s""",
                       (fn.strip(), occ.strip(), bc.strip(), cc.strip(), gen, dyn.strip(),
                        rel.strip(), cst.strip(), got.strip(), uid))
                get_user.clear()
                st.session_state.user = dict(get_user(uid))
                set_msg("Profile updated! ✨", "success")
            st.rerun()

    st.markdown('<hr class="fancy-divider">', unsafe_allow_html=True)
    st.markdown("**Change Password**")
    with st.form("pass_form"):
        op  = st.text_input("Current Password", type="password")
        np1 = st.text_input("New Password",     type="password")
        np2 = st.text_input("Confirm New Password",  type="password")
        if st.form_submit_button("🔐 Update Password"):
            if not check_pw(op, u["password"]): set_msg("Current password wrong.", "error")
            elif len(np1) < 8: set_msg("New password ≥ 8 chars.", "error")
            elif np1 != np2:   set_msg("Passwords don't match.", "error")
            else:
                q_exec("UPDATE users SET password=%s WHERE id=%s", (hash_pw(np1), uid))
                get_user.clear()
                st.session_state.user = dict(get_user(uid))
                set_msg("Password changed! 🔒", "success")
            st.rerun()

    st.markdown('<hr class="fancy-divider">', unsafe_allow_html=True)
    if st.button("🚪 Logout", use_container_width=True):
        st.session_state.user = None; goto("landing"); st.rerun()

# ══════════════════════════════════════════════════════════════════════════════
# DASHBOARD
# ══════════════════════════════════════════════════════════════════════════════
def page_dashboard():
    u = st.session_state.user
    if not u: goto("login"); st.rerun()

    fresh = get_user(u["id"])
    if fresh: st.session_state.user = dict(fresh); u = st.session_state.user
    else: goto("login"); st.rerun()

    render_hero(); show_msg()

    initials = "".join(p[0].upper() for p in u["full_name"].split()[:2])
    dob      = ensure_dob(u["dob"])
    age      = calc_age(dob)
    dynasty  = u["dynasty_name"]
    links    = get_links(u["id"])
    family_cnt, dynasty_cnt, album_cnt, diary_cnt = get_dashboard_stats(u["id"], dynasty)

    _render_namaste_banner(u, initials, age)
    _render_stat_cards(family_cnt, dynasty_cnt, album_cnt, diary_cnt)

    tab_labels = [
        "👤 Profile", "👨‍👩‍👧‍👦 Links", "📖 Diary",
        "🔍 Search", "🌳 Tree", "📸 Album",
        "📅 Timeline", "📜 Activity", "⚙️ Settings",
    ]
    if st.session_state.active_tab >= len(tab_labels):
        st.session_state.active_tab = 0

    tabs = st.tabs(tab_labels)

    with tabs[0]:
        _detailed_profile_tab(u["id"])
    with tabs[1]:
        _family_links_tab(u["id"])
    with tabs[2]:
        _family_diary_tab(u["id"])
    with tabs[3]:
        _dynasty_search_tab(u["id"])
    with tabs[4]:
        st.markdown('<div style="font-family:\'Cormorant Garamond\',serif;font-size:1.4rem;font-weight:700;color:var(--bark);margin-bottom:.7rem;">🌳 Interactive Family Tree</div>', unsafe_allow_html=True)
        _tree_links = get_links(u["id"])
        if not _tree_links:
            st.markdown('<div class="msg-info">Go to <strong>Links</strong> tab to add family members first!</div>', unsafe_allow_html=True)
        else:
            _family_tree_tab(u["id"])
    with tabs[5]:
        _family_album_tab(u["id"], dynasty)
    with tabs[6]:
        _family_timeline_tab(u["id"], dynasty)
    with tabs[7]:
        feed = get_activity_feed(u["id"], dynasty)
        st.markdown('<div class="feed-title">📜 Recent Activity</div>', unsafe_allow_html=True)
        if feed:
            for item in feed:
                st.markdown(f"""
                <div class="feed-item">
                    <div class="feed-dot {item['dot']}"></div>
                    <div>
                        <div class="feed-text">{item['text']}</div>
                        <div class="feed-time">{fmt_feed_time(item['time'])}</div>
                    </div>
                </div>""", unsafe_allow_html=True)
        else:
            st.markdown('<div class="feed-empty">No recent activity yet. Start by adding family members! 🌱</div>', unsafe_allow_html=True)
    with tabs[8]:
        _settings_tab(u["id"])

# ── Router ────────────────────────────────────────────────────────────────────
p = st.session_state.page
if   p == "landing":   page_landing()
elif p == "login":     page_login()
elif p == "register":  page_register()
elif p == "dashboard":
    if st.session_state.user: page_dashboard()
    else: goto("login"); st.rerun()
else:
    goto("landing"); st.rerun()
