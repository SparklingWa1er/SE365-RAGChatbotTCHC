"""Đóng gói index đã ingest để chia sẻ (upload HF Dataset hoặc copy thủ công).

Thực hiện:
  1. Validate index (bin files tồn tại, sql.db có data)
  2. Clone sql.db và XÓA bảng embedding (chứa API key) — máy mới sẽ
     tự re-register từ .env khi khởi động lần đầu
  3. Nén vectorstore + docstore + files + sql.db thành tar.gz
  4. (tuỳ chọn) Upload lên HF Dataset

Dùng:
  python pack_index.py
  python pack_index.py --out my_index.tar.gz
  python pack_index.py --hf-repo user/thu-tuc-hc-index
  python pack_index.py --hf-repo user/thu-tuc-hc-index --hf-token hf_xxx
"""
from __future__ import annotations

import argparse
import shutil
import sqlite3
import tarfile
import tempfile
from pathlib import Path


def _read_env_data_dir() -> Path:
    env = Path(__file__).resolve().parent.parent / "kotaemon-app" / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("KH_APP_DATA_DIR="):
                return Path(line.split("=", 1)[1].strip())
    return Path(r"C:\ktem_data")


def validate(data_dir: Path) -> None:
    user_data = data_dir / "user_data"
    errors = []

    bin_files = list((user_data / "vectorstore").glob("**/*.bin")) if (user_data / "vectorstore").exists() else []
    data_bin = [f for f in bin_files if f.name == "data_level0.bin" and f.stat().st_size > 0]
    if not data_bin:
        errors.append("Không có data_level0.bin — vectorstore chưa đủ (chạy ingest xong chưa?)")

    if not (user_data / "docstore").exists():
        errors.append("docstore không tồn tại")

    sql_db = user_data / "sql.db"
    if not sql_db.exists():
        errors.append("sql.db không tồn tại")
    else:
        con = sqlite3.connect(str(sql_db))
        try:
            n = con.execute("SELECT COUNT(*) FROM [index__1__source]").fetchone()[0]
        finally:
            con.close()
        if n == 0:
            errors.append("index__1__source rỗng — chưa ingest")
        else:
            print(f"  ✅ {n} tài liệu, {len(bin_files)} bin files, data_level0.bin = {data_bin[0].stat().st_size / 1e6:.0f} MB")

    if errors:
        for e in errors:
            print(f"  ❌ {e}")
        raise SystemExit("Validation thất bại.")


def _dir_mb(path: Path) -> float:
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file()) / 1e6


def pack(data_dir: Path, out_path: Path) -> None:
    user_data = data_dir / "user_data"

    print(f"Đọc index từ: {data_dir}")
    validate(data_dir)

    with tempfile.TemporaryDirectory() as tmp:
        # Tạo bản sao sql.db đã xóa API key
        tmp_db = Path(tmp) / "sql.db"
        shutil.copy2(user_data / "sql.db", tmp_db)
        con = sqlite3.connect(str(tmp_db))
        try:
            con.execute("DELETE FROM embedding")
            con.commit()
        finally:
            con.close()
        print("  API key đã được xóa khỏi bản sao sql.db")

        print(f"\nĐóng gói → {out_path} ...")
        with tarfile.open(out_path, "w:gz") as tar:
            vs = user_data / "vectorstore"
            ds = user_data / "docstore"
            fi = user_data / "files"

            if vs.exists():
                tar.add(vs, arcname="user_data/vectorstore")
                print(f"  + vectorstore/ ({_dir_mb(vs):.0f} MB)")
            if ds.exists():
                tar.add(ds, arcname="user_data/docstore")
                print(f"  + docstore/    ({_dir_mb(ds):.0f} MB)")
            if fi.exists():
                tar.add(fi, arcname="user_data/files")
                print(f"  + files/       ({_dir_mb(fi):.0f} MB)")
            tar.add(tmp_db, arcname="user_data/sql.db")
            print(f"  + sql.db       (embedding table cleared)")

        print(f"\n✅ {out_path}  ({out_path.stat().st_size / 1e6:.0f} MB)")


def upload_hf(tar_path: Path, repo_id: str, token: str | None) -> None:
    try:
        from huggingface_hub import HfApi
    except ImportError:
        raise SystemExit("Thiếu thư viện: pip install huggingface-hub")

    api = HfApi(token=token)
    api.create_repo(repo_id=repo_id, repo_type="dataset", exist_ok=True)
    print(f"\nUploading → hf://datasets/{repo_id}/{tar_path.name} ...")
    api.upload_file(
        path_or_fileobj=str(tar_path),
        path_in_repo=tar_path.name,
        repo_id=repo_id,
        repo_type="dataset",
    )
    print(f"✅ https://huggingface.co/datasets/{repo_id}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Đóng gói kotaemon index để chia sẻ")
    ap.add_argument("--data", default=None, help="KH_APP_DATA_DIR (mặc định đọc từ .env)")
    ap.add_argument("--out", default="ktem_index.tar.gz", help="File tar.gz đầu ra")
    ap.add_argument("--hf-repo", default=None, help="HF Dataset repo id (user/name)")
    ap.add_argument("--hf-token", default=None, help="HF write token")
    args = ap.parse_args()

    data_dir = Path(args.data) if args.data else _read_env_data_dir()
    out_path = Path(args.out)

    pack(data_dir, out_path)

    if args.hf_repo:
        upload_hf(out_path, args.hf_repo, args.hf_token)
    else:
        print("\nUpload thủ công lên HF:")
        print(f"  python pack_index.py --hf-repo <user/dataset-name> --hf-token hf_xxx")
        print(f"  hoặc copy {out_path} sang máy khác và dùng init_index.py --from {out_path}")


if __name__ == "__main__":
    main()
