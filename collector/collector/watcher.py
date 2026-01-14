"""File system watcher for Claude log files."""

import json
import logging
import time
from pathlib import Path
from typing import Callable

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileModifiedEvent, FileCreatedEvent

from .config import Config

logger = logging.getLogger(__name__)


class StateManager:
    """Manages file processing state to avoid duplicate processing."""

    def __init__(self, state_path: Path):
        self.state_path = state_path
        self._state: dict[str, int] = {}
        self._load()

    def _load(self) -> None:
        """Load state from disk."""
        if self.state_path.exists():
            try:
                with open(self.state_path) as f:
                    self._state = json.load(f)
                logger.info(f"Loaded state for {len(self._state)} files")
            except (json.JSONDecodeError, IOError) as e:
                logger.warning(f"Could not load state file: {e}")
                self._state = {}

    def _save(self) -> None:
        """Save state to disk."""
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.state_path, "w") as f:
            json.dump(self._state, f, indent=2)

    def get_position(self, file_path: str) -> int:
        """Get last processed position for a file."""
        return self._state.get(file_path, 0)

    def set_position(self, file_path: str, position: int) -> None:
        """Set processed position for a file."""
        self._state[file_path] = position
        self._save()


class LogFileHandler(FileSystemEventHandler):
    """Handles file system events for JSONL log files."""

    def __init__(
        self,
        on_line: Callable[[str, int, dict], None],
        state_manager: StateManager,
    ):
        """Initialize handler.

        Args:
            on_line: Callback called with (file_path, line_offset, raw_json) for each line
            state_manager: Tracks processed file positions
        """
        super().__init__()
        self.on_line = on_line
        self.state_manager = state_manager

    def on_created(self, event: FileCreatedEvent) -> None:
        """Handle new file creation."""
        if event.is_directory:
            return
        if event.src_path.endswith(".jsonl"):
            logger.info(f"New log file: {event.src_path}")
            self._process_file(event.src_path)

    def on_modified(self, event: FileModifiedEvent) -> None:
        """Handle file modification."""
        if event.is_directory:
            return
        if event.src_path.endswith(".jsonl"):
            self._process_file(event.src_path)

    def _process_file(self, file_path: str) -> None:
        """Process new lines in a log file."""
        try:
            position = self.state_manager.get_position(file_path)

            with open(file_path, "r") as f:
                f.seek(position)
                new_lines = 0

                while True:
                    line_offset = f.tell()
                    line = f.readline()
                    if not line:
                        break

                    line = line.strip()
                    if not line:
                        continue

                    # Sanitize null bytes - PostgreSQL JSONB can't store \u0000
                    # These appear when Claude reads binary files
                    line = line.replace("\\u0000", "").replace("\x00", "")

                    try:
                        raw_json = json.loads(line)
                        self.on_line(file_path, line_offset, raw_json)
                        new_lines += 1
                    except json.JSONDecodeError as e:
                        logger.warning(f"Invalid JSON at {file_path}:{line_offset}: {e}")

                new_position = f.tell()
                if new_position > position:
                    self.state_manager.set_position(file_path, new_position)
                    if new_lines > 0:
                        logger.debug(f"Processed {new_lines} lines from {file_path}")

        except IOError as e:
            logger.error(f"Error processing file {file_path}: {e}")


class LogWatcher:
    """Watches Claude projects directory for log file changes."""

    def __init__(
        self,
        config: Config,
        on_line: Callable[[str, int, dict], None],
    ):
        """Initialize watcher.

        Args:
            config: Collector configuration
            on_line: Callback called with (file_path, line_offset, raw_json) for each line
        """
        self.config = config
        self.state_manager = StateManager(config.state_path)
        self.handler = LogFileHandler(on_line, self.state_manager)
        self.observer = Observer()

    def process_existing_files(self) -> None:
        """Process all existing JSONL files on startup."""
        logger.info(f"Scanning existing files in {self.config.claude_projects_path}")

        if not self.config.claude_projects_path.exists():
            logger.warning(f"Projects path does not exist: {self.config.claude_projects_path}")
            return

        for jsonl_file in self.config.claude_projects_path.rglob("*.jsonl"):
            self.handler._process_file(str(jsonl_file))

    def start(self) -> None:
        """Start watching for file changes."""
        if not self.config.claude_projects_path.exists():
            logger.warning(f"Projects path does not exist: {self.config.claude_projects_path}")
            self.config.claude_projects_path.mkdir(parents=True, exist_ok=True)

        self.observer.schedule(
            self.handler,
            str(self.config.claude_projects_path),
            recursive=True,
        )
        self.observer.start()
        logger.info(f"Started watching {self.config.claude_projects_path}")

    def stop(self) -> None:
        """Stop watching for file changes."""
        self.observer.stop()
        self.observer.join()
        logger.info("Stopped file watcher")

    def run_forever(self) -> None:
        """Run the watcher until interrupted."""
        self.start()
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info("Received interrupt, stopping...")
        finally:
            self.stop()
