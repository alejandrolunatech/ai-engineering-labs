"""Allow `python -m golden_path` when the console script is not installed."""

from golden_path.cli import app

if __name__ == "__main__":
    app(prog_name="ai-golden-path")
