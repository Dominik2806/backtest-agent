"""Reading the editable file of a coded signal: bytes only, nothing is imported, compiled or executed.

``read_working_file`` is shared by the gate (``loader.py``, which hashes the file) and by ``bt approve`` (which shows,
hashes and archives the same bytes). It was moved here from ``loader.py`` unchanged, so the messages are the same.
"""

import stat
from pathlib import Path

from backtest_agent.coded.errors import NotApprovedError
from backtest_agent.coded.static import MAX_SOURCE_BYTES

#: The most bytes of the working file that are read. Approved code has at most MAX_SOURCE_BYTES after CRLF became LF,
#: and a file that only uses CRLF is at most twice that long, so a longer file cannot be approved code.
FILE_LIMIT = 2 * MAX_SOURCE_BYTES


def read_working_file(path: Path, shown: str) -> bytes:
    """The bytes of the editable file: a regular file of at most ``FILE_LIMIT`` bytes, else ``NotApprovedError``."""
    too_large = f"{shown} is larger than the limit; approved code is at most {MAX_SOURCE_BYTES // 1024} KiB"
    try:
        info = path.stat()
        if not stat.S_ISREG(info.st_mode):
            raise NotApprovedError(f"{shown} cannot be read (not a regular file)")
        if info.st_size > FILE_LIMIT:
            raise NotApprovedError(too_large)
        with path.open("rb") as handle:
            data = handle.read(FILE_LIMIT + 1)  # one byte more than the limit shows a file that grew since the stat
    except OSError as error:
        raise NotApprovedError(f"{shown} cannot be read ({error.strerror or error})") from None
    if len(data) > FILE_LIMIT:
        raise NotApprovedError(too_large)
    return data
