import os
import re

with open('browser_manager.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

def get_block(start_marker, end_marker):
    start = -1
    end = -1
    for i, line in enumerate(lines):
        if start_marker in line:
            start = i
        if start != -1 and end_marker and end_marker in line and i > start:
            end = i
            break
    if end == -1:
        end = len(lines)
    return "".join(lines[start:end])

# This is a bit complex. Let's just do it manually with multi_replace or copy-pasting via python script that knows exactly where to slice.

