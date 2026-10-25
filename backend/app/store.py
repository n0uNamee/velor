"""Local SQLite storage; all public lookups include the authenticated owner."""
import json
import sqlite3
from pathlib import Path

from .models import Gallery, ImageRef, Outfit, Product, Profile, RequestState


class Store:
    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.upload_dir = data_dir / "uploads"
        self.upload_dir.mkdir(parents=True, exist_ok=True)
        self.path = data_dir / "velor.sqlite3"
        with self.connect() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS profiles (owner TEXT PRIMARY KEY, document TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS requests (id TEXT PRIMARY KEY, owner TEXT NOT NULL, document TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS requests_owner ON requests(owner);
                CREATE TABLE IF NOT EXISTS uploads (id TEXT PRIMARY KEY, owner TEXT NOT NULL, path TEXT NOT NULL, document TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS gallery (owner TEXT NOT NULL, id TEXT NOT NULL, document TEXT NOT NULL, products TEXT NOT NULL, PRIMARY KEY(owner,id));
                CREATE TABLE IF NOT EXISTS provider_calls (id TEXT PRIMARY KEY, cache_key TEXT NOT NULL, reserved REAL NOT NULL, charged REAL NOT NULL, status TEXT NOT NULL, result TEXT);
            """)
            if "actual_cost" not in {row[1] for row in db.execute("PRAGMA table_info(provider_calls)")}:
                db.execute("ALTER TABLE provider_calls ADD COLUMN actual_cost REAL")

    def connect(self):
        return sqlite3.connect(self.path, timeout=15)

    def profile(self, owner: str) -> Profile | None:
        with self.connect() as db:
            row = db.execute("SELECT document FROM profiles WHERE owner=?", (owner,)).fetchone()
        return Profile.model_validate_json(row[0]) if row else None

    def save_profile(self, owner: str, profile: Profile) -> None:
        with self.connect() as db:
            db.execute("INSERT INTO profiles VALUES (?,?) ON CONFLICT(owner) DO UPDATE SET document=excluded.document", (owner, profile.model_dump_json()))

    def request(self, owner: str, request_id: str) -> RequestState | None:
        with self.connect() as db:
            row = db.execute("SELECT document FROM requests WHERE owner=? AND id=?", (owner, request_id)).fetchone()
        return RequestState.model_validate_json(row[0]) if row else None

    def save_request(self, owner: str, state: RequestState) -> None:
        with self.connect() as db:
            db.execute("INSERT INTO requests VALUES (?,?,?) ON CONFLICT(id) DO UPDATE SET document=excluded.document WHERE requests.owner=excluded.owner", (state.id, owner, state.model_dump_json()))

    def all_requests(self) -> list[tuple[str, RequestState]]:
        with self.connect() as db:
            rows = db.execute("SELECT owner, document FROM requests").fetchall()
        return [(owner, RequestState.model_validate_json(doc)) for owner, doc in rows]

    def save_upload(self, owner: str, ref: ImageRef, path: Path) -> None:
        with self.connect() as db:
            db.execute("INSERT INTO uploads VALUES (?,?,?,?)", (ref.id, owner, str(path), ref.model_dump_json()))

    def upload(self, owner: str, image_id: str) -> tuple[ImageRef, Path] | None:
        with self.connect() as db:
            row = db.execute("SELECT document,path FROM uploads WHERE owner=? AND id=?", (owner, image_id)).fetchone()
        return (ImageRef.model_validate_json(row[0]), Path(row[1])) if row else None

    def upload_usage(self, owner: str) -> tuple[int, int]:
        with self.connect() as db:
            rows = db.execute("SELECT path FROM uploads WHERE owner=?", (owner,)).fetchall()
        return len(rows), sum(Path(row[0]).stat().st_size for row in rows if Path(row[0]).is_file())

    def save_outfit(self, owner: str, outfit: Outfit, products: list[Product]) -> None:
        with self.connect() as db:
            db.execute("INSERT INTO gallery VALUES (?,?,?,?) ON CONFLICT(owner,id) DO UPDATE SET document=excluded.document, products=excluded.products", (owner, outfit.id, outfit.model_dump_json(), json.dumps([p.model_dump() for p in products])))

    def gallery(self, owner: str) -> Gallery:
        with self.connect() as db:
            rows = db.execute("SELECT document,products FROM gallery WHERE owner=? ORDER BY rowid DESC", (owner,)).fetchall()
        products = {}
        outfits = []
        for doc, items in rows:
            outfits.append(Outfit.model_validate_json(doc))
            for product in json.loads(items):
                products[product["id"]] = Product.model_validate(product)
        return Gallery(outfits=outfits, products=list(products.values()))

    def provider_cached(self, cache_key: str) -> str | None:
        with self.connect() as db:
            row = db.execute("SELECT result FROM provider_calls WHERE cache_key=? AND status='complete' ORDER BY rowid DESC LIMIT 1", (cache_key,)).fetchone()
        return row[0] if row else None

    def reserve_provider_call(self, call_id: str, cache_key: str, reserve: float, budget: float) -> bool:
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            spent = db.execute("SELECT COALESCE(SUM(charged),0) FROM provider_calls").fetchone()[0]
            if reserve <= 0 or spent + reserve > budget + 1e-9:
                return False
            db.execute("INSERT INTO provider_calls (id,cache_key,reserved,charged,status,result) VALUES (?,?,?,?,?,NULL)", (call_id, cache_key, reserve, reserve, "reserved"))
        return True

    def finish_provider_call(self, call_id: str, result: str | None, actual_cost: float | None = None) -> None:
        # Unknown/failed calls consume their reservation; never promise a free retry.
        with self.connect() as db:
            row = db.execute("SELECT reserved,charged FROM provider_calls WHERE id=?", (call_id,)).fetchone()
            if row:
                charge = max(row[0], row[1], actual_cost or 0)
                status = "complete" if result is not None else "uncertain"
                db.execute("UPDATE provider_calls SET charged=?,status=?,result=?,actual_cost=COALESCE(?,actual_cost) WHERE id=?", (charge, status, result, actual_cost, call_id))

    def provider_actual_cost(self) -> float:
        with self.connect() as db:
            return db.execute("SELECT COALESCE(SUM(actual_cost),0) FROM provider_calls").fetchone()[0]

    def stop_provider_budget(self, call_id: str, budget: float) -> None:
        with self.connect() as db:
            db.execute("UPDATE provider_calls SET charged=MAX(charged,?) WHERE id=?", (budget + 0.01, call_id))

    def provider_usage(self) -> dict:
        with self.connect() as db:
            total, calls = db.execute("SELECT COALESCE(SUM(charged),0),COUNT(*) FROM provider_calls").fetchone()
        return {"reserved_or_charged_usd": total, "calls": calls}
