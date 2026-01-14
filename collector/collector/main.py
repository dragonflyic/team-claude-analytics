"""Main entry point for the Claude log collector."""

import logging
import sys
import signal

from .config import Config
from .db import DatabaseClient
from .watcher import LogWatcher

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
    ],
)

logger = logging.getLogger(__name__)


def main() -> None:
    """Main entry point."""
    logger.info("Starting Claude log collector")

    # Load configuration
    config = Config.from_env()
    logger.info(f"Collector host: {config.collector_host}")
    logger.info(f"Watching: {config.claude_projects_path}")
    logger.info(f"Database: {config.db_host}:{config.db_port}/{config.db_name}")

    # Initialize database client
    db = DatabaseClient(config)

    try:
        db.connect()
        db.init_schema()
    except Exception as e:
        logger.error(f"Failed to initialize database: {e}")
        logger.info("Will retry connection when processing entries...")

    # Track statistics
    stats = {"inserted": 0, "skipped": 0, "errors": 0}

    def on_line(file_path: str, line_offset: int, raw_json: dict) -> None:
        """Handle a new log line."""
        try:
            inserted = db.insert_raw_line(
                config.collector_host, file_path, line_offset, raw_json
            )
            if inserted:
                stats["inserted"] += 1
                logger.debug(f"Inserted line from {file_path}:{line_offset}")
            else:
                stats["skipped"] += 1
        except Exception as e:
            stats["errors"] += 1
            logger.error(f"Error inserting line: {e}")

    # Set up signal handler to show stats on exit
    def signal_handler(sig, frame):
        logger.info(f"Stats: inserted={stats['inserted']}, skipped={stats['skipped']}, errors={stats['errors']}")
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Start watcher
    watcher = LogWatcher(config, on_line)

    # Process existing files first
    watcher.process_existing_files()
    logger.info(f"Initial sync complete: inserted={stats['inserted']}, skipped={stats['skipped']}")

    # Watch for new changes
    logger.info("Watching for new log entries...")
    watcher.run_forever()


if __name__ == "__main__":
    main()
