"""Minimal asciicast v2 recorder using only the Python standard library.

Records a command in a pseudo-terminal, capturing real output with real inter-chunk timing,
and writes a valid asciicast v2 file. Used because the `asciinema` binary isn't installed; the
output (and timing) is genuine, not synthesized.
"""

import json
import os
import pty
import select
import sys
import time

OUT = sys.argv[1]
CMD = sys.argv[2:]

events = []
start = [None]


def _on_read(fd):
    data = os.read(fd, 65536)
    if data:
        now = time.time()
        if start[0] is None:
            start[0] = now
        events.append([round(now - start[0], 4), "o", data.decode("utf-8", "replace")])
    return data


pid, fd = pty.fork()
if pid == 0:
    os.execvp(CMD[0], CMD)
else:
    try:
        while True:
            r, _, _ = select.select([fd], [], [], 15)
            if fd in r and not _on_read(fd):
                break
    except OSError:
        pass  # EIO is the normal signal that the child closed the pty
    os.waitpid(pid, 0)

header = {
    "version": 2,
    "width": 98,
    "height": 32,
    "env": {"TERM": "xterm-256color", "SHELL": "/bin/bash"},
}
with open(OUT, "w") as f:
    f.write(json.dumps(header) + "\n")
    for e in events:
        f.write(json.dumps(e) + "\n")
print(f"wrote {OUT}: {len(events)} output events, {events[-1][0] if events else 0}s")
