"""Khởi tạo index trên máy mới từ package đã đóng gói.

Dùng sau khi clone code repo. Chạy MỘT LẦN trước khi chạy app.

Cách dùng (chạy từ gốc repo, bằng Python trong venv):
  # Từ HF Dataset:
  .venv\\Scripts\\python.exe scripts\\init_index.py --hf-repo MinhTriet/dvc-rag-embeddings

  # Từ file local (ổ USB / shared drive / đã download thủ công):
  .venv\\Scripts\\python.exe scripts\\init_index.py --from ktem_index.tar.gz

  # Chỉ verify index đã có (không download):
  .venv\\Scripts\\python.exe scripts\\init_index.py --verify
"""
from __future__ import annotations

import argparse
import sqlite3
import tarfile
from pathlib import Path


# ─── helpers ─────────────────────────────────────────────────────────────────

def _read_env_data_dir() -> Path:
    env = Path(__file__).resolve().parent.parent / ".env"  # .env ở gốc repo
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("KH_APP_DATA_DIR="):
                return Path(line.split("=", 1)[1].strip())
    return Path(r"C:\ktem_data")


def _check_env() -> list[str]:
    """Trả về danh sách cảnh báo về .env."""
    warnings = []
    env = Path(__file__).resolve().parent.parent / ".env"  # .env ở gốc repo
    if not env.exists():
        warnings.append(".env chưa tồn tại — copy từ .env.example và điền Azure key")
        return warnings
    content = env.read_text(encoding="utf-8")
    for key in ("AZURE_OPENAI_ENDPOINT", "AZURE_OPENAI_API_KEY", "AZURE_OPENAI_EMBEDDINGS_DEPLOYMENT"):
        if key + "=" not in content or f"{key}=\n" in content:
            warnings.append(f"{key} chưa được set trong .env")
    return warnings


# ─── verify ──────────────────────────────────────────────────────────────────

def verify(data_dir: Path) -> bool:
    ok = True
    user_data = data_dir / "user_data"

    # HNSW bin files
    vs = user_data / "vectorstore"
    bin_files = list(vs.glob("**/*.bin")) if vs.exists() else []
    data_bins = [f for f in bin_files if f.name == "data_level0.bin" and f.stat().st_size > 0]
    if data_bins:
        print(f"  ✅ HNSW: data_level0.bin = {data_bins[0].stat().st_size / 1e6:.0f} MB")
    else:
        print("  ❌ HNSW: data_level0.bin không có hoặc rỗng")
        ok = False

    # docstore
    ds = user_data / "docstore"
    if ds.exists():
        mb = sum(f.stat().st_size for f in ds.rglob("*") if f.is_file()) / 1e6
        print(f"  ✅ docstore: {mb:.0f} MB")
    else:
        print("  ❌ docstore: không tồn tại")
        ok = False

    # sql.db
    sql_db = user_data / "sql.db"
    if sql_db.exists():
        con = sqlite3.connect(str(sql_db))
        try:
            sources = con.execute("SELECT COUNT(*) FROM [index__1__source]").fetchone()[0]
            chunks  = con.execute("SELECT COUNT(*) FROM [index__1__index]").fetchone()[0]
            emb_n   = con.execute("SELECT COUNT(*) FROM embedding").fetchone()[0]
        finally:
            con.close()
        print(f"  ✅ sql.db: {sources} tài liệu, {chunks} chunks")
        if emb_n == 0:
            print("  ✅ embedding table rỗng — sẽ tự register từ .env khi khởi động lần đầu")
        else:
            print(f"  ⚠️  embedding table có {emb_n} rows (nếu là máy mới nên để trống)")
    else:
        print("  ❌ sql.db không tồn tại")
        ok = False

    return ok


# ─── extract ─────────────────────────────────────────────────────────────────

def extract(tar_path: Path, data_dir: Path) -> None:
    if not tar_path.exists():
        raise SystemExit(f"File không tồn tại: {tar_path}")

    size_mb = tar_path.stat().st_size / 1e6
    print(f"Giải nén {tar_path.name} ({size_mb:.0f} MB) → {data_dir} ...")
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "user_data").mkdir(parents=True, exist_ok=True)

    with tarfile.open(tar_path, "r:gz") as tar:
        tar.extractall(path=str(data_dir))
    print("  Xong.")


# ─── HF download ─────────────────────────────────────────────────────────────

def download_hf(repo_id: str, filename: str, token: str | None) -> Path:
    try:
        from huggingface_hub import hf_hub_download
    except ImportError:
        raise SystemExit("Thiếu thư viện: pip install huggingface-hub")

    print(f"Downloading {filename} từ hf://datasets/{repo_id} ...")
    local = hf_hub_download(
        repo_id=repo_id,
        filename=filename,
        repo_type="dataset",
        token=token,
    )
    print(f"  Lưu tại: {local}")
    return Path(local)


# ─── main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(description="Khởi tạo kotaemon index trên máy mới")
    src = ap.add_mutually_exclusive_group()
    src.add_argument("--from", dest="from_file", metavar="FILE",
                     help="Path đến file ktem_index.tar.gz local")
    src.add_argument("--hf-repo", metavar="USER/REPO",
                     help="HF Dataset repo id")
    src.add_argument("--verify", action="store_true",
                     help="Chỉ kiểm tra index đã có, không download")

    ap.add_argument("--hf-file", default="ktem_index.tar.gz",
                    help="Tên file trong HF repo (mặc định: ktem_index.tar.gz)")
    ap.add_argument("--hf-token", default=None,
                    help="HF token (chỉ cần cho repo private)")
    ap.add_argument("--data", default=None,
                    help="Đường dẫn đích (mặc định đọc KH_APP_DATA_DIR từ .env)")
    args = ap.parse_args()

    data_dir = Path(args.data) if args.data else _read_env_data_dir()

    # --- download / extract ---
    if args.from_file:
        extract(Path(args.from_file), data_dir)
    elif args.hf_repo:
        tar_path = download_hf(args.hf_repo, args.hf_file, args.hf_token)
        extract(tar_path, data_dir)
    elif not args.verify:
        ap.print_help()
        print("\nVí dụ (chạy từ gốc repo):\n"
              "  python scripts\\init_index.py --from ktem_index.tar.gz\n"
              "  python scripts\\init_index.py --hf-repo MinhTriet/dvc-rag-embeddings\n"
              "  python scripts\\init_index.py --verify")
        return

    # --- verify ---
    print(f"\nKiểm tra index tại {data_dir}:")
    ok = verify(data_dir)

    # --- .env check ---
    env_warnings = _check_env()

    print()
    if ok and not env_warnings:
        print("✅ Index sẵn sàng. Chạy app từ gốc repo:")
        print(f"   .venv\\Scripts\\python.exe app\\app.py")
    else:
        if not ok:
            print("❌ Index chưa hợp lệ — kiểm tra lại bước download/extract.")
        if env_warnings:
            print("⚠️  Cần cấu hình .env trước khi chạy app:")
            for w in env_warnings:
                print(f"   - {w}")
            print(f"   Mẫu: .env.example (ở gốc repo)")


if __name__ == "__main__":
    main()
