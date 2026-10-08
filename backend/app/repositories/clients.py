from typing import Iterable, Optional

from supabase import Client


def list_active_clients_for_members(
    db: Client, member_ids: Iterable[str]
) -> Optional[list[dict]]:
    """Return tenant-scoped clients, or None when no rows are found."""
    ids = list(member_ids)
    if not ids:
        return None
    result = (
        db.table("clients")
        .select("*")
        .eq("is_deleted", False)
        .in_("created_by", ids)
        .execute()
    )
    return result.data if result.data else None


def list_active_clients(db: Client) -> list[dict]:
    return db.table("clients").select("*").eq("is_deleted", False).execute().data or []


def list_client_ids_for_owners(db: Client, owner_ids: Iterable[str]) -> set[str]:
    ids = list(owner_ids)
    if not ids:
        return set()
    requirements = (
        db.table("requirements")
        .select("client_id")
        .in_("created_by", ids)
        .eq("is_deleted", False)
        .execute()
        .data
        or []
    )
    return {row["client_id"] for row in requirements if row.get("client_id")}


def list_clients_for_owner_ids(db: Client, owner_ids: Iterable[str]) -> list[dict]:
    owner_set = set(owner_ids)
    if not owner_set:
        return []
    client_ids = list_client_ids_for_owners(db, owner_set)
    clients = list_active_clients(db)
    return [
        client
        for client in clients
        if client["id"] in client_ids or client.get("created_by") in owner_set
    ]


def insert_client(db: Client, payload: dict):
    return db.table("clients").insert(payload).execute()


def update_client_record(db: Client, client_id: str, name: str):
    return db.table("clients").update({"name": name}).eq("id", client_id).execute()


def soft_delete_client(db: Client, client_id: str):
    return (
        db.table("clients").update({"is_deleted": True}).eq("id", client_id).execute()
    )
