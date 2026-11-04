import csv
import hashlib
import os
import sqlite3
from datetime import datetime


# =============================================================================
# NkparamDB — SQLite pool for nkparam tokens
# =============================================================================

class NkparamDB:
    def __init__(self, db_path="nkparams.db"):
        self.db_path = db_path
        self._init_db()

    def _connect(self):
        return sqlite3.connect(self.db_path)

    def _init_db(self):
        conn = self._connect()
        cursor = conn.cursor()

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS nkparams (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nkparam TEXT UNIQUE,
            is_active INTEGER DEFAULT 1
        )
        """)

        conn.commit()
        conn.close()

    def add_nkparam(self, nkparam):
        conn = self._connect()
        cursor = conn.cursor()

        try:
            cursor.execute(
                "INSERT OR IGNORE INTO nkparams (nkparam, is_active) VALUES (?, 1)",
                (nkparam,)
            )
            conn.commit()
        finally:
            conn.close()

    def get_nkparam(self):
        conn = self._connect()
        cursor = conn.cursor()

        try:
            cursor.execute("""
                SELECT id, nkparam
                FROM nkparams
                WHERE is_active = 1
                LIMIT 1
            """)
            row = cursor.fetchone()

            if row:
                nk_id, nkparam = row

                cursor.execute(
                    "UPDATE nkparams SET is_active = 0 WHERE id = ?",
                    (nk_id,)
                )
                conn.commit()

                return nkparam

            return None

        finally:
            conn.close()


# =============================================================================
# AppliedJobsDB — SQLite store for applied job records
#
# Replaces applied_jobs.csv with a proper indexed store.
# Primary key is a 16-char SHA-256 prefix of  "{job_id}|{company.lower()}".
# has_applied() also checks the raw job_id column so legacy CSV-migrated
# records (stored with empty company) are matched correctly.
# =============================================================================

_CSV_FIELDS = ["hash", "job_id", "title", "company", "location", "ai_score", "applied_at"]


class AppliedJobsDB:

    def __init__(self, db_path: str = "applied_jobs.db", csv_path: str = "applied_jobs.csv"):
        self.db_path  = db_path
        self.csv_path = csv_path
        self._init_db()
        self._init_csv()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def _init_csv(self) -> None:
        if not os.path.exists(self.csv_path):
            with open(self.csv_path, "w", newline="", encoding="utf-8") as f:
                csv.DictWriter(f, fieldnames=_CSV_FIELDS).writeheader()

    def _init_db(self) -> None:
        conn = self._connect()
        cur  = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS applied_jobs (
                hash        TEXT PRIMARY KEY,
                job_id      TEXT NOT NULL,
                title       TEXT,
                company     TEXT,
                location    TEXT,
                ai_score    INTEGER,
                applied_at  TEXT NOT NULL
            )
        """)
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_job_id ON applied_jobs(job_id)"
        )
        conn.commit()
        conn.close()

    # ── Hash ──────────────────────────────────────────────────────────────────

    @staticmethod
    def _hash(job_id: str, company: str) -> str:
        """16-char hex prefix of SHA-256("{job_id}|{company_lower}")."""
        key = f"{job_id}|{(company or '').lower().strip()}"
        return hashlib.sha256(key.encode()).hexdigest()[:16]

    # ── Dedup check ───────────────────────────────────────────────────────────

    def has_applied(self, job_id: str, company: str) -> bool:
        """
        True if this job was applied to before.
        Checks both the full hash and the raw job_id so legacy CSV-migrated
        records (empty company) are matched without re-applying.
        """
        h    = self._hash(job_id, company)
        conn = self._connect()
        cur  = conn.cursor()
        try:
            cur.execute(
                "SELECT 1 FROM applied_jobs WHERE hash = ? OR job_id = ? LIMIT 1",
                (h, job_id),
            )
            return cur.fetchone() is not None
        finally:
            conn.close()

    # ── Write ─────────────────────────────────────────────────────────────────

    def mark_applied(self, job, ai_score: int = None) -> str:
        """Record an application in both SQLite and CSV. Returns the hash."""
        h          = self._hash(job.job_id, job.company)
        title      = getattr(job, "title",    "")
        company    = getattr(job, "company",  "")
        location   = getattr(job, "location", "")
        applied_at = datetime.utcnow().isoformat()

        self._insert_raw(h, job.job_id, title, company, location, ai_score, applied_at)
        self._append_csv(h, job.job_id, title, company, location, ai_score, applied_at)
        return h

    def _append_csv(self, hash_id, job_id, title, company, location, ai_score, applied_at) -> None:
        with open(self.csv_path, "a", newline="", encoding="utf-8") as f:
            csv.DictWriter(f, fieldnames=_CSV_FIELDS).writerow({
                "hash":       hash_id,
                "job_id":     job_id,
                "title":      title,
                "company":    company,
                "location":   location,
                "ai_score":   ai_score if ai_score is not None else "",
                "applied_at": applied_at,
            })

    def _insert_raw(
        self,
        hash_id:    str,
        job_id:     str,
        title:      str,
        company:    str,
        location:   str,
        ai_score,
        applied_at: str,
    ) -> None:
        conn = self._connect()
        cur  = conn.cursor()
        try:
            cur.execute(
                """INSERT OR IGNORE INTO applied_jobs
                   (hash, job_id, title, company, location, ai_score, applied_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (hash_id, job_id, title, company, location, ai_score, applied_at),
            )
            conn.commit()
        finally:
            conn.close()

    # ── Read ──────────────────────────────────────────────────────────────────

    def list_applied(self, limit: int = 50) -> list[dict]:
        conn = self._connect()
        cur  = conn.cursor()
        try:
            cur.execute(
                """SELECT hash, job_id, title, company, location, ai_score, applied_at
                   FROM applied_jobs
                   ORDER BY applied_at DESC
                   LIMIT ?""",
                (limit,),
            )
            cols = [c[0] for c in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]
        finally:
            conn.close()

    def total(self) -> int:
        conn = self._connect()
        cur  = conn.cursor()
        try:
            cur.execute("SELECT COUNT(*) FROM applied_jobs")
            return cur.fetchone()[0]
        finally:
            conn.close()

    # ── Delete ────────────────────────────────────────────────────────────────

    def remove(self, hash_id: str) -> bool:
        """Remove a record by its hash. Returns True if a row was deleted."""
        conn = self._connect()
        cur  = conn.cursor()
        try:
            cur.execute("DELETE FROM applied_jobs WHERE hash = ?", (hash_id,))
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()
