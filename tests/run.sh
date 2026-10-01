#!/bin/sh
# Run all tests: sh tests/run.sh   (Python 3; the page checks also use node if installed)
cd "$(dirname "$0")" && exec python3 -m unittest discover -v -p 'test_*.py' "$@"
