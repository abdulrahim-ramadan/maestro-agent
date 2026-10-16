from pathlib import Path

from maestro.knowledge.store import ManualStore

MANUALS_DIR = Path(__file__).resolve().parents[3] / "data" / "manuals"


def main() -> None:
    store = ManualStore()
    chunk_count = store.index(MANUALS_DIR)
    print(f"Indexed {chunk_count} chunks from {MANUALS_DIR}")


if __name__ == "__main__":
    main()
