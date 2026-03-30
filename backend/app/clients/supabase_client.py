"""
Supabase client wrapper for common CRUD operations.
"""

from app.dependencies import get_supabase


def get_athlete(db=None):
    """Get the current athlete profile."""
    if db is None:
        db = get_supabase()
    result = db.table("athletes").select("*").limit(1).execute()
    return result.data[0] if result.data else None


def upsert_athlete(data: dict, db=None):
    """Create or update the athlete profile."""
    if db is None:
        db = get_supabase()
    existing = get_athlete(db)
    if existing:
        return db.table("athletes").update(data).eq("id", existing["id"]).execute()
    return db.table("athletes").insert(data).execute()
