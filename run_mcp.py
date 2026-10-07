from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from kaze_feed.server import main

if __name__ == "__main__":
    main()
